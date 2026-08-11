"""Langfuse client helpers for observability and prompt retrieval."""

from logging import Logger
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langfuse.model import TextPromptClient

from app.utils.logging import getLogger

logger: Logger = getLogger(name="zammad-ai.observe.observer")


class LangfuseError(Exception):
    """Raised when Langfuse client encounters an error."""

    pass


class LangfuseClient:
    """Client for interacting with Langfuse to fetch prompts and build RunnableConfig with Langfuse callbacks."""

    def __init__(self) -> None:
        """Initialize the LangfuseClient with a callback handler and Langfuse client.

        Creates a new CallbackHandler used for Runnable callbacks and instantiates a Langfuse client.
        The Langfuse client is expected to be configured externally (for example via environment variables or other application configuration).
        """
        self.langfuse_handler: CallbackHandler = CallbackHandler()
        self.langfuse: Langfuse = Langfuse()  # Assumes Langfuse is configured via environment variables or other means

    def get_prompt(self, prompt_name: str, prompt_label: str = "production") -> tuple[str, int]:
        """Retrieve a prompt template from Langfuse by name and label.

        Parameters:
            prompt_name (str): Name of the prompt to fetch.
            prompt_label (str): Label or version of the prompt to fetch (default: "production").

        Returns:
            tuple[str, int]: A tuple containing the text content of the fetched prompt template and its version.

        Raises:
            LangfuseError: If fetching the prompt from Langfuse fails for any reason or if the returned prompt is not a string.
        """
        logger.debug(f"Fetching Langfuse prompt '{prompt_name}' with label '{prompt_label}'.")
        try:
            res: TextPromptClient = self.langfuse.get_prompt(
                name=prompt_name,
                label=prompt_label,
                type="text",
            )
            if not isinstance(res.prompt, str):
                raise LangfuseError(f"Prompt '{prompt_name}' is not of type text.")
            return res.prompt, res.version
        except Exception as e:
            if isinstance(e, LangfuseError):
                raise e
            logger.error(f"Failed to fetch Langfuse prompt '{prompt_name}' with label '{prompt_label}'", exc_info=True)
            raise LangfuseError(f"Failed to fetch Langfuse prompt '{prompt_name}' with label '{prompt_label}'.") from e

    def build_config(self, session_id: str | None = None) -> RunnableConfig:
        """Builds a RunnableConfig that attaches the Langfuse callback handler and embeds a session identifier in metadata.

        Parameters:
            session_id (str | None): Session ID to include in metadata; if None a new UUID4-based session ID is generated.

        Returns:
            RunnableConfig: Config with `callbacks` containing the Langfuse callback handler and `metadata` containing `"langfuse_session_id"` set to the session ID.
        """
        if session_id is None:
            session_id = self.generate_session_id()

        return RunnableConfig(
            callbacks=[self.langfuse_handler],
            metadata={
                "langfuse_session_id": session_id,
            },
        )

    def generate_session_id(self) -> str:
        """Generate a unique session ID for Langfuse tracing.

        Returns:
            session_id (str): A newly generated UUID4-based session identifier.
        """
        return str(uuid4())

    def attach_evaluation_to_trace(
        self,
        trace_id: str,
        thumbs_up: bool,
        comment: str | None = None,
        user: str | None = None,
        score_name: str = "user-thumbs",
    ) -> None:
        """Attach a simple thumbs-up/thumbs-down evaluation to an existing Langfuse trace.

        This uses the server-side Langfuse client (secret key) to create a score
        on the given `trace_id`. The frontend must NOT supply any secret; all
        writes happen with the server's configured Langfuse credentials.

        Parameters:
            trace_id: Langfuse trace id (32 hex chars)
            thumbs_up: True for positive (stored as BOOLEAN 1), False for negative (0)
            comment: Optional short text comment to attach to the score
            user: Optional user id or name to store in score metadata
        """
        try:
            value = 1.0 if thumbs_up else 0.0
            metadata = {"user": user} if user is not None else None
            self.langfuse.create_score(
                name=score_name,
                value=value,
                trace_id=trace_id,
                data_type="BOOLEAN",
                comment=comment,
                metadata=metadata,
            )
            logger.info(f"Attached evaluation to trace {trace_id}: thumbs_up={thumbs_up}")
        except Exception as e:
            logger.error("Failed to attach evaluation to Langfuse trace.", exc_info=True)
            raise LangfuseError("Failed to attach evaluation to Langfuse trace.") from e

    def get_trace_io(self, trace_id: str) -> tuple[str | None, str | None]:
        """Fetch a trace and try to extract a representative input/output pair.

        Returns a tuple (input, output) where values may be None if not found.
        """
        try:
            trace = self.langfuse.api.trace.get(trace_id=trace_id, fields="core,io")
            try:
                trace_dict = trace.dict() if hasattr(trace, "dict") else dict(trace)
            except Exception:
                trace_dict = {}

            def _nested_get(d, *keys, default="") -> str:
                if not isinstance(d, dict):
                    return default
                for k in keys:
                    if not isinstance(d, dict) or k not in d:
                        return default
                    d = d[k]
                return d or default

            input_data = trace_dict.get("input") if isinstance(trace_dict, dict) else None
            inp_str = _nested_get(input_data, "kwargs", "user_text") if input_data is not None else ""

            output_data = trace_dict.get("output") if isinstance(trace_dict, dict) else None
            subject = _nested_get(output_data, "subject") if output_data is not None else ""
            response = _nested_get(output_data, "response") if output_data is not None else ""
            out_str = (subject + "\n\n" + response) if subject and response else (subject or response or "")
            out_str = out_str.replace("<br>", "\n").strip()

            logger.debug(
                "Extracted trace input/output for trace_id %s: input=%s, output=%s",
                trace_id,
                inp_str,
                out_str,
            )
            return inp_str, out_str
        except Exception as e:
            logger.warning(f"Failed to fetch trace {trace_id}", exc_info=True)
            raise LangfuseError(f"Failed to fetch trace {trace_id}") from e
