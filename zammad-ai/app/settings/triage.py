"""Triage configuration models and validation rules."""

from __future__ import annotations

from enum import Enum
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, FilePath, model_validator


class TriageSettings(BaseModel):
    """Settings for triage categories, actions, rules, and prompts."""

    categories: list["Category"]
    no_category_name: str
    actions: list["Action"]
    no_action_name: str
    action_rules: list["ActionRule"]
    prompts: StringTriagePrompts | FileTriagePrompts | LangfuseTriagePrompts = Field(
        description="Prompts for the triage process. Can be provided as raw strings, file paths, or Langfuse prompt references.",
        discriminator="type",
    )

    _required_prompt_keys: ClassVar[set[str]] = {"categories", "examples", "role"}

    @staticmethod
    def _collect_named_items(items: list["Category"] | list["Action"]) -> tuple[set[str], list[str]]:
        names: set[str] = set()
        duplicates: list[str] = []

        for item in items:
            if item.name in names:
                duplicates.append(item.name)
            names.add(item.name)

        return names, duplicates

    @classmethod
    def _validate_references(
        cls, *, category_names: set[str], action_names: set[str], rules: list["ActionRule"]
    ) -> list[str]:
        errors: list[str] = []

        for rule in rules:
            if rule.category_name not in category_names:
                errors.append(
                    f"ActionRule.category_name '{rule.category_name}' must reference an existing category name: {sorted(category_names)}"
                )
            if rule.action_name not in action_names:
                errors.append(
                    f"ActionRule.action_name '{rule.action_name}' must reference an existing action name: {sorted(action_names)}"
                )
            if rule.conditions is not None:
                for condition in rule.conditions:
                    if condition.action_name not in action_names:
                        errors.append(
                            f"Condition.action_name '{condition.action_name}' must reference an existing action name: {sorted(action_names)}"
                        )

        return errors

    @classmethod
    def _validate_prompt_keys(
        cls, prompts: "StringTriagePrompts | FileTriagePrompts | LangfuseTriagePrompts"
    ) -> list[str]:
        missing_prompt_keys = sorted(cls._required_prompt_keys - set(prompts.prompt_map))
        if not missing_prompt_keys:
            return []

        return [
            f"Prompts of type '{prompts.type}' are missing required keys: {missing_prompt_keys}. Expected keys: {sorted(cls._required_prompt_keys)}"
        ]

    @model_validator(mode="after")
    def validate_configuration_integrity(self) -> "TriageSettings":
        """Validate cross-field consistency for categories, actions, rules, and prompts."""
        errors: list[str] = []

        # Validate that there is at least one category and one action, and that their names are unique
        if not self.categories:
            errors.append("At least one category must be provided")
        else:
            category_names, duplicate_category_names = self._collect_named_items(self.categories)
            if duplicate_category_names:
                errors.append(f"Category names must be unique. Duplicates found: {duplicate_category_names}")

        if not self.actions:
            errors.append("At least one action must be provided")
        else:
            action_names, duplicate_action_names = self._collect_named_items(self.actions)
            if duplicate_action_names:
                errors.append(f"Action names must be unique. Duplicates found: {duplicate_action_names}")

        category_names = {category.name for category in self.categories}
        action_names = {action.name for action in self.actions}

        # Validate that no_category_name and no_action_name reference existing category and action names
        if self.no_category_name not in category_names:
            errors.append(
                f"no_category_name '{self.no_category_name}' must reference one of the configured categories: {sorted(category_names)}"
            )

        if self.no_action_name not in action_names:
            errors.append(
                f"no_action_name '{self.no_action_name}' must reference one of the configured actions: {sorted(action_names)}"
            )

        # Validate that action rules reference existing category and action names, and that any conditions within the rules also reference existing action names
        errors.extend(
            self._validate_references(category_names=category_names, action_names=action_names, rules=self.action_rules)
        )

        # Validate that all StaticAnswer actions have a non-empty answer configured
        for action in self.actions:
            if action.type == ActionTypes.StaticAnswer and (action.answer is None or not action.answer.strip()):
                errors.append(f"Action '{action.name}' has type StaticAnswer but answer is None or empty")

        # Validate that prompts are properly configured based on their type
        errors.extend(self._validate_prompt_keys(self.prompts))

        if errors:
            raise ValueError("Invalid triage configuration:\n- " + "\n- ".join(errors))

        return self


class Category(BaseModel):
    """A triage category with a display name and identifier."""

    name: str
    auto_publish: bool = False


class ActionTypes(str, Enum):
    """Supported action execution types for triage outcomes."""

    AIAnswer = "AIAnswer"
    NoAction = "NoAction"
    StaticAnswer = "StaticAnswer"


class Action(BaseModel):
    """Action metadata associated with a triage result."""

    name: str
    description: str
    type: ActionTypes
    answer: str | None = None


class ActionRule(BaseModel):
    """Map a category to a default action with optional conditional overrides."""

    category_name: str
    action_name: str
    conditions: list["Condition"] | None = None


ConditionOperator = Literal["equals", "not_equals", "less", "less_equals", "greater", "greater_equals"]
ConditionField = Literal["processing_id", "days_since_request"]


class Condition(BaseModel):
    """Condition used to select a triage action."""

    priority: int
    field: "ConditionField"
    operator: "ConditionOperator"
    value: str | bool | int
    action_name: str


class ProcessingState(BaseModel):
    """Stored state used while evaluating processing-id rules."""

    operator: str
    datetime: str


TriagePrompt = Literal["categories", "examples", "role"]


class StringTriagePrompts(BaseModel):
    """Triage prompt templates provided as raw strings."""

    type: Literal["string"] = "string"
    prompt_map: dict[TriagePrompt, str] = Field(
        description="Prompts for the triage process as raw strings. The keys should be 'categories', 'examples', and 'role'.",
        default={
            "categories": "List of categories: {{categories}}",
            "examples": "Examples: {{examples}}",
            "role": "You are a helpful assistant that categorizes support requests into the above categories based on the content of the request.",
        },
    )


class FileTriagePrompts(BaseModel):
    """Triage prompt templates loaded from files."""

    type: Literal["file"] = "file"
    prompt_map: dict[TriagePrompt, FilePath] = Field(
        description="Prompts for the triage process as file paths. The files should contain the prompts as raw text. The keys should be 'categories', 'examples', and 'role'.",
    )


class LangfuseTriagePrompts(BaseModel):
    """Triage prompt references loaded from Langfuse."""

    type: Literal["langfuse"] = "langfuse"
    prompt_map: dict[TriagePrompt, "LangfusePrompt"] = Field(
        description="Prompts for the triage process as LangfusePrompt objects. The keys should be 'categories', 'examples', and 'role'.",
    )


class LangfusePrompt(BaseModel):
    """Reference to a Langfuse prompt by name and label."""

    label: str = Field(
        description="Label of the prompt in Langfuse",
        default="production",
    )
    name: str = Field(
        description="Name of the prompt in Langfuse",
        examples=["use_case/triage/prompt_name"],
    )
