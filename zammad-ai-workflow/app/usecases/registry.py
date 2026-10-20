"""Construction and lifecycle management for usecase runtimes."""

from copy import deepcopy
from typing import Any

from app.action.service import ActionService
from app.answer.service import AnswerService
from app.guardrails.http_client import GuardrailService
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
        self.triage_service = TriageService(
            settings=settings, guardrail_service=guardrail_service, owns_guardrail_service=False
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
        """Close resources owned by this runtime."""
        await self.answer_service.cleanup()
        await self.triage_service.cleanup()


class UseCaseRegistry:
    """Registry containing one runtime per configured usecase."""

    def __init__(self, root_settings: ZammadAISettings, guardrail_service: GuardrailService) -> None:
        """Build all configured runtimes and their resolver."""
        self.root_settings = root_settings
        self.resolver = UseCaseResolver(root_settings.usecases)
        self.runtimes: dict[str, UseCaseRuntime] = {
            definition.name: UseCaseRuntime(
                name=definition.name,
                settings=self._build_settings(definition),
                guardrail_service=guardrail_service,
            )
            for definition in root_settings.usecases
        }

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
        payload["usecase"]["name"] = definition.name
        return ZammadAISettings.model_validate(payload)

    def get(self, name: str) -> UseCaseRuntime:
        """Return a runtime by its configured name."""
        try:
            return self.runtimes[name]
        except KeyError as e:
            raise KeyError(f"Unknown usecase: {name}") from e

    async def cleanup(self) -> None:
        """Close every configured runtime."""
        for runtime in self.runtimes.values():
            await runtime.cleanup()


def _deep_merge(target: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
