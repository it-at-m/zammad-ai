# Answer Component

The answer component generates a structured reply for a ticket using a LangChain agent with retrieval tools.

## Overview

The workflow is:

1. Inject knowledge-base context retrieved from Qdrant as a system message.
2. Let the agent answer user requests using its tools.
3. Trim the conversation before every model call so it fits the model context window.
4. Return a structured answer candidate.

## Key Modules

### `app/answer/middleware.py`

Contains the LangGraph middleware for knowledge-base context injection and context trimming.

### `app/answer/agent.py`

Builds the agent and wires both middleware hooks via `build_agent`.

## Knowledge-Base Context Injection

Before the agent starts, `build_knowledgebase_middleware` generates a search query from the latest user message, retrieves documents from Qdrant, and injects them as a system message prefixed with `Knowledge-base context`. The result is cached in the runtime context so it is built once per run.

## Context Trimming

Before every model call, `build_context_trimming_middleware` keeps the conversation within the model context window. The budget is:

```text
context_window_tokens - max_tokens - context_overhead_tokens
```

Token counts are estimated using `chars_per_token`, which defaults to a conservative `3.0` characters per token.

Trimming runs in two steps:

1. **Drop old exchanges.** Messages are grouped into exchanges, keeping tool results attached to their tool-call message so the sequence stays valid. Oldest exchanges are removed first. System messages are never removed. The first pass preserves all human messages; if the budget is still exceeded, a second pass also removes older human messages except the latest one.
2. **Truncate the knowledge-base context.** The injected knowledge-base system message is shortened to the space left by the remaining messages and receives a truncation notice. Duplicate knowledge-base context messages are removed.

Removal is best effort: when the protected messages alone exceed the budget, every removable exchange is still dropped instead of leaving the conversation unchanged.

### Law Re-Retrieval

When a removed exchange contains a law tool call, the middleware releases the law id from the `searched_laws` set. This allows the agent to retrieve the law again instead of receiving the "already searched" stub response for documents that are no longer part of the conversation.

## Configuration

The trimming behavior is configured by `app.settings.genai.BaseGenAISettings` under `genai`:

- `context_window_tokens`: maximum context window of the model in tokens (default `131072`).
- `max_tokens`: tokens reserved for the model response (default `8192`).
- `context_overhead_tokens`: reserve for the agent prompt, tool schemas, and tokenization overhead (default `8192`).
- `chars_per_token`: estimated characters per token used for the approximation (default `3.0`).

The middleware logs a warning when exchanges were removed, when the knowledge-base context was truncated, and when the conversation cannot be trimmed below the budget after removing all removable exchanges.
