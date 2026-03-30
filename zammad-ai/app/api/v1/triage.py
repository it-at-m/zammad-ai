"""Version 1 triage endpoint for Zammad AI."""

from fastapi import APIRouter, Depends, Request

from app.models.api_v1 import TriageInput, TriageOutput
from app.models.triage import CategorizationResult, TriageResult
from app.settings.triage import Action, Category
from app.triage.triage import TriageService


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
) -> TriageOutput:
    """Handle a triage request by classifying the input text, selecting an action, and returning a structured triage result.

    Parameters:
        input (TriageInput): Request payload containing `text` to classify; if `session_id` is missing a UUID will be assigned and returned.

    Returns:
        TriageOutput: Contains `triage` (a TriageResult with `category`, `action`, `reasoning`, and `confidence`) and the request `session_id`.
    """
    import uuid

    if not input.session_id:
        input.session_id = str(uuid.uuid4())
    text: str = input.text

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
