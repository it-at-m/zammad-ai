"""Settings models and configuration loading for Zammad AI."""

from .answer import AnswerSettings, JudgeSettings, JudgeThresholds, QdrantSettings
from .frontend import FrontendSettings
from .genai import GenAISettings
from .kafka import KafkaSettings
from .settings import ZammadAISettings, get_settings
from .triage import TriageSettings
from .usecase import UseCaseSettings
from .zammad import BaseZammadSettings, ZammadAPISettings, ZammadEAISettings

__all__: list[str] = [
    "AnswerSettings",
    "BaseZammadSettings",
    "FrontendSettings",
    "GenAISettings",
    "get_settings",
    "KafkaSettings",
    "JudgeSettings",
    "JudgeThresholds",
    "QdrantSettings",
    "TriageSettings",
    "UseCaseSettings",
    "ZammadAISettings",
    "ZammadAPISettings",
    "ZammadEAISettings",
]
