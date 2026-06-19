# Observability (Langfuse)

The service integrates with Langfuse to provide observability, tracing, and dynamic prompt management for all AI-related operations.

## Features

### LLM Tracing

All calls to language models are traced using Langfuse's LangChain integration. This includes:

- Input and output text.
- Token counts and costs.
- Latency and execution steps.
- Metadata such as session IDs for grouping related traces.

### Prompt Management

Prompt templates can be managed directly in the Langfuse UI. The `LangfuseClient` in `zammad-ai-workflow/app/observe/langfuse.py` retrieves these prompts by name and label (e.g., `production`). This allow updating prompts without redeploying the service.

## Integration Details

### `LangfuseClient`

This client handles:

- **Callback Initialization**: Sets up `CallbackHandler` for LangChain.
- **Dynamic Prompt Fetching**: Implements `get_prompt` to retrieve text-based templates.
- **Session Tracking**: Generates unique session IDs and builds `RunnableConfig` objects that include the Langfuse callback.

### Environment Variables

Langfuse is typically configured using standard environment variables:

- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_HOST`

## Implementation in Triage

The `GenAIHandler` uses the `LangfuseClient` to wrap every chain execution in a trace. If a `session_id` is provided (e.g., from a Kafka event or API request), it is used to group the resulting traces in the Langfuse dashboard.
