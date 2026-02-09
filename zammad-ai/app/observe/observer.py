from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler


class LangfuseClient:
    """Client for interacting with Langfuse to fetch prompts and build RunnableConfig with Langfuse callbacks."""

    def __init__(self) -> None:
        """
        Initialize the LangfuseClient with a callback handler and Langfuse client.
        
        Creates a new CallbackHandler used for Runnable callbacks and instantiates a Langfuse client.
        The Langfuse client is expected to be configured externally (for example via environment variables or other application configuration).
        """
        self.langfuse_handler: CallbackHandler = CallbackHandler()
        self.langfuse: Langfuse = Langfuse()  # Assumes Langfuse is configured via environment variables or other means

    def get_prompt(self, prompt_name: str, prompt_label: str = "production") -> str:
        """
        Retrieve a prompt template from Langfuse by name and label.
        
        Parameters:
        	prompt_name (str): Name of the prompt to fetch.
        	prompt_label (str): Label or version of the prompt to fetch (default: "production").
        
        Returns:
        	str: The text content of the fetched prompt template.
        """
        return self.langfuse.get_prompt(prompt_name, label=prompt_label).prompt

    def build_config(self, session_id: str | None = None) -> RunnableConfig:
        """
        Builds a RunnableConfig that attaches the Langfuse callback handler and embeds a session identifier in metadata.
        
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
        """
        Generate a unique session ID for Langfuse tracing.
        
        Returns:
            session_id (str): A newly generated UUID4-based session identifier.
        """
        return str(uuid4())