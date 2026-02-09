"""Backend context for sharing application state across handlers."""

from app.core.settings import ZammadAISettings
from app.triage.triage import Triage


class BackendContext:
    """Context class holding shared application state.

    This class manages the lifecycle of shared resources like the Triage instance,
    ensuring a single instance is used across all REST and Kafka handlers.
    """

    def __init__(self, settings: ZammadAISettings):
        """
        Create a BackendContext that stores application settings and initializes the shared Triage instance.
        
        Parameters:
            settings (ZammadAISettings): Application configuration used to configure internal resources, including the Triage instance.
        """
        self.settings = settings
        self.triage = Triage(settings=settings)

    async def cleanup(self) -> None:
        """
        Perform cleanup of BackendContext-managed resources during application shutdown.
        
        This method is a no-op by default; override or extend it to close or release resources (for example, external handlers, connections, or file handles) that require explicit cleanup.
        """
        # Future: Add cleanup for GenAIHandler, Langfuse, etc. if needed
        pass


# Module-level variable to hold the shared context
backend_context: BackendContext | None = None


def get_backend_context() -> BackendContext:
    """Get the current backend context.

    Returns:
        BackendContext: The shared backend context

    Raises:
        RuntimeError: If backend context has not been initialized
    """
    if backend_context is None:
        raise RuntimeError("Backend context not initialized. Ensure the FastAPI lifespan has been executed.")
    return backend_context