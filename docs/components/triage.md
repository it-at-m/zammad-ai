# Triage Component

The Triage component is the core business logic of the Zammad-AI service. It is responsible for analyzing incoming Zammad tickets using Generative AI (GenAI) and determining the appropriate actions to take based on a set of configurable rules.

## Overview

The triage process follows these main steps:

1. **Data Retrieval**: Fetches the full ticket data from Zammad.
2. **Analysis**: Uses GenAI to categorize the ticket and extract relevant information (e.g., days since last request, processing IDs).
3. **Rule Evaluation**: Evaluates the analysis results against a set of `ActionRules` to decide on an `Action`.
4. **Execution**: Executes the determined action (e.g., posting a response or a draft to Zammad).

## Key Classes

### `Triage`

Located in `zammad-ai-workflow/app/triage/triage.py`. This class orchestrates the entire triage workflow. It is initialized with `ZammadAISettings`, which defines categories, actions, and rules.

### `GenAIHandler`

Located in `zammad-ai-workflow/app/triage/genai_handler.py`. This class handles all interactions with the language model using LangChain. It dynamically builds and caches chains based on prompt templates and optionally attaches Pydantic models for structured output.

## Configuration

The triage behavior is highly configurable via `app.settings.triage.TriageSettings`.

### Categories and Actions

- **Categories**: Logical groupings for tickets (e.g., "Support", "Billing").
- **Actions**: Tasks to perform (e.g., "Post Reply", "Internal Note").

### Action Rules

Rules consist of multiple `Conditions` that must be met to trigger an `Action`. Conditions can check:

- `CategorizationResult`: Matches a specific category.
- `DaysSinceRequestResponse`: Checks the time elapsed since the last customer request.
- `ProcessingIdResponse`: Matches internal tracking IDs.

## Prompt Management

The component supports three sources for prompt templates:

- **Langfuse**: Fetches prompts dynamically from the Langfuse service.
- **File**: Reads prompts from local Markdown files.
- **String**: Uses prompts provided directly in the configuration.
