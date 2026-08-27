# Zammad Integration

The Zammad integration layer provides the clients used by both services to talk to Zammad.

## Architecture

The integration is built around `BaseZammadClient`, which defines the shared operations for the workflow and index job.

### `BaseZammadClient`

The abstract interface located in `zammad-ai-workflow/app/zammad/base.py`. It defines methods for:

- `get_ticket(id)`: Retrieving a ticket with its articles.
- `post_answer(ticket_id, text, internal)`: Posting a reply or internal note.
- `post_shared_draft(ticket_id, text)`: Saving a draft.

## Implementations

### `ZammadAPIClient` (REST API)

Located in `zammad-ai-workflow/app/zammad/api.py` and `zammad-ai-index/job/zammad/api.py`.

- Uses Bearer Token authentication when the API token secret is configured.
- Handles ticket retrieval, knowledge base lookup, and answer synchronization.
- Maps Zammad JSON responses to Pydantic models.

### `ZammadEAIClient` (Internal EAI)

Located in `zammad-ai-workflow/app/zammad/eai.py` and `zammad-ai-index/job/zammad/eai.py`.

- Used when the deployment talks to Zammad through EAI instead of the REST API.
- The client is selected through the `zammad.type` setting.

## Models

Incoming Zammad data and outgoing requests are validated using Pydantic models defined in `app/models/zammad.py` and `job/models/zammad.py`.

## Related Configuration

- `zammad.type`
- `zammad.base_url` -> Base URL of the Zammad instance. Use it for API calls and to generate links, such as knowledge base articles.
- `zammad.knowledge_base_id`
- `zammad.auth_token` or EAI OAuth fields
- `zammad.document_parsing`
- `zammad.eai_url` (if using EAI)
