"""Polling service for polling-based ticket intake from vanilla Zammad instances."""

import asyncio
from logging import Logger
from time import monotonic

from app.action.service import ActionService
from app.errors import (
    AckDecision,
    ExceptionDecision,
    TicketAlreadyProcessedError,
    TicketNotFoundError,
    classify_exception,
)
from app.metrics import record_polling_cycle, record_polling_ticket_outcome
from app.models.triage import TriageResult
from app.models.zammad import ZammadTicket
from app.settings.polling import PollingSettings
from app.settings.settings import ZammadAISettings
from app.triage.triage import TriageService
from app.utils.logging import getLogger
from app.utils.status import track_activity
from app.zammad.api import ZammadAPIClient
from app.zammad.base import BaseZammadClient
from app.zammad.processing import ensure_ticket_not_already_processed

logger: Logger = getLogger("zammad-ai.polling.service")


class PollingConfigurationError(RuntimeError):
    """Raised when polling is configured with an unsupported Zammad client type."""


class PollingRetryableError(RuntimeError):
    """Raised when polling ticket processing fails with a retryable error."""


class PollingService:
    """Poll the Zammad search API and process matching tickets through triage and action."""

    def __init__(
        self, settings: ZammadAISettings, triage_service: TriageService, action_service: ActionService
    ) -> None:
        """Initialize the polling service with settings and processing services."""
        if settings.zammad.type == "eai":
            raise PollingConfigurationError("Polling is not supported with the Zammad EAI client.")
        self.settings: ZammadAISettings = settings
        self.triage_service: TriageService = triage_service
        self.action_service: ActionService = action_service
        self.polling_settings: PollingSettings = settings.polling
        self._processed: dict[int, float] = {}
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the background polling task unless it is already running."""
        if self._task is not None and not self._task.done():
            logger.warning("Polling service is already running; ignoring start request.")
            return
        self._task = asyncio.create_task(self._run(), name="zammad-ai-polling")
        logger.info(
            "Polling-based ticket intake started.",
            extra={
                "search_query": self.polling_settings.search_query,
                "interval_seconds": self.polling_settings.interval_seconds,
            },
        )

    async def stop(self) -> None:
        """Cancel the background polling task and wait for it to finish."""
        if self._task is None:
            return
        task = self._task
        self._task = None
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        logger.info("Polling service stopped.")

    async def cleanup(self) -> None:
        """Stop the polling task and clear the in-memory deduplication state."""
        await self.stop()
        self._processed.clear()
        logger.info("Polling resources cleaned up.")

    async def _run(self) -> None:
        """Run polling cycles forever until the task is cancelled."""
        while True:
            await asyncio.sleep(self.polling_settings.interval_seconds)
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("Polling cycle failed.", exc_info=True)
                record_polling_cycle(outcome="error")

    async def _run_cycle(self) -> None:
        """Run a single polling cycle: search, deduplicate, and process matching tickets."""
        async with track_activity():
            zammad_client = self.triage_service.zammad_client
            if not isinstance(zammad_client, ZammadAPIClient):
                raise PollingConfigurationError("Polling requires the Zammad API client.")
            collected_ids: list[int] = []
            for page in range(1, self.polling_settings.max_pages + 1):
                ids: list[int] = await zammad_client.search_tickets(
                    query=self.polling_settings.search_query,
                    page=page,
                    per_page=self.polling_settings.per_page,
                )
                collected_ids.extend(ids)
                if len(ids) < self.polling_settings.per_page:
                    break
            record_polling_cycle(outcome="success")

            ticket_ids: list[int] = []
            for ticket_id in collected_ids:
                if ticket_id not in ticket_ids:
                    ticket_ids.append(ticket_id)

            self._prune_processed()

            for ticket_id in ticket_ids:
                last_processed = self._processed.get(ticket_id)
                if (
                    last_processed is not None
                    and monotonic() - last_processed < self.polling_settings.processed_ttl_seconds
                ):
                    continue
                try:
                    outcome: str = await self._process_ticket(ticket_id=ticket_id)
                except PollingRetryableError:
                    logger.warning(
                        "Processing of ticket will be retried in a later polling cycle.",
                        extra={"handler_stage": "ticket_processing", "ticket_id": ticket_id},
                        exc_info=True,
                    )
                except Exception:
                    logger.error(
                        "Polling ticket processing failed unexpectedly.",
                        extra={"handler_stage": "ticket_processing", "ticket_id": ticket_id},
                        exc_info=True,
                    )
                else:
                    logger.info("Polling ticket completed.", extra={"ticket_id": ticket_id, "outcome": outcome})

    def _prune_processed(self) -> None:
        """Remove deduplication entries that are older than the configured TTL."""
        now: float = monotonic()
        expired = [
            ticket_id
            for ticket_id, processed_at in self._processed.items()
            if now - processed_at >= self.polling_settings.processed_ttl_seconds
        ]
        for ticket_id in expired:
            self._processed.pop(ticket_id, None)

    async def _process_ticket(self, ticket_id: int) -> str:
        """Fetch, triage, and execute the action for a single ticket and return its outcome."""
        zammad_client: BaseZammadClient = self.triage_service.zammad_client
        try:
            ticket: ZammadTicket = await zammad_client.get_ticket(id=ticket_id)
            ensure_ticket_not_already_processed(
                ticket,
                ai_group_id=self.settings.zammad.ai_ticket_group_id,
                ai_group_name=self.settings.zammad.ai_ticket_group_name,
                ai_ticket_author=self.settings.zammad.ai_ticket_author,
                duplicate_detection_enabled=self.settings.zammad.duplicate_detection_enabled,
                allow_in_ai_group=False,
            )
        except TicketNotFoundError:
            logger.info(
                "Ticket no longer exists in Zammad.",
                extra={"handler_stage": "ticket_lookup", "ticket_id": ticket_id},
            )
            return "not_found"
        except TicketAlreadyProcessedError:
            logger.info(
                "Skipping ticket that was already processed.",
                extra={"handler_stage": "duplicate_check", "ticket_id": ticket_id},
            )
            self._processed[ticket_id] = monotonic()
            return "skipped_already_processed"
        except Exception as e:
            decision: ExceptionDecision = classify_exception(
                e,
                category_wrong_retry_confidence_threshold=self.settings.triage.category_wrong_retry_confidence_threshold,
            )
            if decision.decision == AckDecision.ACK_DROP:
                logger.error(
                    "Polling ticket lookup failed permanently.",
                    extra={"handler_stage": "ticket_lookup", "ticket_id": ticket_id},
                    exc_info=True,
                )
                self._processed[ticket_id] = monotonic()
                record_polling_ticket_outcome(category=None, action_type=None, outcome="aborted_with_error")
                return "error_permanent"
            logger.error(
                "Error connecting to Zammad during polling.",
                extra={"handler_stage": "ticket_lookup", "ticket_id": ticket_id},
                exc_info=True,
            )
            raise PollingRetryableError("Failed to fetch ticket from Zammad during polling") from e

        result: TriageResult | None = None
        try:
            result = await self.triage_service.perform_triage(ticket=ticket)
            await self.action_service.execute_action(ticket_id=ticket_id, triage=result)
        except Exception as e:
            decision: ExceptionDecision = classify_exception(
                e,
                category_wrong_retry_confidence_threshold=self.settings.triage.category_wrong_retry_confidence_threshold,
            )
            if decision.decision == AckDecision.ACK_DROP:
                logger.error(
                    "Polling ticket processing failed permanently.",
                    extra={"handler_stage": "ticket_processing", "ticket_id": ticket_id},
                    exc_info=True,
                )
                self._processed[ticket_id] = monotonic()
                record_polling_ticket_outcome(
                    category=result.category.name if result is not None else None,
                    action_type=result.action.type if result is not None else None,
                    outcome="aborted_with_error",
                )
                return "error_permanent"
            logger.error(
                "Polling ticket processing failed with a retryable error.",
                extra={"handler_stage": "ticket_processing", "ticket_id": ticket_id},
                exc_info=True,
            )
            raise PollingRetryableError("Polling ticket processing failed with a retryable error") from e

        record_polling_ticket_outcome(
            category=result.category.name,
            action_type=result.action.type,
            outcome="processed",
        )
        self._processed[ticket_id] = monotonic()
        logger.info(
            "Polling ticket processed successfully.",
            extra={"ticket_id": ticket_id, "category": result.category.name, "action_type": result.action.type.value},
        )
        return "processed"


_service: PollingService | None = None


def get_polling_service(
    settings: ZammadAISettings, triage_service: TriageService, action_service: ActionService
) -> PollingService:
    """Get or create the shared PollingService instance.

    Args:
        settings: Application settings containing the polling configuration.
        triage_service: The TriageService used to triage polled tickets.
        action_service: The ActionService used for post-triage ticket handling.

    Returns:
        PollingService: The shared PollingService instance.
    """
    global _service
    if _service is None:
        _service = PollingService(settings=settings, triage_service=triage_service, action_service=action_service)
    return _service


def reset_polling_service() -> None:
    """Reset the module-level polling service reference so a new instance can be created."""
    global _service
    _service = None
