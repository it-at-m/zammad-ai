"""Tests for Zammad duplicate-processing detection."""

from __future__ import annotations

from app.models.zammad import ZammadArticle, ZammadTicket
from app.zammad.processing import build_ticket_processing_state, ensure_ticket_not_already_processed


def test_build_ticket_processing_state_accepts_initial_ticket_without_markers() -> None:
    """A ticket with only the initial articles should not be treated as processed."""
    ticket = ZammadTicket(
        id=1,
        group_id=31,
        articles=[
            ZammadArticle(id=1, ticket_id=1, text="Inhalt des Anliegens", internal=False, author="Customer"),
            ZammadArticle(id=2, ticket_id=1, text="Eingang Ihres Anliegens", internal=False, author="System"),
            ZammadArticle(
                id=3, ticket_id=1, text="Dokumentation von ersten Einstellungen", internal=True, author="System"
            ),
            ZammadArticle(
                id=4, ticket_id=1, text="Interner Artikel für interne Anhänge.", internal=True, author="Agent"
            ),
        ],
    )

    state = build_ticket_processing_state(
        ticket,
        ai_group_id=99,
        ai_group_name="AI-Group",
        ai_ticket_author="AI-Author",
    )

    assert state.already_processed is False


def test_build_ticket_processing_state_accepts_five_articles_without_markers() -> None:
    """A ticket with five ordinary articles should still reach triage."""
    ticket = ZammadTicket(
        id=7,
        group_id=31,
        articles=[
            ZammadArticle(id=1, ticket_id=7, text="Inhalt des Anliegens", internal=False, author="Customer"),
            ZammadArticle(id=2, ticket_id=7, text="Eingang Ihres Anliegens", internal=False, author="System"),
            ZammadArticle(
                id=3, ticket_id=7, text="Dokumentation von ersten Einstellungen", internal=True, author="System"
            ),
            ZammadArticle(
                id=4, ticket_id=7, text="Interner Artikel für interne Anhänge.", internal=True, author="Agent"
            ),
            ZammadArticle(id=5, ticket_id=7, text="Weitere Info ohne AI-Marker", internal=False, author="Customer"),
        ],
    )

    state = build_ticket_processing_state(
        ticket,
        ai_group_id=99,
        ai_group_name="AI-Group",
        ai_ticket_author="AI-Author",
    )

    assert state.already_processed is False


def test_build_ticket_processing_state_ignores_email_addresses_containing_ai() -> None:
    """The heuristic should not misclassify tickets because an email address contains 'ai'."""
    ticket = ZammadTicket(
        id=2,
        group_id=31,
        articles=[
            ZammadArticle(id=1, ticket_id=2, text="Inhalt des Anliegens", internal=False, author="Customer"),
            ZammadArticle(id=2, ticket_id=2, text="Eingang Ihres Anliegens", internal=False, author="System"),
            ZammadArticle(
                id=3,
                ticket_id=2,
                text="Rückfrage an support@example.ai",
                internal=True,
                author="System",
            ),
            ZammadArticle(
                id=4,
                ticket_id=2,
                text="Interner Artikel für interne Anhänge.",
                internal=True,
                author="Agent",
            ),
        ],
    )

    state = build_ticket_processing_state(
        ticket,
        ai_group_id=99,
        ai_group_name="AI-Group",
        ai_ticket_author="AI-Author",
    )

    assert state.already_processed is False


def test_build_ticket_processing_state_requires_complete_group_name_match() -> None:
    """Group-name fallback should not match substrings."""
    ticket = ZammadTicket(
        id=8,
        group_name="Customer AI-Group Archive",
        articles=[
            ZammadArticle(id=1, ticket_id=8, text="Inhalt des Anliegens", internal=False, author="Customer"),
            ZammadArticle(id=2, ticket_id=8, text="Eingang Ihres Anliegens", internal=False, author="System"),
        ],
    )

    state = build_ticket_processing_state(
        ticket,
        ai_group_id=None,
        ai_group_name="AI-Group",
        ai_ticket_author="AI-Author",
    )

    assert state.in_ai_group is False


def test_build_ticket_processing_state_detects_configured_ai_author() -> None:
    """The configured AI author should still be recognized exactly."""
    ticket = ZammadTicket(
        id=3,
        group_id=31,
        articles=[
            ZammadArticle(id=1, ticket_id=3, text="Inhalt des Anliegens", internal=False, author="Customer"),
            ZammadArticle(id=2, ticket_id=3, text="Eingang Ihres Anliegens", internal=False, author="System"),
            ZammadArticle(
                id=3,
                ticket_id=3,
                text="Interner Hinweis",
                internal=True,
                author="AI-Author",
            ),
            ZammadArticle(
                id=4, ticket_id=3, text="Interner Artikel für interne Anhänge.", internal=True, author="Agent"
            ),
        ],
    )

    state = build_ticket_processing_state(
        ticket,
        ai_group_id=99,
        ai_group_name="AI-Group",
        ai_ticket_author="AI-Author",
    )

    assert state.already_processed is True
    assert "ai_internal_note_present" in state.reasons


def test_build_ticket_processing_state_detects_no_answer_note() -> None:
    """A no-answer note should be recognized as a dedicated marker."""
    ticket = ZammadTicket(
        id=4,
        group_id=31,
        articles=[
            ZammadArticle(id=1, ticket_id=4, text="Inhalt des Anliegens", internal=False, author="Customer"),
            ZammadArticle(id=2, ticket_id=4, text="Eingang Ihres Anliegens", internal=False, author="System"),
            ZammadArticle(
                id=3,
                ticket_id=4,
                text="No answer possible. Explanation: insufficient data.",
                internal=True,
                author="AI-System",
                subject="No answer generation possible",
            ),
            ZammadArticle(
                id=4, ticket_id=4, text="Interner Artikel für interne Anhänge.", internal=True, author="Agent"
            ),
        ],
    )

    state = build_ticket_processing_state(
        ticket,
        ai_group_id=99,
        ai_group_name="AI-Group",
        ai_ticket_author="AI-System",
    )

    assert state.already_processed is True
    assert "no_answer_internal_note_present" in state.reasons


def test_build_ticket_processing_state_detects_no_answer_note_without_author() -> None:
    """The no-answer marker should still work when no AI author is configured."""
    ticket = ZammadTicket(
        id=9,
        group_id=31,
        articles=[
            ZammadArticle(id=1, ticket_id=9, text="Inhalt des Anliegens", internal=False, author="Customer"),
            ZammadArticle(id=2, ticket_id=9, text="Eingang Ihres Anliegens", internal=False, author="System"),
            ZammadArticle(
                id=3,
                ticket_id=9,
                text="No answer possible. Explanation: insufficient data.",
                internal=True,
                subject="No answer generation possible",
            ),
        ],
    )

    state = build_ticket_processing_state(
        ticket,
        ai_group_id=99,
        ai_group_name="AI-Group",
        ai_ticket_author=None,
    )

    assert state.has_no_answer_internal_note is True
    assert state.already_processed is True


def test_build_ticket_processing_state_uses_shared_draft_article_marker() -> None:
    """The shared-draft guard should still work from article text."""
    ticket = ZammadTicket(
        id=10,
        group_id=31,
        articles=[
            ZammadArticle(id=1, ticket_id=10, text="Inhalt des Anliegens", internal=False, author="Customer"),
            ZammadArticle(id=2, ticket_id=10, text="Eingang Ihres Anliegens", internal=False, author="System"),
            ZammadArticle(id=3, ticket_id=10, text="shared draft has been created", internal=True, author="System"),
        ],
    )

    state = build_ticket_processing_state(
        ticket,
        ai_group_id=99,
        ai_group_name="AI-Group",
        ai_ticket_author="AI-Author",
    )

    assert state.has_shared_draft is True
    assert state.already_processed is True


def test_ensure_ticket_not_already_processed_allows_only_no_answer_note() -> None:
    """The feedback path may proceed when the only marker is a just-posted no-answer note."""
    ticket = ZammadTicket(
        id=5,
        group_id=31,
        articles=[
            ZammadArticle(id=1, ticket_id=5, text="Inhalt des Anliegens", internal=False, author="Customer"),
            ZammadArticle(id=2, ticket_id=5, text="Eingang Ihres Anliegens", internal=False, author="System"),
            ZammadArticle(
                id=3,
                ticket_id=5,
                text="No answer possible. Explanation: insufficient data.",
                internal=True,
                author="AI-Author",
                subject="No answer generation possible",
            ),
            ZammadArticle(
                id=4, ticket_id=5, text="Interner Artikel für interne Anhänge.", internal=True, author="Agent"
            ),
        ],
    )

    state = ensure_ticket_not_already_processed(
        ticket,
        ai_group_id=99,
        ai_group_name="AI-Group",
        ai_ticket_author="AI-Author",
        allow_no_answer_internal_note=True,
    )

    assert state.has_no_answer_internal_note is True


def test_ensure_ticket_not_already_processed_can_be_disabled() -> None:
    """Duplicate detection can be turned off through settings."""
    ticket = ZammadTicket(
        id=6,
        group_id=99,
        articles=[
            ZammadArticle(id=1, ticket_id=6, text="Inhalt des Anliegens", internal=False, author="Customer"),
            ZammadArticle(id=2, ticket_id=6, text="Eingang Ihres Anliegens", internal=False, author="System"),
            ZammadArticle(id=3, ticket_id=6, text="Interner Hinweis", internal=True, author="AI-Author"),
            ZammadArticle(
                id=4, ticket_id=6, text="Interner Artikel für interne Anhänge.", internal=True, author="Agent"
            ),
        ],
    )

    state = ensure_ticket_not_already_processed(
        ticket,
        ai_group_id=99,
        ai_group_name="AI-Group",
        ai_ticket_author="AI-Author",
        duplicate_detection_enabled=False,
    )

    assert state.already_processed is True
