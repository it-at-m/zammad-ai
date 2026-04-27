"""Version 1 answer endpoint for Zammad AI."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.action.service import ActionService
from app.errors import AppError
from app.models.api_v1 import AnswerInput, AnswerOutput
from app.utils.logging import getLogger

from .errors import app_error_to_http, unexpected_error_to_http

logger = getLogger("zammad-ai.api.v1.answer")


def action_dependency(request: Request) -> ActionService:
    """Retrieve the request-scoped ActionService instance stored on the FastAPI application state.

    Parameters:
        request (Request): FastAPI request whose application state contains the ActionService instance.

    Returns:
        ActionService: The ActionService instance found at request.app.state.action_service.
    """
    return request.app.state.action_service


answer_router = APIRouter(
    tags=["answer"],
    prefix="/answer",
)


@answer_router.post(path="")
async def answer(
    input: AnswerInput,
    service: ActionService = Depends(action_dependency),
) -> AnswerOutput:
    """Process an answer request and produce the agent's response based on the provided input.

    Parameters:
        input (AnswerInput): Request payload containing `ticket_id`, `category`, `action`, `text`, and `session_id` for generating an answer.

    Returns:
        AnswerOutput: The agent's response and any supporting documents.
    """
    try:
        answer, documents, auto_publish = await service.get_answer(
            ticket_id=input.ticket_id,
            category_name=input.category,
            action_name=input.action,
            user_text=input.text,
            session_id=input.session_id,
        )
        if answer is None:
            answer = "No answer generated based on the provided input and current configuration."

        return AnswerOutput(
            response=answer,
            documents=documents,
            auto_publish=auto_publish,
        )
    except AppError as e:
        logger.warning(f"Answer request failed with application error type {type(e).__name__}.", exc_info=True)
        raise app_error_to_http(e) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Answer request failed with unexpected error.", exc_info=True)
        raise unexpected_error_to_http() from e
