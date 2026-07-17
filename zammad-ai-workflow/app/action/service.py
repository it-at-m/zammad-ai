"""Action service for executing post-triage ticket handling."""

from logging import Logger

from app.answer.service import AnswerService, get_answer_service
from app.errors import ActionExecutionError, AppError
from app.guardrails import GuardrailService, get_guardrail_service
from app.models.answer import AnswerCandidate, NoAnswerPossible, StaticAnswer
from app.models.guardrails import GuardrailResponseResult, GuardrailResult
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
        """Initialize action execution with settings, answer service, guardrail service, and Zammad client."""
        self.settings: ZammadAISettings = settings
        self.answer_service: AnswerService = answer_service
        self.guardrail_service: GuardrailService = get_guardrail_service(settings=settings.guardrails)
        self.max_user_text_length: int = settings.max_user_text_length
        # Zammad client setup
        if isinstance(self.settings.zammad, ZammadAPISettings):
            self.zammad_client = ZammadAPIClient(settings=self.settings.zammad)
        elif isinstance(self.settings.zammad, ZammadEAISettings):
            self.zammad_client = ZammadEAIClient(settings=self.settings.zammad)
        else:
            raise ActionExecutionError("Invalid type for Zammad settings in configuration", retryable=False)

    async def execute_action(self, ticket_id: int, triage: TriageResult, session_id: str | None = None) -> None:
        """Run the configured action for a ticket and publish or draft the answer."""
        try:
            category: str = triage.category.name
            action: str = triage.action.name
            reason: str = triage.reasoning

            response = await self.get_answer(  # TODO what to do with documents here? Internal Note?
                ticket_id=ticket_id,
                category_name=category,
                action_name=action,
                user_text=triage.user_text,
                session_id=session_id,
            )

            if isinstance(response, NoAnswerPossible):
                self.logger.info(f"No answer generated for ticket {ticket_id} with category {category}")
                if not self.settings.triage.no_action_internal_note:
                    return
                text: str = _safe_format(
                    template=self.settings.triage.no_action_internal_note,
                    category=category,
                    action=action,
                    reason=f"{reason}\n\nNo answer possible. Explanation:\n{response.reasoning}",
                )

                await self.zammad_client.post_answer(
                    ticket_id=ticket_id,
                    text=text,
                    subject="No answer generation possible",
                    internal=True,  # Post an internal note if no answer is generated to document the triage result and action execution
                )
                self.logger.info(f"Posted internal note for ticket {ticket_id} with category {category}")
            elif triage.category.auto_publish and (
                isinstance(response, StaticAnswer) or (isinstance(response, AnswerCandidate) and response.auto_publish)
            ):
                await self.zammad_client.post_answer(
                    ticket_id=ticket_id,
                    text=response.response,
                    subject=response.subject if isinstance(response, AnswerCandidate) else "Answer",
                    internal=False,
                )
                self.logger.info(f"Posted answer for ticket {ticket_id} with category {category}")
                # Optionally schedule the ticket to be moved to a pending-close state after configured days
                try:
                    pending_days: int | None = self.settings.zammad.pending_close_after_days
                    if pending_days is not None:
                        await self.zammad_client.set_ticket_pending_close(ticket_id=ticket_id, days=pending_days)
                        self.logger.info(
                            f"Scheduled ticket {ticket_id} to be set to pending close after {pending_days} days"
                        )
                except Exception:
                    # Don't fail the action execution if scheduling fails — just log
                    self.logger.error("Failed to schedule pending-close update for ticket.", exc_info=True)
            else:
                await self.zammad_client.post_shared_draft(
                    ticket_id=ticket_id,
                    text=response.response,
                )
                self.logger.info(f"Posted shared draft for ticket {ticket_id} with category {category}")
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
    ) -> AnswerCandidate | StaticAnswer | NoAnswerPossible:
        """Resolve an answer payload for the given action and category.

        Performs guardrail checks on user text before answer generation.

        Raises:
            ActionExecutionError: If guardrails fail with block_on_high_risk enabled, or if no action is found.
        """
        # Evaluate guardrails before answer generation
        guardrail_result: GuardrailResult = await self.guardrail_service.evaluate(user_text)
        if self.settings.guardrails.enabled:
            self.logger.info(
                f"Guardrail check in get_answer for ticket {ticket_id if ticket_id is not None else 'unknown'}: safety={guardrail_result.prompt_safety}, toxicity={guardrail_result.prompt_toxicity}, jailbreak={guardrail_result.jailbreak_detection}"
            )

        if not guardrail_result.prompt_safety == "safe" and self.guardrail_service.settings.block_on_high_risk:
            self.logger.warning(
                f"Answer generation blocked by guardrails for ticket {ticket_id if ticket_id is not None else 'unknown'}"
            )
            raise ActionExecutionError(
                f"Input failed safety checks: {guardrail_result.prompt_toxicity}, {guardrail_result.jailbreak_detection}",
                retryable=False,
            )

        if len(user_text) > self.settings.max_user_text_length:
            self.logger.warning(
                f"User text for ticket {ticket_id if ticket_id is not None else 'unknown'} exceeds max_user_text_length={self.settings.max_user_text_length} and will be truncated for answer generation"
            )
            user_text = user_text[: self.max_user_text_length]

        action: Action | None = next(
            (action for action in self.settings.triage.actions if action.name == action_name), None
        )

        response: AnswerCandidate | StaticAnswer | NoAnswerPossible
        if action is None:
            raise ActionExecutionError(f"No action found with name: {action_name}", retryable=False)
        elif action.type == ActionTypes.NoAction:
            self.logger.info(
                f"Action {action.name} is of type No_Action. No answer will be generated for ticket {ticket_id if ticket_id is not None else 'unknown'}."
            )
        elif action.type == ActionTypes.AIAnswer:
            response = await self.answer_service.generate_answer(
                user_text=user_text, category=category_name, session_id=session_id
            )
        elif action.type == ActionTypes.StaticAnswer:
            # The settings validator ensures that if the type is StaticAnswer, the answer field is not None, so we can safely access it here
            if not action.answer:
                raise ActionExecutionError(
                    f"StaticAnswer action {action.name} is missing the 'answer' field", retryable=False
                )
            response = StaticAnswer(response=action.answer)
        else:
            raise ActionExecutionError(f"Unknown action type: {action.type}", retryable=False)

        # Evaluate guardrails on the generated response as well
        if isinstance(response, AnswerCandidate):
            response_guardrail_result: GuardrailResponseResult = await self.guardrail_service.evaluate_response(
                text=user_text, response=response.response
            )
            self.logger.debug(f"Guardrail evaluation for response: {response_guardrail_result}")
            if (
                not response_guardrail_result.response_safety == "safe"
                and self.guardrail_service.settings.block_on_high_risk
            ):
                self.logger.warning(
                    f"Generated response blocked by guardrails for ticket {ticket_id if ticket_id is not None else 'unknown'}"
                )
                raise ActionExecutionError(
                    f"Generated response failed safety checks: {response_guardrail_result.response_toxicity}, {response_guardrail_result.response_refusal}",
                    retryable=False,
                )

        return response

    async def cleanup(self) -> None:
        """Close internal clients and reset the module-level service reference.

        Attempts to close the Qdrant KB client and, if present, the DLF client. Always resets the module-level `_service` reference to `None` so the service can be recreated.
        """
        try:
            await self.zammad_client.close()
        finally:
            global _service
            _service = None


class _SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def _safe_format(template: str, **values: str) -> str:
    return template.format_map(_SafeFormatDict(values))


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
