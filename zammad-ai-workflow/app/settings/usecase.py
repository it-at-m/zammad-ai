"""Use case configuration for the Zammad AI deployment."""

from pydantic import BaseModel


class UseCaseSettings(BaseModel):
    """Settings related to the specific use case for the AI integration, such as the name and description of the use case."""

    name: str
    description: str
