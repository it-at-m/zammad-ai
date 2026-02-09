from app.core.settings.zammad import ZammadEAISettings
from app.models.zammad import ZammadTicket

from .base import BaseZammadClient


class ZammadEAIClient(BaseZammadClient):
    """Zammad API client implementation for Zammad AI."""

    def __init__(self, settings: ZammadEAISettings):
        """Initialize the ZammadEAIClient with the provided settings.

        Args:
            settings (ZammadEAISettings): The settings for Zammad EAI integration, including API endpoint and authentication details.
        """
        ...

    async def get_ticket(self, id: str) -> ZammadTicket:
        """
        Retrieve a ticket from Zammad by its identifier.
        
        Parameters:
            id (str): Zammad ticket identifier.
        
        Returns:
            ZammadTicket: The ticket corresponding to the provided identifier.
        
        Raises:
            NotImplementedError: If the client implementation is not available.
        """
        raise NotImplementedError("ZammadEAIClient is not implemented yet.")

    async def post_answer(self, ticket_id: str, text: str, internal: bool = False) -> None:
        """
        Post an answer message to a Zammad ticket.
        
        Parameters:
            ticket_id (str): The identifier of the ticket to post the message to.
            text (str): The message content to add to the ticket.
            internal (bool): If True, post the message as an internal note; otherwise post it as a visible customer reply.
        """
        raise NotImplementedError("ZammadEAIClient is not implemented yet.")

    async def post_shared_draft(self, ticket_id: str, text: str) -> None:
        """
        Posts a shared draft message to the specified Zammad ticket.
        
        Parameters:
            ticket_id (str): Identifier of the ticket to attach the shared draft to.
            text (str): Draft message content to post.
        
        Raises:
            NotImplementedError: Implementation not provided in this client stub.
        """
        raise NotImplementedError("ZammadEAIClient is not implemented yet.")

    async def add_tag_to_ticket(self, ticket_id: str, tag: str) -> None:
        """
        Add a tag to the specified Zammad ticket.
        
        Parameters:
        	ticket_id (str): Identifier of the ticket to update.
        	tag (str): Tag value to add to the ticket.
        
        Raises:
        	NotImplementedError: Implementation is not provided in this client.
        """
        raise NotImplementedError("ZammadEAIClient is not implemented yet.")