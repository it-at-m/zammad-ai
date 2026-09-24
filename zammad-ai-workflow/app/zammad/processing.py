"""Helpers for detecting whether a ticket has already been processed by AI or a human."""

import re
from dataclasses import dataclass

from app.errors import TicketAlreadyProcessedError
from app.models.zammad import ZammadArticle, ZammadTicket

from .markers import NO_ANSWER_NOTE_SUBJECT


@dataclass(frozen=True, slots=True)
class TicketProcessingState:
    """Computed processing markers for a ticket."""

    ticket_id: int
    article_count: int
    current_group_id: int | None
    current_group_name: str | None
    in_ai_group: bool
    has_ai_group_move_note: bool
    has_feedback_note: bool
    has_shared_draft: bool
    has_ai_internal_note: bool
    has_no_answer_internal_note: bool

    @property
    def already_processed(self) -> bool:
        """Return whether the ticket should be treated as already processed."""
        return (
            self.in_ai_group
            or self.has_ai_group_move_note
            or self.has_feedback_note
            or self.has_shared_draft
            or self.has_ai_internal_note
            or self.has_no_answer_internal_note
        )

    @property
    def reasons(self) -> tuple[str, ...]:
        """Return the markers that triggered duplicate-processing detection."""
        reasons: list[str] = []
        if self.in_ai_group:
            reasons.append("already_in_ai_group")
        if self.has_ai_group_move_note:
            reasons.append("ai_group_move_note_present")
        if self.has_feedback_note:
            reasons.append("feedback_note_present")
        if self.has_shared_draft:
            reasons.append("shared_draft_present")
        if self.has_ai_internal_note:
            reasons.append("ai_internal_note_present")
        if self.has_no_answer_internal_note:
            reasons.append("no_answer_internal_note_present")
        return tuple(reasons)


def _article_text(article: ZammadArticle) -> str:
    return f"{article.subject or ''}\n{article.text}".lower()


def _is_no_answer_internal_note(article: ZammadArticle) -> bool:
    return article.internal and article.subject == NO_ANSWER_NOTE_SUBJECT


def _contains_ai_group_name(text: str, ai_group_name: str | None) -> bool:
    if not ai_group_name:
        return False
    normalized_text = text.lower()
    normalized_group_name = re.escape(ai_group_name.strip().lower())
    return bool(re.search(rf"(?<!\w){normalized_group_name}(?!\w)", normalized_text))


def _is_ai_group_move_note(article: ZammadArticle, ai_group_name: str | None) -> bool:
    if not article.internal or not ai_group_name:
        return False
    return bool(
        re.search(
            rf"(?s)\bdokumentation von änderungen\b.*\baktuelle gruppe:\s*{re.escape(ai_group_name.strip().lower())}(?!\w)",
            _article_text(article),
        )
    )


def _is_ai_system_author(author: str | None, expected_author: str | None) -> bool:
    if not author:
        return False
    if not expected_author:
        return False
    return author.strip().lower() == expected_author.strip().lower()


def build_ticket_processing_state(
    ticket: ZammadTicket,
    *,
    ai_group_id: int | None,
    ai_group_name: str | None,
    ai_ticket_author: str | None,
) -> TicketProcessingState:
    """Derive duplicate-processing markers from a ticket payload."""
    articles = ticket.articles
    article_count = len(articles)

    current_group_name = ticket.group_name
    in_ai_group = False
    if ticket.group_id is not None and ai_group_id is not None:
        in_ai_group = ticket.group_id == ai_group_id
    elif current_group_name and ai_group_name:
        in_ai_group = current_group_name.strip().lower() == ai_group_name.strip().lower()

    has_ai_group_move_note = any(_is_ai_group_move_note(article, ai_group_name) for article in articles)
    has_feedback_note = any(
        article.internal
        and (
            "feedback zu shared draft" in _article_text(article)
            or "feedback zum ki-antwortvorschlag" in _article_text(article)
            or "feedback zur statischen antwort" in _article_text(article)
            or "feedback zur no-answer" in _article_text(article)
        )
        for article in articles
    )
    has_shared_draft = any("shared draft" in _article_text(article) for article in articles)
    has_no_answer_internal_note = any(_is_no_answer_internal_note(article) for article in articles)
    has_ai_internal_note = any(
        article.internal
        and ai_ticket_author
        and _is_ai_system_author(article.author, ai_ticket_author)
        and not _is_no_answer_internal_note(article)
        for article in articles
    )

    return TicketProcessingState(
        ticket_id=ticket.id,
        article_count=article_count,
        current_group_id=ticket.group_id,
        current_group_name=current_group_name,
        in_ai_group=in_ai_group,
        has_ai_group_move_note=has_ai_group_move_note,
        has_feedback_note=has_feedback_note,
        has_shared_draft=has_shared_draft,
        has_ai_internal_note=has_ai_internal_note,
        has_no_answer_internal_note=has_no_answer_internal_note,
    )


def ensure_ticket_not_already_processed(
    ticket: ZammadTicket,
    *,
    ai_group_id: int | None,
    ai_group_name: str | None,
    ai_ticket_author: str | None,
    duplicate_detection_enabled: bool = True,
    allow_no_answer_internal_note: bool = False,
) -> TicketProcessingState:
    """Raise when a ticket already contains AI or human processing markers."""
    state = build_ticket_processing_state(
        ticket,
        ai_group_id=ai_group_id,
        ai_group_name=ai_group_name,
        ai_ticket_author=ai_ticket_author,
    )
    if not duplicate_detection_enabled:
        return state
    if allow_no_answer_internal_note and state.has_no_answer_internal_note:
        if tuple(reason for reason in state.reasons if reason != "no_answer_internal_note_present") == ():
            return state
    if state.already_processed:
        raise TicketAlreadyProcessedError(
            "Ticket appears to have already been processed: " + ", ".join(state.reasons),
            retryable=False,
        )
    return state
