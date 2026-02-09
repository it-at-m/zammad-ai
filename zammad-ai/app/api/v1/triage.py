from fastapi import APIRouter, Depends, Request

from app.models.api_v1 import TriageInput, TriageOutput
from app.models.triage import CategorizationResult, TriageResult
from app.triage.triage import Triage


def get_triage(request: Request) -> Triage:
    """
    Retrieve the request-scoped Triage instance stored on the FastAPI application state.
    
    Parameters:
        request (Request): FastAPI request whose application state contains the Triage instance.
    
    Returns:
        Triage: The Triage instance found at request.app.state.triage.
    """
    return request.app.state.triage


triage_router = APIRouter()


@triage_router.post("/")
async def triage(
    input: TriageInput,
    triage: Triage = Depends(get_triage),
) -> TriageOutput:
    """
    Handle a triage request by classifying the input text, selecting an action, and returning a structured triage result.
    
    Parameters:
        input (TriageInput): Request payload containing `text` to classify; if `id` is missing a UUID will be assigned and returned.
    
    Returns:
        TriageOutput: Contains `triage` (a TriageResult with `category`, `action`, `reasoning`, and `confidence`) and the request `id`.
    """
    import uuid

    if not input.id:
        input.id = str(uuid.uuid4())
    text = input.text

    # Get categorization result
    categorization: CategorizationResult = await triage.predict_category(text, session_id=input.id)

    # Determine action based on category
    action_id = await triage.get_action_id(categorization, message=text, session_id=input.id)
    action = triage._id_to_action(action_id)
    final_category = categorization.category if categorization.category else triage.no_category
    return TriageOutput(
        triage=TriageResult(
            category=final_category,
            action=action,
            reasoning=categorization.reasoning,
            confidence=categorization.confidence,
        ),
        id=input.id,
    )