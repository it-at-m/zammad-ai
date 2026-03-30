"""Core triage service for ticket categorization and action selection."""

from datetime import date
from time import perf_counter

from dotenv import load_dotenv
from prometheus_client import Gauge, Histogram
from truststore import inject_into_ssl

from app.models.triage import (
    CategorizationResult,
    DaysSinceRequestResponse,
    ProcessingIdResponse,
    TriageResult,
)
from app.models.zammad import ZammadTicket
from app.settings import ZammadAISettings
from app.settings.triage import (
    Action,
    ActionRule,
    Category,
    Condition,
    FileTriagePrompts,
    LangfuseTriagePrompts,
    StringTriagePrompts,
    TriagePrompt,
)
from app.settings.zammad import ZammadAPISettings, ZammadEAISettings
from app.utils.logging import getLogger
from app.utils.paths import get_prompts_dir
from app.utils.prompts import load_prompt
from app.zammad import BaseZammadClient, ZammadAPIClient, ZammadConnectionError, ZammadEAIClient

from .genai_handler import GenAIError, GenAIHandler
from .helper import get_operator_function

load_dotenv()
inject_into_ssl()
logger = getLogger("zammad-ai.triage")

TRIAGE_RUN_DURATION_SECONDS = Histogram(
    name="zammad_ai_triage_run_duration_seconds",
    documentation="Duration of triage service runs in seconds.",
    labelnames=("outcome",),
)

TRIAGE_RUNS_IN_PROGRESS = Gauge(
    name="zammad_ai_triage_runs_in_progress",
    documentation="Number of triage runs currently in progress.",
)


class TriageError(Exception):
    """Custom exception for errors during the triage process."""


class TriageService:
    """Service that classifies tickets and selects follow-up actions."""

    def __init__(self, settings: ZammadAISettings) -> None:
        """Initialize the TriageService with the provided configuration, preparing category/action maps, prompt sources, the GenAI handler, and the Zammad client.

        Parameters:
            settings (ZammadAISettings): Configuration containing triage categories, actions, action rules, prompt definitions (Langfuse, file, or string), GenAI settings, and Zammad settings.

        Raises:
            ValueError: If the configured triage prompts type or Zammad settings type is unsupported.
            TriageError: If Langfuse prompt retrieval fails during prompt initialization.
        """
        # Triage setup
        self.categories: list[Category] = settings.triage.categories
        self.categories_by_name: dict[str, Category] = {c.name: c for c in settings.triage.categories}

        self.actions: list[Action] = settings.triage.actions
        self.actions_by_name: dict[str, Action] = {a.name: a for a in settings.triage.actions}

        self.no_category: Category = self.categories_by_name[settings.triage.no_category_name]
        self.no_action: Action = self.actions_by_name[settings.triage.no_action_name]

        self.action_rules: list[ActionRule] = settings.triage.action_rules

        # Prompt setup based on the type of prompts provided in settings
        self.prompts: dict[TriagePrompt, str]
        if isinstance(settings.triage.prompts, LangfuseTriagePrompts):
            from app.observe import LangfuseClient, LangfuseError

            langfuse_client = LangfuseClient()
            self.prompts = {}
            for name, prompt in settings.triage.prompts.prompt_map.items():
                try:
                    self.prompts[name] = langfuse_client.get_prompt(
                        prompt_name=prompt.name,
                        prompt_label=prompt.label,
                    )
                except LangfuseError as e:
                    logger.error(
                        f"Failed to initialize triage prompts from Langfuse for '{prompt.name}'.",
                        exc_info=True,
                    )
                    raise TriageError("Triage initialization failed due to Langfuse prompt retrieval error.") from e
        elif isinstance(settings.triage.prompts, FileTriagePrompts):
            self.prompts = {name: load_prompt(path) for name, path in settings.triage.prompts.prompt_map.items()}
        elif isinstance(settings.triage.prompts, StringTriagePrompts):
            self.prompts = settings.triage.prompts.prompt_map.copy()
        else:
            raise ValueError("Invalid type for triage prompts in configuration")

        # Prepare prompts for GenAI handler with system prompts
        genai_prompts: dict[str, str] = self.prompts.copy()  # type: ignore

        # Load system prompts from markdown files
        prompts_dir = get_prompts_dir()

        genai_prompts["triage"] = load_prompt(prompts_dir / "triage" / "triage.prompt.md")
        genai_prompts["days_since_request"] = load_prompt(prompts_dir / "triage" / "days_since_request.prompt.md")
        genai_prompts["processing_id"] = load_prompt(prompts_dir / "triage" / "processing_id.prompt.md")

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

    async def perform_triage(self, id: int) -> TriageResult:
        """Triage a Zammad ticket by analyzing its customer message to determine category, action, and any extracted values.

        Parameters:
            id (int): Zammad ticket identifier.

        Returns:
            TriageResult: Result containing the resolved category, selected action, human-readable reasoning, confidence score, and any extracted values (or `None`).

        Raises:
            TriageError: If the ticket cannot be retrieved from Zammad (for example, due to a connection failure).
        """
        start_time: float = perf_counter()
        outcome: str = "error"
        TRIAGE_RUNS_IN_PROGRESS.inc()
        # Step 1: Fetch ticket data from Zammad
        try:
            try:
                ticket: ZammadTicket = await self.zammad_client.get_ticket(id=id)
            except ZammadConnectionError as e:
                logger.error("Error connecting to Zammad", exc_info=True)
                raise TriageError("Triage failed due to Zammad connection error") from e

            # TODO: Only use the first article or concatenate all articles?
            # Normally the `0` is the customer message, the rest are internal notes
            # But what if there are multiple customer messages? -> edge case

            # Step 2: Check if there are articles in the ticket
            logger.debug(f"Number of articles in ticket {id}: {len(ticket.articles)}")
            if len(ticket.articles) == 0:
                logger.warning(f"No articles found for ticket {id}, returning no_category and no_action")
                return TriageResult(
                    user_text="",
                    category=self.no_category,
                    reasoning="No articles found",
                    confidence=1.0,
                    action=self.no_action,
                    extracted_values=None,
                )

            try:
                # Step 3: Extract customer message and generate session ID for Langfuse
                customer_message: str = ticket.articles[0].text
                session_id: str = self.genai_handler.langfuse_client.generate_session_id()

                # Step 4: Predict category using LLM
                categorization: CategorizationResult = await self.predict_category(
                    message=customer_message,
                    session_id=session_id,
                )

                # Step 5: Determine action based on predicted category and conditions
                action_name: str = await self.get_action_name(
                    categorization_result=categorization,
                    message=customer_message,
                    session_id=session_id,
                )
                action: Action = self.actions_by_name.get(action_name, self.no_action)
                # Step 6: Return the triage result
                outcome = "success"
                return TriageResult(
                    user_text=customer_message,
                    category=categorization.category if categorization.category else self.no_category,
                    action=action,
                    reasoning=categorization.reasoning,
                    confidence=categorization.confidence,
                    extracted_values=categorization.extracted_values,
                )
            except TriageError:
                outcome = "fallback"
                logger.warning(f"Processing failed for ticket {id}, returning fallback TriageResult.")
                return TriageResult(
                    user_text=customer_message,
                    category=self.no_category,
                    action=self.no_action,
                    reasoning="Error during triage processing",
                    confidence=1.0,
                    extracted_values=None,
                )
        finally:
            TRIAGE_RUN_DURATION_SECONDS.labels(outcome=outcome).observe(perf_counter() - start_time)
            TRIAGE_RUNS_IN_PROGRESS.dec()

    async def predict_category(self, message: str, session_id: str) -> CategorizationResult:
        """Predict the appropriate triage category for a customer message.

        Parameters:
            message (str): Customer message to categorize; leading/trailing whitespace is ignored.
            session_id (str): Langfuse session identifier used for tracing the prediction.

        Returns:
            CategorizationResult: Object containing `category`, `reasoning`, `confidence`, and optional `extracted_values`. If the message is empty or the model returns an invalid category, the `category` will be the service's `no_category`, `reasoning` will explain the fallback, and `confidence` will be 1.0.

        Raises:
            TriageError: If categorization fails due to GenAI errors or other unexpected exceptions.
        """
        if len(message.strip()) == 0:
            logger.warning("Empty message provided for categorization")
            return CategorizationResult(
                category=self.no_category,
                reasoning="Empty message cannot be categorized",
                confidence=1.0,
                extracted_values=None,
            )

        try:
            cat_result: CategorizationResult = await self.genai_handler.categorize_ticket(
                message=message,
                role_description=self.prompts.get("role", ""),
                categories=self.categories,
                categories_prompt=self.prompts.get("categories", ""),
                examples=self.prompts.get("examples", ""),
                session_id=session_id,
            )

            if not cat_result.category or cat_result.category.name not in [c.name for c in self.categories]:
                logger.warning("Predicted category is invalid or not found, assigning no_category")
                cat_result.category = self.no_category
                cat_result.reasoning += " (Invalid category, 'no_category' assigned)"
                cat_result.confidence = 1.0

            # Log the results
            logger.debug(f"Text to categorize: {message[:100] + '...' if len(message) > 100 else message}")
            logger.debug(f"Category: {cat_result.category}")
            logger.debug(f"Reasoning: {cat_result.reasoning}")
            logger.debug(f"Confidence: {cat_result.confidence}")

            return cat_result

        except GenAIError as e:
            logger.error("GenAI categorization error", exc_info=True)
            raise TriageError("Categorization failed due to GenAI error") from e
        except Exception as e:
            logger.error("Unexpected error during categorization", exc_info=True)
            raise TriageError("Categorization failed due to unexpected error") from e

    async def get_action_name(
        self, categorization_result: CategorizationResult, message: str = "", session_id: str | None = None
    ) -> str:
        """Selects the appropriate action name for a categorization using configured action rules and optional message-derived conditions.

        Evaluates action rules associated with the categorization's category. If a rule defines ordered conditions, each condition is evaluated (possibly extracting values from the provided message via the GenAI handler) and its action_name is returned when the condition matches. If a rule matches but none of its conditions match, the rule's default action_name is returned. If the categorization has no category or no rule matches, the configured fallback action name is returned.

        Parameters:
            categorization_result (CategorizationResult): The categorization outcome whose category guides rule selection.
            message (str): Optional text used to extract condition values (e.g., days since request or processing id).
            session_id (str | None): Optional session identifier forwarded to GenAI extraction calls.

        Returns:
            str: The chosen action name, or the fallback action name when no rule or matching condition is found.
        """
        try:
            days_since_request = None
            processing_id = None

            # If no category or it's the no_category, always return no_action
            if not categorization_result.category or categorization_result.category.name == self.no_category.name:
                return self.no_action.name

            # Find matching action rule
            for rule in self.action_rules:
                if rule.category_name == categorization_result.category.name:
                    # If there are conditions, evaluate them
                    if rule.conditions:
                        conditions: list[Condition] = sorted(rule.conditions, key=lambda c: c.priority)
                        for condition in conditions:
                            if condition.field == "days_since_request":
                                if days_since_request is None:
                                    days_result: DaysSinceRequestResponse = await self.genai_handler.extract_days_since_request(
                                        message=message,
                                        today=date.today().isoformat(),  # TODO: Mpck date for benchmarks with old tickets
                                        session_id=session_id,
                                    )
                                    days_since_request = days_result.days_since_request
                                if (get_operator_function(operator=condition.operator))(
                                    days_since_request, condition.value
                                ):
                                    return condition.action_name

                            if condition.field == "processing_id":
                                if processing_id is None:
                                    processing_result: ProcessingIdResponse = (
                                        await self.genai_handler.extract_processing_id(
                                            message=message,
                                            session_id=session_id,
                                        )
                                    )
                                    processing_id = processing_result.processing_id
                                if get_operator_function(operator=condition.operator)(processing_id, condition.value):
                                    return condition.action_name
                    return rule.action_name

            # Default action if no rules matched
            return self.no_action.name
        except GenAIError as e:
            logger.error("GenAI extraction error during action determination", exc_info=True)
            raise TriageError("Action determination failed due to GenAI error") from e
        except Exception as e:
            logger.error("Unexpected error during action determination", exc_info=True)
            raise TriageError(f"Action determination failed due to unexpected error: {str(e)}") from e

    def _name_to_category(self, category_name: str) -> Category:
        """Return the Category for the given name or the configured fallback when no match exists.

        Parameters:
            category_name (str): Name of the category to look up.

        Returns:
            Category: The matching Category, or the configured fallback Category if no match exists.
        """
        return self.categories_by_name.get(category_name, self.no_category)

    def _name_to_action(self, action_name: str) -> Action:
        """Look up an action by its name.

        Args:
            action_name: The action name to look up

        Returns:
            The matching Action or no_action as fallback
        """
        return self.actions_by_name.get(action_name, self.no_action)

    async def cleanup(self) -> None:
        """Release resources held by the TriageService and clear the global singleton.

        This closes the underlying Zammad client and resets the module-level service reference so a new instance can be created on next request.
        """
        await self.zammad_client.close()
        global _service
        _service = None
        logger.info("Triage resources cleaned up.")


_service: TriageService | None = None


def get_triage_service(settings: ZammadAISettings | None = None) -> TriageService:
    """Return the shared TriageService singleton, creating and initializing it if necessary.

    Parameters:
        settings (ZammadAISettings | None): Optional settings to initialize the service. If None, the application settings from get_settings() are used.

    Returns:
        TriageService: The shared TriageService instance.
    """
    global _service
    if _service is None:
        if settings is None:
            from app.settings import get_settings

            settings = get_settings()
        _service = TriageService(settings=settings)
    return _service
