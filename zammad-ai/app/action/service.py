"""Action service for executing post-triage ticket handling."""

from logging import Logger

from app.answer.service import AnswerService, get_answer_service
from app.errors import ActionExecutionError, AppError
from app.models.answer import DocumentDict, StructuredAgentResponse
from app.models.triage import Action
from app.settings.settings import ZammadAISettings
from app.settings.triage import ActionTypes
from app.settings.zammad import ZammadAPISettings, ZammadEAISettings
from app.triage.triage import TriageResult
from app.utils.logging import getLogger
from app.zammad.api import ZammadAPIClient
from app.zammad.eai import ZammadEAIClient


class ActionService:
    """Execute ticket actions based on triage category and action type."""

    logger: Logger = getLogger("zammad-ai.action.service")

    def __init__(self, settings: ZammadAISettings, answer_service: AnswerService):
        """Initialize action execution with settings, answer service, and Zammad client."""
        self.settings: ZammadAISettings = settings
        self.answer_service: AnswerService = answer_service
        # Zammad client setup
        if isinstance(self.settings.zammad, ZammadAPISettings):
            self.zammad_client = ZammadAPIClient(settings=self.settings.zammad)
        elif isinstance(self.settings.zammad, ZammadEAISettings):
            self.zammad_client = ZammadEAIClient(settings=self.settings.zammad)
        else:
            raise ActionExecutionError("Invalid type for Zammad settings in configuration", retryable=False)

    async def execute_action(self, ticket_id: int, triage: TriageResult, session_id: str | None = None) -> None:
        """Run the configured action for a ticket and publish or draft the answer."""
        category_name: str = triage.category.name
        action: Action = triage.action
        try:
            (
                answer,
                documents,
                judge_auto_publish,
            ) = await self.get_answer(  # TODO what to do with documents here? Internal Note?
                ticket_id=ticket_id,
                category_name=category_name,
                action_name=action.name,
                user_text=triage.user_text,
                session_id=session_id,
            )

            if answer is None:
                self.logger.info(
                    f"No answer generated for ticket {ticket_id} with category {category_name}; skipping action execution."
                )
                return

            if triage.category.auto_publish and judge_auto_publish:
                await self.zammad_client.post_answer(
                    ticket_id=ticket_id,
                    text=answer,
                    subject=None,  # TODO
                    internal=False,
                )
                self.logger.info(f"Posted answer for ticket {ticket_id} with category {category_name}")
            else:
                await self.zammad_client.post_shared_draft(
                    ticket_id=ticket_id,
                    text=answer,
                )
                self.logger.info(f"Posted shared draft for ticket {ticket_id} with category {category_name}")
        except AppError:
            raise
        except Exception as e:
            self.logger.error("Action execution failed.", exc_info=True)
            raise ActionExecutionError("Action execution failed", retryable=True) from e

    async def get_answer(
        self,
        ticket_id: int | None,
        category_name: str,
        action_name: str,
        user_text: str,
        session_id: str | None,
    ) -> tuple[str | None, list[DocumentDict], bool]:
        """Resolve an answer payload for the given action and category."""
        action: Action | None = next(
            (action for action in self.settings.triage.actions if action.name == action_name), None
        )
        answer: str | None = None
        documents: list[DocumentDict] = []
        judge_auto_publish: bool = True
        if action is None:
            raise ActionExecutionError(f"No action found with name: {action_name}", retryable=False)
        elif action.type == ActionTypes.NoAction:
            self.logger.info(
                f"Action {action.name} is of type No_Action. No answer will be generated for ticket {ticket_id if ticket_id is not None else 'unknown'}."
            )
        elif action.type == ActionTypes.AIAnswer:
            response: StructuredAgentResponse = await self.answer_service.generate_answer(
                user_text=user_text, category=category_name, session_id=session_id
            )
            answer = response.response
            documents = response.documents
            judge_auto_publish = response.auto_publish
        elif action.type == ActionTypes.StaticAnswer:
            # The settings validator ensures that if the type is StaticAnswer, the answer field is not None, so we can safely access it here
            answer = action.answer
        else:
            raise ActionExecutionError(f"Unknown action type: {action.type}", retryable=False)
        return answer, documents, judge_auto_publish

    async def cleanup(self) -> None:
        """Close internal clients and reset the module-level service reference.

        Attempts to close the Qdrant KB client and, if present, the DLF client. Always resets the module-level `_service` reference to `None` so the service can be recreated.
        """
        try:
            await self.zammad_client.close()
        finally:
            global _service
            _service = None


_service: ActionService | None = None


def get_action_service(
    settings: ZammadAISettings | None = None, answer_service: AnswerService | None = None
) -> ActionService:
    """Get or create the shared ActionService instance.

    Args:
        settings: Optional settings to initialize the ActionService instance.
                 If not provided, uses get_settings().
        answer_service: Optional AnswerService instance to use.
                        If not provided, a new one will be created.

    Returns:
        ActionService: The shared ActionService instance.
    """
    global _service
    if _service is None:
        if settings is None:
            from app.settings import get_settings

            settings = get_settings()
        if answer_service is None:
            answer_service = get_answer_service(settings)
        _service = ActionService(settings=settings, answer_service=answer_service)
    return _service
