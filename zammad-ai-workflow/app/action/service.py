"""Action service for executing post-triage ticket handling."""

from logging import Logger

from app.answer.service import AnswerService, get_answer_service
from app.errors import ActionExecutionError, AppError
from app.guardrails import GuardrailService, reset_guardrail_service
from app.metrics import record_kafka_ticket_outcome
from app.models.answer import AnswerCandidate, NoAnswerPossible, StaticAnswer
from app.models.guardrails import GuardrailResponseResult, GuardrailResult
from app.models.triage import Action
from app.settings.settings import ZammadAISettings
from app.settings.triage import ActionTypes
from app.settings.zammad import ZammadAPISettings, ZammadEAISettings
from app.triage.triage import TriageResult
from app.utils.logging import getLogger
from app.utils.token import compute_feedback_token
from app.zammad.api import ZammadAPIClient
from app.zammad.eai import ZammadEAIClient


class ActionService:
    """Execute ticket actions based on triage category and action type."""

    logger: Logger = getLogger("zammad-ai.action.service")

    def __init__(
        self, settings: ZammadAISettings, answer_service: AnswerService, guardrail_service: GuardrailService
    ) -> None:
        """Initialize action execution with settings, answer service, guardrail service, and Zammad client."""
        self.settings: ZammadAISettings = settings
        self.answer_service: AnswerService = answer_service
        self.guardrail_service: GuardrailService = guardrail_service
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

            if triage.action.type == ActionTypes.NoAction:
                record_kafka_ticket_outcome(category=category, action_type=triage.action.type, outcome="manual")

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
                record_kafka_ticket_outcome(
                    category=triage.category.name,
                    action_type=triage.action.type,
                    outcome="answer",
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
                record_kafka_ticket_outcome(
                    category=triage.category.name,
                    action_type=triage.action.type,
                    outcome="shared_draft",
                )
                self.logger.info(f"Posted shared draft for ticket {ticket_id} with category {category}")
                if self.settings.frontend.feedback.post_internal_note and isinstance(response, AnswerCandidate):
                    await self._post_feedback_internal_note(
                        ticket_id=ticket_id, user_text=triage.user_text[: self.max_user_text_length], response=response
                    )
        except AppError:
            raise
        except Exception as e:
            self.logger.error("Action execution failed.", exc_info=True)
            raise ActionExecutionError("Action execution failed", retryable=True) from e

    async def _post_feedback_internal_note(self, ticket_id: int, user_text: str, response: AnswerCandidate) -> None:
        trace_id: str | None = (
            self.answer_service.langfuse_client.langfuse_handler.last_trace_id
            if self.answer_service.langfuse_client
            else None
        )
        if trace_id and self.settings.frontend.base_url:
            # Generate a per-link token using the trace IO and the configured salt
            try:
                input: str = user_text or ""
                output: str = (response.subject or "") + "\n\n" + (response.response or "")
                output: str = output.replace("<br>", "\n").strip()
                salt: str = (
                    self.settings.frontend.feedback.salt.get_secret_value()
                    if self.settings.frontend.feedback.salt
                    else ""
                )
                token = compute_feedback_token(inp=input, out=output, salt=salt)
            except Exception:
                token = ""

            text = f"<a href='{self.settings.frontend.base_url}/feedback/?trace_id={trace_id}&key={token}' target='_blank'>Feedback zu Shared Draft geben</a> (öffnet ein neues Fenster)"
            await self.zammad_client.post_answer(
                ticket_id=ticket_id,
                text=text,
                subject="Feedback zum KI-Antwortvorschlag",
                internal=True,  # Post an internal note to document that feedback can be given for the answer suggestion
            )

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
        guardrail_result: GuardrailResult | None = await self.guardrail_service.evaluate(
            user_text,
            toxicity_labels=[
                "violence_and_weapons",
                "sexual_content",
                "hate_and_discrimination",
                "self_harm_and_suicide",
                "misinformation",
                "copyright_violation",
                "child_safety",
                "political_manipulation",
                "unethical_conduct",
                "regulated_advice",
                "other",
                "benign",
            ],
            jailbreak_labels=None,
        )
        if self.settings.guardrails.enabled:
            self.logger.info(
                f"Guardrail check in get_answer for ticket {ticket_id if ticket_id is not None else 'unknown'}: safety={guardrail_result.prompt_safety if guardrail_result else 'unknown'}, toxicity={guardrail_result.prompt_toxicity if guardrail_result else 'unknown'}, jailbreak={guardrail_result.jailbreak_detection if guardrail_result else 'unknown'}"
            )

        if (
            (not guardrail_result or not guardrail_result.prompt_safety == "safe")
            and self.guardrail_service.settings.block_on_high_risk
            and self.guardrail_service.settings.enabled
        ):
            self.logger.warning(
                f"Answer generation blocked by guardrails for ticket {ticket_id if ticket_id is not None else 'unknown'}"
            )
            if not guardrail_result:
                raise ActionExecutionError(
                    "Guardrail evaluation failed or returned no result; action execution blocked",
                    retryable=True,
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
            response = NoAnswerPossible(
                reasoning=(
                    f"No answer was generated because the selected action '{action.name}' is configured as NoAction. "
                    f"The triage category was '{category_name}', so the ticket should not receive an automated answer."
                )
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
            response_guardrail_result: GuardrailResponseResult | None = await self.guardrail_service.evaluate_response(
                text=user_text, response=response.response
            )
            self.logger.debug(f"Guardrail evaluation for response: {response_guardrail_result}")
            if (
                (not response_guardrail_result or not response_guardrail_result.response_safety == "safe")
                and self.guardrail_service.settings.block_on_high_risk
                and self.guardrail_service.settings.enabled
            ):
                self.logger.warning(
                    f"Generated response blocked by guardrails for ticket {ticket_id if ticket_id is not None else 'unknown'}"
                )
                if not response_guardrail_result:
                    raise ActionExecutionError(
                        "Guardrail evaluation for generated response failed or returned no result; action execution blocked",
                        retryable=True,
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
        first_error: Exception | None = None
        try:
            try:
                await self.guardrail_service.close()
            except Exception as e:
                first_error = e
                self.logger.error("Failed to close guardrail service during action cleanup", exc_info=True)

            try:
                await self.zammad_client.close()
            except Exception as e:
                if first_error is None:
                    first_error = e
                self.logger.error("Failed to close Zammad client during action cleanup", exc_info=True)
        finally:
            reset_guardrail_service()
            global _service
            _service = None

        if first_error is not None:
            raise first_error


class _SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def _safe_format(template: str, **values: str) -> str:
    return template.format_map(_SafeFormatDict(values))


_service: ActionService | None = None


def get_action_service(
    guardrail_service: GuardrailService,
    settings: ZammadAISettings | None = None,
    answer_service: AnswerService | None = None,
) -> ActionService:
    """Get or create the shared ActionService instance.

    Args:
        guardrail_service: The guardrail service to initialize the ActionService instance.
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
            answer_service = get_answer_service(guardrail_service=guardrail_service, settings=settings)
        _service = ActionService(settings=settings, answer_service=answer_service, guardrail_service=guardrail_service)
    return _service
