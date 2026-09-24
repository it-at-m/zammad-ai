# Observability (Langfuse)

The workflow and index job can integrate with Langfuse for tracing and prompt management.

## Features

### LLM Tracing

All calls to language models are traced using Langfuse's LangChain integration. This includes:

- Input and output text.
- Token counts and costs.
- Latency and execution steps.
- Metadata such as session IDs for grouping related traces.

### Prompt Management

Prompt templates can be managed directly in the Langfuse UI. The workflow loads prompts from `app/observe/langfuse.py` by name and label, which allows prompt updates without redeploying the service.

## Integration Details

### `LangfuseClient`

This client handles:

- callback initialization for LangChain
- prompt fetching by name and label
- session tracking via request or Kafka session IDs
- dedicated feedback traces for `StaticAnswer` and `NoAnswerPossible` responses so internal notes can always point to a Langfuse trace

### Environment Variables

Langfuse is typically configured using standard environment variables:

- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_HOST`

## Implementation in Triage

The triage and answer flows wrap chain execution in traces when `langfuse_enabled` is true.

For internal feedback notes, the workflow also creates explicit Langfuse traces for static answers and no-answer results. That keeps feedback links available even when no LLM-generated trace exists.

These feedback traces reuse the session ID from the related triage run so categorization and feedback stay grouped together in Langfuse.
