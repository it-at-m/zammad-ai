from logging import Logger
from typing import override

from httpx import AsyncClient, HTTPStatusError, Response
from pydantic import SecretStr, TypeAdapter
from stamina import retry_context

from app.core.settings.zammad import ZammadAPISettings
from app.models.zammad import ZammadAnswer, ZammadArticle, ZammadTicket
from app.utils.logging import getLogger

from .base import BaseZammadClient, ZammadConnectionError

logger: Logger = getLogger("zammad-ai.triage.ticket_helper")


class ZammadAPIClient(BaseZammadClient):
    """Client for interacting with Zammad API to fetch and update ticket information."""

    def __init__(self, settings: ZammadAPISettings) -> None:
        """
        Initialize the Zammad API client and store configuration-derived attributes.
        
        Creates an AsyncClient configured with the settings' base URL, bearer authorization header, and timeout, and saves the knowledge_base_id, rss_feed_token, and max_retries from the provided settings.
        
        Parameters:
            settings (ZammadAPISettings): Configuration containing base_url, auth_token, timeout, knowledge_base_id, rss_feed_token, and max_retries.
        """
        self.client = AsyncClient(
            base_url=settings.base_url.encoded_string(),
            headers={"Authorization": f"Bearer {settings.auth_token}"},  # TODO: implement custom auth schema if needed
            timeout=settings.timeout,
        )
        self.knowledge_base_id: str | None = settings.knowledge_base_id
        self.rss_feed_token: SecretStr | None = settings.rss_feed_token
        self.max_retries: int = settings.max_retries

    @override
    async def get_ticket(self, id: str) -> ZammadTicket:
        """
        Fetches a ticket and its articles from Zammad using the ticket ID.
        
        Parameters:
            id (str): Ticket ID to fetch.
        
        Returns:
            ZammadTicket: Ticket containing the provided id and the parsed list of articles.
        
        Raises:
            ZammadConnectionError: If the request fails after retries or an HTTP error occurs.
        """
        try:
            for attempt in retry_context(on=HTTPStatusError, attempts=self.max_retries):
                with attempt:
                    # Send GET request to Zammad API to fetch ticket information
                    response: Response = await self.client.get(f"/api/v1/ticket_articles/by_ticket/{id}")
                    response.raise_for_status()
                    # Parse the response JSON into a list of ZammadArticle models via a pydantic TypeAdapter
                    ta: TypeAdapter[list[ZammadArticle]] = TypeAdapter(list[ZammadArticle])
                    articles: list[ZammadArticle] = ta.validate_json(response.text)
                    #
                    ticket = ZammadTicket(
                        id=id,
                        articles=articles,
                    )
                    return ticket
            else:
                logger.error(f"Failed to fetch ticket {id} after {self.max_retries} attempts.")
                raise ZammadConnectionError(f"Failed to fetch ticket {id} from Zammad after {self.max_retries} attempts.")

        except HTTPStatusError as e:
            logger.error(f"Failed to fetch ticket {id} after {self.max_retries} attempts.", exc_info=True)
            raise ZammadConnectionError(f"Failed to fetch ticket {id} from Zammad after {self.max_retries} attempts.") from e

    async def post_answer(
        self,
        ticket_id: str,
        text: str,
        internal: bool = False,
    ) -> None:
        """
        Post an answer to a Zammad ticket.
        
        Parameters:
            ticket_id (str): ID of the ticket to post the answer to.
            text (str): Content of the answer.
            internal (bool): If True, mark the answer as internal (visible only to agents).
        
        Raises:
            ZammadConnectionError: If posting the article fails after retrying.
        """
        article_payload = ZammadAnswer(
            ticket_id=ticket_id,
            body=text,
            internal=internal,
        )

        try:
            for attempt in retry_context(on=HTTPStatusError, attempts=self.max_retries):
                with attempt:
                    response: Response = await self.client.post(
                        url="/api/v1/ticket_articles",
                        json=article_payload.model_dump(),
                    )
                    response.raise_for_status()
                    logger.info(f"Successfully posted answer to ticket {ticket_id}.")
                    return
        except HTTPStatusError as e:
            logger.error(f"Failed to post answer to ticket {ticket_id} after {self.max_retries} attempts.", exc_info=True)
            raise ZammadConnectionError(f"Failed to post answer to ticket {ticket_id} after {self.max_retries} attempts.") from e

    async def post_shared_draft(
        self,
        ticket_id: str,
        text: str,
    ) -> None:
        """
        Create a shared draft (internal note) on a Zammad ticket.
        
        Raises:
            ZammadConnectionError: If posting fails after the configured retry attempts or if Zammad returns an HTTP error.
        """
        # TODO: move payload to zammad model with default values and validation for dynamic fields (ticket_id, text)
        payload = {
            "form_id": "367646073",
            "new_article": {
                "body": text,
                "cc": "",
                "content_type": "text/html",
                "from": "KI Agent",
                "in_reply_to": "",
                "internal": True,
                "sender_id": 1,
                "subject": "",
                "subtype": "",
                "ticket_id": ticket_id,
                "to": "",
                "type": "note",
                "type_id": 10,
            },
            "ticket_attributes": {"group_id": "2", "owner_id": "4", "priority_id": "2", "state_id": "2"},
        }

        try:
            for attempt in retry_context(on=HTTPStatusError, attempts=self.max_retries):
                with attempt:
                    response: Response = await self.client.put(
                        url=f"/api/v1/tickets/{ticket_id}/shared_draft",
                        json=payload,
                    )
                    response.raise_for_status()
                    logger.info(f"Successfully posted shared draft to ticket {ticket_id}.")
                    return
        except HTTPStatusError as e:
            logger.error(f"Failed to post shared draft to ticket {ticket_id} after {self.max_retries} attempts.", exc_info=True)
            raise ZammadConnectionError(f"Failed to post shared draft to ticket {ticket_id} after {self.max_retries} attempts.") from e

    async def add_tag_to_ticket(self, ticket_id: str, tag: str) -> None:
        """
        Add a tag to the specified Zammad ticket.
        
        Raises:
            ZammadConnectionError: If adding the tag fails after retrying the configured number of attempts.
        """
        # TODO: move payload to zammad model with default values and validation for dynamic fields (ticket_id, text)
        payload = {
            "item": tag,
            "object": "Ticket",
            "o_id": ticket_id,
        }
        try:
            for attempt in retry_context(on=HTTPStatusError, attempts=self.max_retries):
                with attempt:
                    response: Response = await self.client.post(
                        url="/api/v1/tags/add",
                        json=payload,
                    )
                    response.raise_for_status()
                    logger.info(f"Successfully added tag '{tag}' to ticket {ticket_id}.")
                    return
        except HTTPStatusError as e:
            logger.error(f"Failed to add tag '{tag}' to ticket {ticket_id} after {self.max_retries} attempts.", exc_info=True)
            raise ZammadConnectionError(f"Failed to add tag '{tag}' to ticket {ticket_id} after {self.max_retries} attempts.") from e