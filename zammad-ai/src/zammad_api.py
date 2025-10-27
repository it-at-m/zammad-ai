from typing import Literal

from httpx import AsyncClient, Response
from pydantic import BaseModel, Field


class ZammadTicket(BaseModel):
    id: int = Field(description="The unique identifier of the ticket")
    number: str = Field(description="The ticket number")
    title: str = Field(description="The title of the ticket")
    articles: list["ZammadArticle"] = Field(description="The list of articles included with the ticket")


class ZammadArticle(BaseModel):
    content_type: Literal["text/html", "text/plain"] = Field(description="The content type of the article")
    subject: str = Field(description="The subject of the article")
    body: str = Field(description="The body of the article")
    sender: Literal["Agent", "Customer", "System"] = Field(description="The sender of the article")
    to: str = Field(description="The recipient of the article")
    cc: str = Field(description="The CC recipient of the article")
    type: Literal["email", "phone", "web", "note", "sms", "chat", "fax"] = Field(description="The type of the article")
    internal: bool = Field(description="Whether the article is internal or not")
    time_unit: str = Field(description="The minutes it took to create the article / do the work")


class ZammadAPI:
    def __init__(self, base_url: str) -> None:
        self.base_url: str = base_url
        self.client = AsyncClient(base_url=self.base_url)

    async def get_ticket(self, ticket_id: int) -> ZammadTicket:
        """Fetch a ticket by its ID.

        Args:
            ticket_id (int): The ID of the ticket to fetch.

        Returns:
            ZammadTicket: The fetched ticket.

        Raises:
            HTTPStatusError: If the request to fetch the ticket fails.
            HTTPError: If the HTTP transport fails.
            ValidationError: If the response data cannot be validated against the ZammadTicket model.
        """
        response: Response = await self.client.get(url=f"/tickets/byId/{ticket_id}")
        response.raise_for_status()

        ticket: ZammadTicket = ZammadTicket.model_validate_json(json_data=response.text)
        return ticket

    async def create_article(self, ticket_id: int, article: ZammadArticle) -> bool:
        """Create a new article for a ticket.

        Args:
            ticket_id (int): The ID of the ticket to which the article will be added.
            article (ZammadArticle): The article to be added to the ticket.

        Returns:
            bool: True if the article was created successfully, False otherwise.
        """
        response: Response = await self.client.post(
            url=f"/v2/tickets/{ticket_id}/articles",
            data=article.model_dump(),
        )
        response.raise_for_status()
        return response.status_code == 201

    async def close(self) -> None:
        await self.client.aclose()
