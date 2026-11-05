"""Construction and lifecycle management for usecase runtimes."""

from copy import deepcopy
from typing import Any

from app.action.service import ActionService
from app.answer.service import AnswerService
from app.guardrails.http_client import GuardrailService
from app.preparser.service import PreparserService
from app.settings import ZammadAISettings
from app.settings.usecase import UseCaseSettings
from app.triage.triage import TriageService
from app.usecases.resolver import UseCaseResolver
from app.utils.logging import getLogger

logger = getLogger("zammad-ai.usecases.registry")


class UseCaseRuntime:
    """All usecase-specific services and their effective settings."""

    def __init__(self, name: str, settings: ZammadAISettings, guardrail_service: GuardrailService) -> None:
        """Build one isolated service group for a usecase."""
        self.name = name
        self.settings = settings
        self.guardrail_service = guardrail_service
        self.preparser_service = PreparserService(settings=settings.preparser)
        self.triage_service = TriageService(
            settings=settings,
            guardrail_service=guardrail_service,
            preparser_service=self.preparser_service,
            owns_guardrail_service=False,
        )
        self.answer_service = AnswerService(settings=settings, guardrail_service=guardrail_service)
        self.action_service = ActionService(
            settings=settings,
            answer_service=self.answer_service,
            guardrail_service=guardrail_service,
            zammad_client=self.triage_service.zammad_client,
            owns_guardrail_service=False,
        )

    async def cleanup(self) -> None:
        """Close resources owned by this runtime.

        The runtime is the sole owner of its guardrail service; the dependent services
        hold non-owning references, so the guardrail client is closed exactly once here.
        """
        first_error: Exception | None = None
        try:
            await self.answer_service.cleanup()
        except Exception as e:
            first_error = e
            logger.error("Failed to clean up answer service during usecase runtime cleanup", exc_info=True)
        try:
            await self.triage_service.cleanup()
        except Exception as e:
            if first_error is None:
                first_error = e
            logger.error("Failed to clean up triage service during usecase runtime cleanup", exc_info=True)
        try:
            await self.guardrail_service.close()
        except Exception as e:
            if first_error is None:
                first_error = e
            logger.error("Failed to close guardrail service during usecase runtime cleanup", exc_info=True)
        if first_error is not None:
            raise first_error


class UseCaseRegistry:
    """Registry containing one runtime per configured usecase."""

    def __init__(self, root_settings: ZammadAISettings) -> None:
        """Build all configured runtimes and their resolver."""
        self.root_settings = root_settings
        self.resolver = UseCaseResolver(root_settings.usecases)
        self.runtimes: dict[str, UseCaseRuntime] = {}
        for definition in root_settings.usecases:
            settings = self._build_settings(definition)
            self.runtimes[definition.name] = UseCaseRuntime(
                name=definition.name,
                settings=settings,
                guardrail_service=GuardrailService(settings.guardrails),
            )
        self._warn_inert_polling_usecases()
        self._warn_ruleless_usecases()

    def _warn_inert_polling_usecases(self) -> None:
        """Warn about polling-enabled usecases that can never match a polled ticket.

        With more than one usecase, a usecase without polling_match rules never
        matches a polled ticket, so its polling service would skip every ticket
        forever.
        """
        if len(self.root_settings.usecases) <= 1:
            return
        for definition in self.root_settings.usecases:
            runtime = self.runtimes.get(definition.name)
            if runtime is None:
                continue
            if runtime.settings.polling.enabled and not definition.polling_match:
                logger.warning(
                    f"Usecase '{definition.name}' has polling enabled but defines no polling_match rules; "
                    "it will never match polled tickets. Add polling_match rules or disable polling for this usecase."
                )

    def _warn_ruleless_usecases(self) -> None:
        """Warn about usecases that define neither match nor polling_match rules.

        With more than one usecase, such a usecase never matches a Kafka event
        or a polled ticket. The sole-usecase case is exempt because polled
        tickets match it unconditionally and unmatched events may be routed to
        it via the fallback policy. The configured fallback usecase is exempt
        for the same reason.
        """
        if len(self.root_settings.usecases) <= 1:
            return
        for definition in self.root_settings.usecases:
            if definition.match or definition.polling_match:
                continue
            if (
                self.root_settings.router.unmatched_policy == "fallback"
                and self.root_settings.router.fallback_usecase == definition.name
            ):
                continue
            logger.warning(
                f"Usecase '{definition.name}' defines neither match nor polling_match rules; "
                "it will never match Kafka events or polled tickets. "
                "Add at least one match or polling_match rule to its definition."
            )

    def _build_settings(self, definition: UseCaseSettings) -> ZammadAISettings:
        payload: dict[str, Any] = self.root_settings.model_dump(mode="python")
        payload.pop("usecases", None)
        payload.pop("router", None)
        payload["usecase"] = {
            "name": definition.name,
            "description": definition.description,
            "match": [match.model_dump() for match in definition.match],
            "polling_match": [match.model_dump() for match in definition.polling_match],
        }
        _deep_merge(payload, deepcopy(definition.config))
        if payload.get("triage") is None:
            raise ValueError(
                f"Usecase '{definition.name}' must define triage settings under its config "
                "because the root configuration does not define any"
            )
        payload["usecase"]["name"] = definition.name
        return ZammadAISettings.model_validate(payload)

    def get(self, name: str) -> UseCaseRuntime:
        """Return a runtime by its configured name."""
        try:
            return self.runtimes[name]
        except KeyError as e:
            raise KeyError(f"Unknown usecase: {name}") from e

    async def cleanup(self) -> None:
        """Close every configured runtime, continuing past individual failures."""
        first_error: Exception | None = None
        for runtime in self.runtimes.values():
            try:
                await runtime.cleanup()
            except Exception as e:
                if first_error is None:
                    first_error = e
                logger.error(f"Failed to clean up usecase runtime '{runtime.name}'.", exc_info=True)
        if first_error is not None:
            raise first_error


def _deep_merge(target: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
