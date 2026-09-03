"""Tests for the genai provider helpers.

These tests create fake langchain provider modules and ensure the
helper `get_chat_model` constructs the expected chat model objects
and passes through configuration like reasoning effort.
"""

from __future__ import annotations

import importlib
import sys
import types

from app.settings.genai import GenAIAnthropicSettings, GenAIOpenAISettings, ThinkingConfig


def _make_fake_module(name: str, class_name: str):
    m = types.ModuleType(name)

    class FakeChat:
        def __init__(self, *args, **kwargs):
            # record construction args for assertions
            self._init_args = args
            self._init_kwargs = kwargs

    setattr(m, class_name, FakeChat)
    return m


def _load_provider_with_fake_dependency(monkeypatch, module_name: str, class_name: str):
    fake_mod = _make_fake_module(module_name, class_name)
    monkeypatch.setitem(sys.modules, module_name, fake_mod)

    import app.utils.genai_provider as provider

    return importlib.reload(provider)


def test_get_chat_model_openai(monkeypatch):
    """Ensure an OpenAI chat model is constructed with expected kwargs."""
    provider = _load_provider_with_fake_dependency(monkeypatch, "langchain_openai", "ChatOpenAI")

    settings = GenAIOpenAISettings(
        chat_model="gpt-test",
        answer_reasoning_effort="medium",
        http_socket_options=[{"family": 0}],
        use_responses_api=True,
    )

    model = provider.get_chat_model(settings, "answer")
    assert model._init_kwargs["model"] == "gpt-test"
    assert model._init_kwargs["reasoning_effort"] == "medium"
    assert model._init_kwargs["http_socket_options"] == [{"family": 0}]
    assert model._init_kwargs["use_responses_api"] is True

    sys.modules.pop("app.utils.genai_provider", None)


def test_get_chat_model_anthropic(monkeypatch):
    """Ensure an Anthropic chat model is constructed and reasoning maps to kwargs."""
    provider = _load_provider_with_fake_dependency(monkeypatch, "langchain_anthropic", "ChatAnthropic")

    settings_with_reasoning = GenAIAnthropicSettings(
        chat_model="claude-test",
        answer_thinking=ThinkingConfig(budget_tokens=1024),
        answer_effort="high",
    )
    model = provider.get_chat_model(settings_with_reasoning, "answer")

    assert model._init_kwargs["model_name"] == "claude-test"
    assert model._init_kwargs["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    assert model._init_kwargs["effort"] == "high"

    sys.modules.pop("app.utils.genai_provider", None)
