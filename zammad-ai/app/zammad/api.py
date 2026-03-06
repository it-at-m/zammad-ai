import base64
from logging import Logger
from typing import override

import feedparser
from pydantic import TypeAdapter

from app.core.settings.zammad import ZammadAPISettings
from app.models.zammad import (
    KnowledgeBaseAnswer,
    KnowledgeBaseAttachment,
    ZammadAnswer,
    ZammadArticle,
    ZammadKnowledgebase,
    ZammadSharedDraftAPI,
    ZammadSharedDraftArticle,
    ZammadTagAdd,
    ZammadTicket,
)
from app.utils.logging import getLogger

from .base import BaseZammadClient

logger: Logger = getLogger("zammad-ai.zammad.api")


class ZammadAPIClient(BaseZammadClient):
    """Client for interacting with Zammad API to fetch and update ticket information."""

    def __init__(self, settings: ZammadAPISettings):
        """
        Initialize the Zammad API client with configuration from `settings`.
        
        Initializes the underlying HTTP client with base URL, timeout, retry and proxy settings, sets the Authorization header from the provided auth token, and stores the configured knowledge base ID and RSS feed token on the instance.
        
        Parameters:
            settings (ZammadAPISettings): Configuration including base_url, timeout, max_retries, proxy_url, auth_token, knowledge_base_id, and rss_feed_token.
        """
        super().__init__(
            base_url=settings.base_url.encoded_string(),
            timeout=settings.timeout,
            max_retries=settings.max_retries,
            proxy_url=settings.proxy_url,
        )

        # Set auth header
        self.client.headers.update({"Authorization": f"Bearer {settings.auth_token.get_secret_value()}"})

        self.kb_id = settings.knowledge_base_id
        self.rss_token = settings.rss_feed_token

    @override
    async def get_ticket(self, id: str) -> ZammadTicket:
        """
        Fetches articles for the specified ticket and returns a ZammadTicket containing them.
        
        Parameters:
            id (str): ID of the ticket to retrieve.
        
        Returns:
            ZammadTicket: Ticket object populated with the ticket `id` and its list of parsed articles.
        """
        data = await self._request("GET", f"/api/v1/ticket_articles/by_ticket/{id}")
        articles = TypeAdapter(list[ZammadArticle]).validate_python(data)
        return ZammadTicket(id=id, articles=articles)

    @override
    async def post_answer(self, ticket_id: str, text: str, subject: str | None = None, internal: bool = False) -> None:
        """
        Post an article (answer) to a Zammad ticket.
        
        Parameters:
        	ticket_id (str): ID of the ticket to post the article to.
        	text (str): Body text of the article.
        	subject (str | None): Optional subject/title for the article.
        	internal (bool): If `True`, the article is marked internal; otherwise it's visible to the customer.
        """
        payload = ZammadAnswer(ticket_id=ticket_id, body=text, internal=internal, subject=subject)
        await self._request("POST", "/api/v1/ticket_articles", json=payload.model_dump())
        logger.info(f"Posted answer to ticket {ticket_id}")

    @override
    async def post_shared_draft(self, ticket_id: str, text: str) -> None:
        """
        Post a shared draft article to a Zammad ticket.
        
        Creates and uploads a shared draft article for the specified ticket using the configured Zammad API.
        
        Parameters:
            ticket_id (str): ID of the ticket to attach the shared draft to.
            text (str): Body content of the shared draft article.
        """
        payload = ZammadSharedDraftAPI(new_article=ZammadSharedDraftArticle(body=text, ticket_id=ticket_id))
        await self._request("PUT", f"/api/v1/tickets/{ticket_id}/shared_draft", json=payload.model_dump(by_alias=True))
        logger.info(f"Posted shared draft to ticket {ticket_id}")

    @override
    async def add_tag_to_ticket(self, ticket_id: str, tag: str) -> None:
        """
        Attach a tag to a Zammad ticket.
        
        Parameters:
            ticket_id (str): ID of the ticket to update.
            tag (str): Tag value to add to the ticket.
        """
        payload = ZammadTagAdd(item=tag, o_id=ticket_id)
        await self._request("POST", "/api/v1/tags/add", json=payload.model_dump())
        logger.info(f"Added tag '{tag}' to ticket {ticket_id}")

    @override
    async def show_kb(self) -> ZammadKnowledgebase | None:
        """
        Retrieve metadata for the client's configured knowledge base.
        
        Returns:
            ZammadKnowledgebase: Parsed knowledge base object containing `id`, `active`, `createdAt`, `updatedAt`, `categoryIds`, and `answerIds`, or `None` if no knowledge base is configured or the API returned no data.
        """
        if not self.kb_id:
            return None

        data = await self._request("GET", f"/api/v1/knowledge_bases/{self.kb_id}")
        return (
            ZammadKnowledgebase(
                id=data["id"],
                active=data["active"],
                createdAt=data["created_at"],
                updatedAt=data["updated_at"],
                categoryIds=data.get("category_ids", []),
                answerIds=data.get("answer_ids", []),
            )
            if data
            else None
        )

    @override
    async def parse_rss_feed(self) -> feedparser.FeedParserDict | None:
        """
        Parse the knowledge base RSS feed for the configured knowledge base.
        
        Returns:
            feed (feedparser.FeedParserDict): The parsed RSS feed, or `None` if the knowledge base ID or RSS token is not configured or no feed data was retrieved.
        """
        if not self.kb_id or not self.rss_token:
            return None

        url = f"/api/v1/knowledge_bases/{self.kb_id}/de-de/feed"
        text = await self._request("GET", url, params={"token": self.rss_token.get_secret_value()})
        return feedparser.parse(base64.b64decode(text).decode("utf-8"))

    @override
    async def get_kb_answer_by_id(self, answer_id: str) -> KnowledgeBaseAnswer | None:
        """
        Retrieve a knowledge-base answer by its ID from the configured knowledge base.
        
        Parameters:
            answer_id (str): Identifier of the knowledge-base answer to fetch.
        
        Returns:
            KnowledgeBaseAnswer | None: A KnowledgeBaseAnswer populated with id, answerTitle, answerBody, attachments, createdAt, and updatedAt if found; `None` if no knowledge base is configured or the answer could not be retrieved.
        """
        if not self.kb_id:
            return None

        try:
            response = await self._request("GET", f"/api/v1/knowledge_bases/{self.kb_id}/answers/{answer_id}?include_contents={answer_id}")
            return KnowledgeBaseAnswer(
                id=response["id"],
                answerTitle=response["assets"]["KnowledgeBaseAnswerTranslation"][answer_id]["title"],
                answerBody=response["assets"]["KnowledgeBaseAnswerTranslationContent"][answer_id]["body"],
                attachments=[
                    KnowledgeBaseAttachment(
                        id=attachment["id"], filename=attachment["filename"], contentType=attachment["preferences"]["Content-Type"]
                    )
                    for attachment in response["assets"]["KnowledgeBaseAnswer"][answer_id]["attachments"]
                ],
                createdAt=response["assets"]["KnowledgeBaseAnswer"][answer_id]["created_at"],
                updatedAt=response["assets"]["KnowledgeBaseAnswer"][answer_id]["updated_at"],
            )
        except Exception:
            logger.warning(f"Failed to fetch knowledge base answer {answer_id}", exc_info=True)
            return None

    @override
    async def fetch_kb_attachment_data(self, id: str) -> str | None:
        """
        Fetches the raw data for a knowledge-base attachment by its ID.
        
        Parameters:
            id (str): The attachment identifier to fetch.
        
        Returns:
            data (str | None): The attachment content as a string if found, `None` if `id` is falsy or the attachment could not be retrieved.
        """
        return await self._request("GET", f"/api/v1/attachments/{id}") if id else None

    @override
    async def fetch_ticket_attachment_data(self, ticket_id: str, attachment_id: str, article_id: str) -> str | None:
        """
        Retrieve the raw content of a ticket attachment.
        
        Parameters:
            ticket_id (str): Identifier of the ticket containing the attachment.
            attachment_id (str): Identifier of the attachment to fetch.
            article_id (str): Identifier of the ticket article that references the attachment.
        
        Returns:
            attachment_data (str | None): Raw attachment content as returned by the API, or `None` if any identifier is missing.
        """
        return (
            await self._request("GET", f"/api/v1/ticket_attachment/{ticket_id}/{article_id}/{attachment_id}")
            if ticket_id and attachment_id and article_id
            else None
        )

    @override
    async def check_if_answer_exists(self, answer_id: str) -> bool:
        """
        Check whether a knowledge-base answer with the given ID exists.
        
        Parameters:
            answer_id (str): Identifier of the knowledge-base answer to check.
        
        Returns:
            bool: `true` if an answer with `answer_id` exists, `false` otherwise.
        """
        answer: KnowledgeBaseAnswer | None = await self.get_kb_answer_by_id(answer_id)
        return answer is not None
