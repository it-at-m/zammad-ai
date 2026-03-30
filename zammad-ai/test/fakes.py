"""Test doubles used across the Zammad AI test suite."""

from app.models.triage import CategorizationResult, DaysSinceRequestResponse, ProcessingIdResponse
from app.models.zammad import ZammadTicket
from app.settings import GenAISettings
from app.settings.zammad import ZammadAPISettings


class FakeZammadConnectionError(Exception):
    """Raised by the fake Zammad client when connection errors are simulated."""

    pass


class FakeLangfuseClient:
    """Small test double for Langfuse session handling."""

    class _FakeLangfuse:
        def update_current_trace(self, *, session_id: str) -> None:
            del session_id
            return None

    def __init__(self) -> None:
        """Initialize the fake Langfuse client."""
        self.langfuse = self._FakeLangfuse()

    def build_config(self, *, session_id: str) -> dict:
        """Return a minimal runnable config for tests."""
        del session_id
        return {}

    def generate_session_id(self) -> str:
        """Return a stable session id for deterministic tests."""
        return "session-id"


class FakeGenAIHandler:
    """Test double for GenAI handler calls used in triage tests."""

    REQUIRED_PROMPT_KEYS = {"categorization", "days_since_request", "processing_id"}

    def __init__(self, genai_settings: GenAISettings, prompts: dict[str, str]) -> None:
        """Initialize fake handler state and validate prompt configuration.

        Args:
            genai_settings: GenAI configuration kept for constructor parity.
            prompts: Mapping of prompt keys to prompt templates.

        Raises:
            ValueError: If prompts are empty, contain empty values, or miss
                required keys.
        """
        del genai_settings

        if not prompts:
            raise ValueError("Prompts dictionary cannot be empty.")

        empty_keys = [key for key, value in prompts.items() if not value]
        if empty_keys:
            raise ValueError(
                f"Empty prompt values for keys: {', '.join(empty_keys)}. All prompts must be non-empty strings."
            )

        missing_keys = self.REQUIRED_PROMPT_KEYS - set(prompts)
        if missing_keys:
            raise ValueError(f"Missing required prompt keys: {', '.join(sorted(missing_keys))}.")

        self.prompts = prompts
        self.langfuse_client = FakeLangfuseClient()
        self._categorization_chain = self._build_chain(prompt_key="categorization", schema=CategorizationResult)
        self._days_since_request_chain = self._build_chain(
            prompt_key="days_since_request", schema=DaysSinceRequestResponse
        )
        self._processing_id_chain = self._build_chain(prompt_key="processing_id", schema=ProcessingIdResponse)
        self.categorization_result: CategorizationResult | None = None
        self.days_since_request_response: DaysSinceRequestResponse | None = None
        self.processing_id_response: ProcessingIdResponse | None = None

    def _build_chain(self, prompt_key: str, schema: type) -> type:
        """Build a lightweight fake chain descriptor.

        Args:
            prompt_key: Prompt key identifying the configured prompt.
            schema: Structured output schema associated with the chain.

        Returns:
            The schema type used as fake chain descriptor.

        Raises:
            KeyError: If prompt_key is missing from configured prompts.
        """
        if prompt_key not in self.prompts:
            raise KeyError(f"Prompt key '{prompt_key}' not found in prompts dictionary.")
        return schema

    def _build_runnable_config(self, session_id: str | None) -> tuple[str, dict]:
        """Resolve session id and return a fake runnable config.

        Args:
            session_id: Optional external session identifier.

        Returns:
            Tuple of resolved session id and fake runnable config.
        """
        resolved_session_id: str | None = session_id.strip() if session_id is not None else None
        if not resolved_session_id:
            resolved_session_id = self.langfuse_client.generate_session_id()

        self.langfuse_client.langfuse.update_current_trace(session_id=resolved_session_id)
        config = self.langfuse_client.build_config(session_id=resolved_session_id)
        return resolved_session_id, config

    async def categorize_ticket(
        self,
        *,
        message: str,
        role_description: str,
        categories: list,
        categories_prompt: str,
        examples: str,
        session_id: str | None = None,
    ) -> CategorizationResult:
        """Return a fake categorization result for tests."""
        del message, role_description, categories, categories_prompt, examples
        _, config = self._build_runnable_config(session_id=session_id)
        del config

        if self._categorization_chain is not CategorizationResult:
            raise ValueError("Unsupported schema type for categorization chain")

        if self.categorization_result is None:
            return CategorizationResult(category=None, reasoning="no result", confidence=0.0)
        return self.categorization_result

    async def extract_days_since_request(
        self,
        *,
        message: str,
        today: str,
        session_id: str | None = None,
    ) -> DaysSinceRequestResponse:
        """Return a fake days-since-request extraction result for tests."""
        del message, today
        _, config = self._build_runnable_config(session_id=session_id)
        del config

        if self._days_since_request_chain is not DaysSinceRequestResponse:
            raise ValueError("Unsupported schema type for days-since-request chain")

        if self.days_since_request_response is None:
            return DaysSinceRequestResponse(days_since_request=0, reason="default")
        return self.days_since_request_response

    async def extract_processing_id(
        self,
        *,
        message: str,
        session_id: str | None = None,
    ) -> ProcessingIdResponse:
        """Return a fake processing-id extraction result for tests."""
        del message
        _, config = self._build_runnable_config(session_id=session_id)
        del config

        if self._processing_id_chain is not ProcessingIdResponse:
            raise ValueError("Unsupported schema type for processing-id chain")

        if self.processing_id_response is None:
            return ProcessingIdResponse(processing_id="")
        return self.processing_id_response


class FakeZammadClient:
    """Fake Zammad client for unit tests."""

    def __init__(self, settings: ZammadAPISettings) -> None:
        """Create a fake Zammad client configured for tests.

        Parameters:
            settings (ZammadAPISettings): Configuration used by the fake client; stored on the instance.

        The instance initializes `ticket` to None and `raise_connection_error` to False to allow tests to inject a ticket or simulate a connection error.
        """
        self.settings = settings
        self.ticket: ZammadTicket | None = None
        self.raise_connection_error: bool = False

    async def get_ticket(self, id: int) -> ZammadTicket:
        """Retrieve a ticket by id, raising a fake connection error when configured.

        If a preset ticket has been assigned to the fake client, that ticket is returned.
        Otherwise returns a new ZammadTicket with the given `id` and an empty `articles` list.

        Parameters:
            id (int): The ticket identifier to fetch.

        Returns:
            ZammadTicket: The fetched or default ticket for the given `id`.

        Raises:
            FakeZammadConnectionError: If the client is configured to simulate a connection error.
        """
        if self.raise_connection_error:
            raise FakeZammadConnectionError("Fake connection error")
        if self.ticket is None:
            return ZammadTicket(id=id, articles=[])
        return self.ticket

    async def post_answer(self, ticket_id: str, text: str, internal: bool = False) -> None:
        """Prevent posting an answer during tests by failing if called.

        Raises:
            AssertionError: Always raised to indicate this method must not be invoked in tests.
        """
        raise AssertionError("post_answer should not be called in these tests")

    async def post_shared_draft(self, ticket_id: str, text: str) -> None:
        """Signal that posting a shared draft is unsupported by this fake client and fail the test if invoked.

        Raises:
            AssertionError: Always raised to indicate this method must not be called in tests.
        """
        raise AssertionError("post_shared_draft should not be called in these tests")

    async def add_tag_to_ticket(self, ticket_id: str, tag: str) -> None:
        """Prevent accidental use of tag-adding in tests by failing immediately.

        Raises:
            AssertionError: Always raised to indicate this fake client must not be asked to add a tag to a ticket during tests.
        """
        raise AssertionError("add_tag_to_ticket should not be called in these tests")

    async def cleanup(self) -> None:
        """Perform cleanup for the fake client.

        This implementation performs no action.
        """
        return None

    async def parse_rss_feed(self) -> dict | None:
        """Stub method that must not be called during tests and signals misuse by raising an AssertionError.

        @raises AssertionError: always raised with message "parse_rss_feed should not be called in these tests"
        """
        raise AssertionError("parse_rss_feed should not be called in these tests")

    async def get_kb_answer_by_id(self, answer_id: str) -> dict | None:
        """Fail if knowledge-base lookup is attempted in tests."""
        raise AssertionError("get_kb_answer_by_id should not be called in these tests")

    async def fetch_attachment_data(self, url: str) -> str | None:
        """Fail the test if code attempts to fetch attachment data from a URL.

        Raises:
            AssertionError: Always raised with message "fetch_attachment_data should not be called in these tests".
        """
        raise AssertionError("fetch_attachment_data should not be called in these tests")

    async def check_if_answer_exists(self, answer_id: str) -> bool:
        """Indicates whether a knowledge-base answer exists for the given answer ID.

        Parameters:
            answer_id (str): The identifier of the knowledge-base answer to check.

        Returns:
            `true` if an answer with the given ID exists, `false` otherwise.

        Raises:
            AssertionError: Always raised in this fake implementation with the message
            "check_if_answer_exists should not be called in these tests".
        """
        raise AssertionError("check_if_answer_exists should not be called in these tests")
