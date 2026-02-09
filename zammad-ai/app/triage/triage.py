import datetime

from dotenv import load_dotenv
from truststore import inject_into_ssl

from app.core.settings import ZammadAISettings
from app.core.settings.triage import (
    Action,
    ActionRule,
    Category,
    Condition,
    FileTriagePrompts,
    LangfuseTriagePrompts,
    StringTriagePrompts,
    TriagePrompt,
)
from app.core.settings.zammad import ZammadAPISettings, ZammadEAISettings
from app.models.triage import (
    CategorizationResult,
    DaysSinceRequestResponse,
    ProcessingIdResponse,
    TriageResult,
)
from app.models.zammad import ZammadTicket
from app.utils.logging import getLogger
from app.zammad import BaseZammadClient, ZammadAPIClient, ZammadConnectionError, ZammadEAIClient

from .genai_handler import GenAIHandler
from .helper import get_operator_function
from .prompts import SYSTEM_PROMPT_CATEGORIES, SYSTEM_PROMPT_DAYS_SINCE_REQUEST, SYSTEM_PROMPT_PROCESSING_ID

load_dotenv()
inject_into_ssl()
logger = getLogger("zammad-ai.triage")


class TriageError(Exception):
    """Custom exception for errors during the triage process."""


class Triage:
    def __init__(self, settings: ZammadAISettings) -> None:
        """
        Initialize the Triage instance from the provided ZammadAISettings.
        
        Sets up categories, actions, fallback no_category/no_action, action rules, prompt sources (Langfuse, file, or string), prepares system prompts for GenAI, initializes the GenAI handler, and instantiates the appropriate Zammad client.
        
        Parameters:
            settings (ZammadAISettings): Configuration containing triage categories, actions, action rules, prompt definitions, GenAI settings, and Zammad settings.
        
        Raises:
            ValueError: If the configured triage prompts type is unsupported or if the Zammad settings type is unsupported.
        """
        # Triage setup
        self.categories: list[Category] = settings.triage.categories
        self.categories_by_id: dict[int, Category] = {c.id: c for c in settings.triage.categories}

        self.actions: list[Action] = settings.triage.actions
        self.actions_by_id: dict[int, Action] = {a.id: a for a in settings.triage.actions}

        self.no_category: Category = self.categories_by_id.get(
            settings.triage.no_category_id,
            settings.triage.categories[0]
            if settings.triage.categories
            else Category(
                id=0,
                name="Unknown",
            ),
        )
        self.no_action: Action = self.actions_by_id.get(
            settings.triage.no_action_id,
            settings.triage.actions[0]
            if settings.triage.actions
            else Action(
                id=0,
                description="",
                name="Unknown",
            ),
        )

        self.action_rules: list[ActionRule] = settings.triage.action_rules

        # Prompt setup based on the type of prompts provided in settings
        self.prompts: dict[TriagePrompt, str]
        if isinstance(settings.triage.prompts, LangfuseTriagePrompts):
            from app.observe.observer import LangfuseClient

            langfuse_client = LangfuseClient()
            self.prompts = {
                name: langfuse_client.get_prompt(
                    prompt_name=prompt.name,
                    prompt_label=prompt.label,
                )
                for name, prompt in settings.triage.prompts.prompt_map.items()
            }
        elif isinstance(settings.triage.prompts, FileTriagePrompts):
            self.prompts = {
                name: open(file_path, "r", encoding="utf-8").read() for name, file_path in settings.triage.prompts.prompt_map.items()
            }
        elif isinstance(settings.triage.prompts, StringTriagePrompts):
            self.prompts = settings.triage.prompts.prompt_map
        else:
            raise ValueError("Invalid type for triage prompts in configuration")

        # Prepare prompts for GenAI handler with system prompts
        genai_prompts: dict[str, str] = self.prompts.copy()  # type: ignore
        genai_prompts["categories"] = SYSTEM_PROMPT_CATEGORIES
        genai_prompts["days_since_request"] = SYSTEM_PROMPT_DAYS_SINCE_REQUEST
        genai_prompts["processing_id"] = SYSTEM_PROMPT_PROCESSING_ID

        # Initialize GenAI handler with pre-built chains
        self.genai_handler = GenAIHandler(
            genai_settings=settings.genai,
            prompts=genai_prompts,
        )

        self.zammad_client: BaseZammadClient

        # Zammad client setup
        if isinstance(settings.zammad, ZammadAPISettings):
            self.zammad_client = ZammadAPIClient(settings=settings.zammad)
        elif isinstance(settings.zammad, ZammadEAISettings):
            self.zammad_client = ZammadEAIClient(settings=settings.zammad)
        else:
            raise ValueError("Invalid type for Zammad settings in configuration")

        logger.info("Triage initialized successfully.")

    async def perform_triage(self, id: str) -> TriageResult:
        """
        Perform triage for a Zammad ticket identified by its ID.
        
        Parameters:
            id (str): Zammad ticket identifier.
        
        Returns:
            TriageResult: Result containing the resolved category, selected action, human-readable reasoning, and confidence score.
        
        Raises:
            TriageError: When the ticket cannot be retrieved from Zammad (e.g., connection failures).
        """
        # Step 1: Fetch ticket data from Zammad
        try:
            ticket: ZammadTicket = await self.zammad_client.get_ticket(id=id)
        except ZammadConnectionError as e:
            logger.error(msg="Error connecting to Zammad", exc_info=True)
            raise TriageError("Triage failed due to Zammad connection error") from e

        # TODO: Only use the first article or concatenate all articles?
        # Normally the `0` is the customer message, the rest are internal notes
        # But what if there are multiple customer messages? -> edge case

        # Step 2: Check if there are articles in the ticket
        logger.debug(msg=f"Number of articles in ticket {id}: {len(ticket.articles)}")
        if len(ticket.articles) == 0:
            logger.warning(f"No articles found for ticket {id}, returning no_category and no_action")
            return TriageResult(
                category=self.no_category,
                reasoning="Keine Artikel gefunden",
                confidence=1.0,
                action=self.no_action,
            )

        # Step 3: Extract customer message and generate session ID for Langfuse
        customer_message: str = ticket.articles[0].text
        session_id: str = self.genai_handler.langfuse_client.generate_session_id()

        # Step 4: Predict category using LLM
        categorization: CategorizationResult = await self.predict_category(
            message=customer_message,
            session_id=session_id,
        )

        # Step 5: Determine action based on predicted category and conditions
        action_id: int = await self.get_action_id(
            categorization_result=categorization,
            message=customer_message,
            session_id=session_id,
        )
        action: Action = self.actions_by_id.get(action_id, self.no_action)
        # Step 6: Return the triage result
        return TriageResult(
            category=categorization.category if categorization.category else self.no_category,
            action=action,
            reasoning=categorization.reasoning,
            confidence=categorization.confidence,
        )

    async def predict_category(self, message: str, session_id: str) -> CategorizationResult:
        """
        Predict the triage category for a customer message using the GenAI handler.
        
        Parameters:
        	message (str): Customer message to categorize; leading/trailing whitespace is ignored.
        	session_id (str): Langfuse session identifier used for tracing the prediction.
        
        Returns:
        	CategorizationResult: Categorization outcome containing `category`, `reasoning`, and `confidence`. If the message is empty, the predicted category is invalid, or an error occurs, returns a result with `no_category`, an explanatory `reasoning`, and `confidence` set to 1.0.
        """
        if len(message.strip()) == 0:
            logger.warning("Empty message provided for categorization")
            return CategorizationResult(
                category=self.no_category,
                reasoning="Leere Nachricht kann nicht kategorisiert werden",
                confidence=1.0,
            )

        try:
            cat_result: CategorizationResult = await self.genai_handler.predict_category(
                input={
                    "text": message,
                    "role_description": self.prompts.get("role", ""),
                    "categories": self.categories,
                    "categories_prompt": self.prompts.get("categories", ""),
                    "examples": self.prompts.get("examples", ""),
                },
                session_id=session_id,
            )

            if not cat_result.category or cat_result.category.id not in [c.id for c in self.categories]:
                logger.warning("Predicted category is invalid or not found, assigning no_category")
                cat_result.category = self.no_category
                cat_result.reasoning += " (Kategorie ungültig, 'no_category' zugewiesen)"
                cat_result.confidence = 1.0

            # Log the results
            logger.debug(f"Text to categorize: {message[:100] + '...' if len(message) > 100 else message}")
            logger.debug(f"Category: {cat_result.category}")
            logger.debug(f"Reasoning: {cat_result.reasoning}")
            logger.debug(f"Confidence: {cat_result.confidence}")

            return cat_result

        except ImportError:
            # BadRequestError import issue
            logger.error("BadRequestError during categorization", exc_info=True)
            return CategorizationResult(
                category=self.no_category,
                reasoning="Fehler: Request konnte nicht vollendet werden, wahrscheinlich wg. Content-Policy",
                confidence=1.0,
            )
        except Exception as e:
            logger.error("Unexpected error during categorization", exc_info=True)
            return CategorizationResult(
                category=self.no_category,
                reasoning=f"Unerwarteter Fehler: {str(e)}",
                confidence=1.0,
            )

    async def get_action_id(self, categorization_result: CategorizationResult, message: str = "", session_id: str | None = None) -> int:
        """
        Selects the appropriate action ID for a categorization using configured action rules and optional message-derived conditions.
        
        Evaluates action rules associated with the categorization's category. If a rule defines ordered conditions, each condition is evaluated (possibly extracting values from the provided message via the GenAI handler) and its action_id is returned when the condition matches. If a rule matches but none of its conditions match, the rule's default action_id is returned. If the categorization has no category or no rule matches, the configured fallback action ID is returned.
        
        Parameters:
            categorization_result (CategorizationResult): The categorization outcome whose category guides rule selection.
            message (str): Optional text used to extract condition values (e.g., days since request or processing id).
            session_id (str | None): Optional session identifier forwarded to GenAI extraction calls.
        
        Returns:
            int: The chosen action ID, or the fallback action ID when no rule or matching condition is found.
        """

        days_since_request = None
        processing_id = None

        # If no category or it's the no_category, always return no_action
        if not categorization_result.category or categorization_result.category.id == self.no_category.id:
            return self.no_action.id

        # Find matching action rule
        for rule in self.action_rules:
            if rule.category_id == categorization_result.category.id:
                # If there are conditions, evaluate them
                if rule.conditions:
                    conditions: list[Condition] = sorted(rule.conditions, key=lambda c: c.priority)
                    for condition in conditions:
                        if condition.field == "days_since_request":
                            if days_since_request is None:
                                days_result: DaysSinceRequestResponse = await self.genai_handler.extract_days_since_request(
                                    input={
                                        "text": message,
                                        "today": datetime.datetime.now().strftime("%Y-%m-%d"),
                                    },
                                    session_id=session_id,
                                )
                                days_since_request = days_result.days_since_request
                            if (get_operator_function(operator=condition.operator))(days_since_request, condition.value):
                                return condition.action_id

                        if condition.field == "processing_id":
                            if processing_id is None:
                                condition_str: str = "Processing id " + condition.operator + " " + str(condition.value)
                                processing_result: ProcessingIdResponse = await self.genai_handler.extract_processing_id(
                                    input={
                                        "text": message,
                                        "condition": condition_str,
                                    },
                                    session_id=session_id,
                                )
                                processing_id = processing_result.processing_id
                            if get_operator_function(operator=condition.operator)(processing_id, condition.value):
                                return condition.action_id
                return rule.action_id

        # Default action if no rules matched
        return self.no_action.id

    def _id_to_category(self, category_id: int) -> Category:
        """
        Return the Category for the given ID or the configured fallback when no match exists.
        
        Parameters:
            category_id (int): ID of the category to look up.
        
        Returns:
            Category: The matching Category, or the configured fallback Category if no match exists.
        """
        return self.categories_by_id.get(category_id, self.no_category)

    def _id_to_action(self, action_id: int) -> Action:
        """Look up an action by its ID.

        Args:
            action_id: The action ID to look up

        Returns:
            The matching Action or no_action as fallback
        """
        return self.actions_by_id.get(action_id, self.no_action)