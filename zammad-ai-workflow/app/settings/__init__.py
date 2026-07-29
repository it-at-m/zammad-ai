"""Settings models and configuration loading for Zammad AI."""

from .answer import AnswerSettings, JudgeSettings, JudgeThresholds, LawToolSettings, QdrantSettings
from .frontend import FrontendSettings
from .genai import GenAIAnthropicSettings, GenAIOpenAISettings, GenAIProviderSettings
from .guardrails import GuardrailSettings
from .kafka import KafkaSettings
from .preparser import PreparserSettings
from .settings import ZammadAISettings, get_settings
from .triage import TriageSettings
from .usecase import UseCaseSettings
from .zammad import BaseZammadSettings, ZammadAPISettings, ZammadEAISettings

__all__: list[str] = [
    "AnswerSettings",
    "BaseZammadSettings",
    "FrontendSettings",
    "GenAIProviderSettings",
    "GenAIOpenAISettings",
    "GenAIAnthropicSettings",
    "get_settings",
    "KafkaSettings",
    "JudgeSettings",
    "JudgeThresholds",
    "LawToolSettings",
    "QdrantSettings",
    "TriageSettings",
    "UseCaseSettings",
    "ZammadAISettings",
    "ZammadAPISettings",
    "ZammadEAISettings",
    "GuardrailSettings",
    "PreparserSettings",
]
