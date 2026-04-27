"""Kafka event models used by the broker and API layers."""

from pydantic import AliasChoices, BaseModel, Field


class Event(BaseModel):
    """Event model for Kafka messages.

    Follows this structure: https://github.com/it-at-m/dbs/blob/main/ticketing-eventing/handler-core/src/main/java/de/muenchen/oss/dbs/ticketing/eventing/handlercore/domain/model/Event.java
    """

    action: str = Field(
        description="Action performed on the ticket",
        examples=["created"],
    )
    ticket: str = Field(
        description="ID of the ticket",
        examples=["3720"],
    )
    status: str = Field(
        description="Current status of the ticket",
        examples=["new"],
    )
    statusId: str = Field(
        description="ID of the current status",
        examples=["1"],
    )
    request_type: str = Field(
        validation_alias=AliasChoices("anliegenart", "requestType"),
        description="Type of request",
        examples=["technischer Bürgersupport"],
    )
    lhmExtId: str | None = Field(
        description="External ID from LHM",
        examples=[""],
    )
