"""Tests for the genai provider helpers.

These tests create fake langchain provider modules and ensure the
helper `get_chat_model` constructs the expected chat model objects
and passes through configuration like reasoning effort.
"""

import sys
import types

from app.settings.genai import GenAIAnthropicSettings, GenAIOpenAISettings


def _make_fake_module(name: str, class_name: str):
    m = types.ModuleType(name)

    class FakeChat:
        def __init__(self, *args, **kwargs):
            # record construction args for assertions
            self._init_args = args
            self._init_kwargs = kwargs

    setattr(m, class_name, FakeChat)
    return m


def test_get_chat_model_openai(monkeypatch):
    """Ensure an OpenAI chat model is constructed with expected kwargs."""
    # Provide fake langchain_openai module with ChatOpenAI
    fake_mod = _make_fake_module("langchain_openai", "ChatOpenAI")
    sys.modules["langchain_openai"] = fake_mod

    settings = GenAIOpenAISettings(chat_model="gpt-test")

    from app.utils.genai_provider import get_chat_model

    model = get_chat_model(settings, "answer")
    assert hasattr(model, "_init_kwargs")


def test_get_chat_model_anthropic(monkeypatch):
    """Ensure an Anthropic chat model is constructed and reasoning maps to kwargs."""
    # Provide fake langchain_anthropic module with ChatAnthropic
    fake_mod = _make_fake_module("langchain_anthropic", "ChatAnthropic")
    sys.modules["langchain_anthropic"] = fake_mod

    # (leave out the unused base settings variable)

    from app.utils.genai_provider import get_chat_model

    # Also test that reasoning mapping results in kwargs when configured
    settings_with_reasoning = GenAIAnthropicSettings(chat_model="claude-test")
    model = get_chat_model(settings_with_reasoning, "answer")
    # Our fake ChatAnthropic stores init kwargs on the instance
    assert hasattr(model, "_init_kwargs")
    # Ensure model was constructed with thinking/effort when reasoning provided
    assert ("thinking" in model._init_kwargs) or ("effort" in model._init_kwargs)
