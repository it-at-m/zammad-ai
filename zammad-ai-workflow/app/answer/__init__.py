"""Answer module for Zammad AI, responsible for generating structured responses to user questions using an agent-based approach."""

from .agent import AgentContext, AnswerCandidate
from .judge import JudgeHandler
from .service import AnswerService, get_answer_service

__all__: list[str] = [
    "AgentContext",
    "AnswerService",
    "JudgeHandler",
    "get_answer_service",
    "AnswerCandidate",
]
