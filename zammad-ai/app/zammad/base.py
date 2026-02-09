from abc import ABC, abstractmethod

from app.models.zammad import ZammadTicket


class BaseZammadClient(ABC):
    """Abstract base class for Zammad API clients."""

    @abstractmethod
    async def get_ticket(
        self,
        id: str,
    ) -> ZammadTicket:
        """
        Fetches ticket information for a given Zammad ticket ID.
        
        Parameters:
            id (str): Zammad ticket ID to retrieve.
        
        Returns:
            ZammadTicket: Ticket data corresponding to the provided ID.
        """
        ...

    @abstractmethod
    async def post_answer(
        self,
        ticket_id: str,
        text: str,
        internal: bool = False,
    ) -> None:
        """
        Post an answer to the specified Zammad ticket.
        
        Parameters:
            ticket_id: ID of the ticket to update.
            text: Answer content to post.
            internal: If True, post as an internal note not visible to the customer.
        """
        ...

    @abstractmethod
    async def post_shared_draft(
        self,
        ticket_id: str,
        text: str,
    ) -> None:
        """
        Post a shared draft to the specified Zammad ticket.
        
        Parameters:
        	ticket_id (str): ID of the ticket to post the shared draft to.
        	text (str): Content of the shared draft.
        """
        ...

    @abstractmethod
    async def add_tag_to_ticket(
        self,
        ticket_id: str,
        tag: str,
    ) -> None:
        """
        Add a tag to the specified Zammad ticket.
        
        Parameters:
            ticket_id (str): Zammad ticket identifier.
            tag (str): Tag text to add to the ticket.
        """
        ...


class ZammadConnectionError(Exception):
    """Custom exception for Zammad connection errors."""

    pass