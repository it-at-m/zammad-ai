# Zammad Integration

The Zammad integration component provides the interface for interacting with the Zammad ticketing system. It allows the service to retrieve ticket details and post updates (replies, drafts, notes).

## Architecture

The integration is built around an abstract base class `BaseZammadClient`, which defines the required operations. This allows for multiple implementations of the Zammad interface.

### `BaseZammadClient`

The abstract interface located in `zammad-ai-workflow/app/zammad/base.py`. It defines methods for:

- `get_ticket(id)`: Retrieving a ticket with its articles.
- `post_answer(ticket_id, text, internal)`: Posting a reply or internal note.
- `post_shared_draft(ticket_id, text)`: Saving a draft.

## Implementations

### `ZammadAPIClient` (REST API)

Located in `zammad-ai-workflow/app/zammad/api.py`. This is the primary implementation using Zammad's official REST API.

- **Authentication**: Uses Bearer Token authentication.
- **Retries**: Uses `stamina` for robust HTTP request handling with exponential backoff.
- **Data Models**: Maps Zammad JSON responses to Pydantic models in `app.models.zammad`.

### `ZammadEAIClient` (Internal EAI)

Located in `zammad-ai-workflow/app/zammad/eai.py`. This is a skeleton implementation intended for integration with internal Enterprise Application Integration (EAI) systems. Currently, it raises `NotImplementedError` for most methods.

## Models

Incoming Zammad data and outgoing requests are validated using Pydantic models defined in `zammad-ai-workflow/app/models/zammad.py`. These models ensure type safety and consistent data structures throughout the application.
