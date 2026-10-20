"""Deterministic routing of Kafka events and polling tickets."""

from app.models.kafka import Event
from app.models.zammad import ZammadTicket
from app.settings.usecase import UseCaseSettings


class UseCaseResolver:
    """Resolve events against startup-validated usecase definitions."""

    def __init__(self, usecases: list[UseCaseSettings]) -> None:
        """Create a resolver from startup-validated definitions."""
        self.usecases = usecases

    def resolve_event(self, event: Event) -> UseCaseSettings | None:
        """Return the usecase matching a Kafka event, if any."""
        for usecase in self.usecases:
            if any(
                (match.request_type is None or match.request_type == event.request_type)
                and (match.action is None or match.action == event.action)
                for match in usecase.match
            ):
                return usecase
        return None

    def resolve_ticket(self, ticket: ZammadTicket) -> UseCaseSettings | None:
        """Return the usecase matching polling ticket metadata, if any."""
        for usecase in self.usecases:
            if any(
                (match.group_id is None or match.group_id == ticket.group_id)
                and (match.group_name is None or match.group_name == ticket.group_name)
                for match in usecase.polling_match
            ):
                return usecase
        return None
