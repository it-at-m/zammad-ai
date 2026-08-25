# Triage Component

The triage component classifies incoming ticket text and selects the action to run next.

## Overview

The workflow is:

1. Preparse the incoming text if the preparser is enabled.
2. Ask the triage LLM to categorize the request.
3. Evaluate the configured action rules.
4. Return the triage result to the API or Kafka flow.

## Key Modules

### `app/triage/triage.py`

Orchestrates the triage workflow and ties together prompt handling, category prediction, and action selection.

### `app/triage/genai_handler.py`

Handles LLM calls and structured output.

## Configuration

The triage behavior is configured by `app.settings.triage.TriageSettings`.

### Categories and Actions

- Categories define the classification targets.
- Actions define what the system should do next.

### Action Rules

Rules map categories to actions and can override the default action with conditions.

Conditions can check:

- `processing_id`
- `days_since_request`

The settings also support:

- `no_category_name` and `no_action_name` fallbacks
- `no_action_internal_note` when no action is taken
- `category_wrong_retry_confidence_threshold` for low-confidence retries

## Prompt Management

The component supports three sources for prompt templates:

- **Langfuse**: Fetches prompts dynamically from the Langfuse service.
- **File**: Reads prompts from local Markdown files.
- **String**: Uses prompts provided directly in the configuration.
