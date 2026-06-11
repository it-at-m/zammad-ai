"""Version 1 triage endpoint for Zammad AI."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import AppError
from app.models.api_v1 import TriageInput, TriageOutput
from app.models.triage import CategorizationResult, TriageResult
from app.settings import ZammadAISettings, get_settings
from app.settings.triage import Action, Category
from app.triage.triage import TriageService
from app.utils.logging import getLogger

from .errors import app_error_to_http, unexpected_error_to_http
from .utils import check_api_key

logger = getLogger("zammad-ai.api.v1.triage")

settings: ZammadAISettings = get_settings()

header_scheme = HTTPBearer(auto_error=False)


def triage_dependency(request: Request) -> TriageService:
    """Retrieve the request-scoped TriageService instance from the FastAPI application state.

    Parameters:
        request (Request): Incoming FastAPI request whose app.state contains the service.

    Returns:
        TriageService: The TriageService instance stored at request.app.state.triage_service.
    """
    return request.app.state.triage_service


triage_router = APIRouter(
    tags=["triage"],
    prefix="/triage",
)


@triage_router.post(path="")
async def triage(
    input: TriageInput,
    service: TriageService = Depends(triage_dependency),
    request: Request | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(header_scheme),
) -> TriageOutput:
    """Handle a triage request by classifying the input text, selecting an action, and returning a structured triage result.

    Parameters:
        input (TriageInput): Request payload containing `text` to classify; if `session_id` is missing a UUID will be assigned and returned.

    Returns:
        TriageOutput: Contains `triage` (a TriageResult with `category`, `action`, `reasoning`, and `confidence`) and the request `session_id`.
    """
    if not check_api_key(credentials):
        logger.warning("Unauthorized triage request with invalid API key.")
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        if not input.session_id:
            input.session_id = str(uuid4())
        text: str = input.text

        # Preparse input text if a preparser is available on the app state
        try:
            preparser = request.app.state.preparser_service if request is not None else None
            if preparser is not None:
                text = preparser.preparse(text)
        except Exception:
            logger.error("Preparser failed in API triage endpoint; continuing with original text", exc_info=True)

        # Get categorization result
        categorization: CategorizationResult = await service.predict_category(text, session_id=input.session_id)

        # Determine action based on category
        action_name: str = await service.get_action_name(categorization, message=text, session_id=input.session_id)
        action: Action = service._name_to_action(action_name)
        final_category: Category = categorization.category if categorization.category else service.no_category

        return TriageOutput(
            triage=TriageResult(
                user_text=text,
                category=final_category,
                action=action,
                reasoning=categorization.reasoning,
                confidence=categorization.confidence,
                extracted_values=categorization.extracted_values,
            ),
            session_id=input.session_id,
        )
    except AppError as e:
        logger.warning(f"Triage request failed with application error type {type(e).__name__}.", exc_info=True)
        raise app_error_to_http(e) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Triage request failed with unexpected error.", exc_info=True)
        raise unexpected_error_to_http() from e
