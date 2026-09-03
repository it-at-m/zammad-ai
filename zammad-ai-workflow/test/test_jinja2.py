"""Tests for Jinja2 prompt templating integration."""

from pathlib import Path

import pytest

from app.settings.templates import (
    AnswerTemplateContext,
    JudgeTemplateContext,
    ToolDefinition,
)
from app.utils.context_builders import (
    build_answer_context,
    build_judge_context,
    merge_contexts,
)
from app.utils.jinja2 import PromptTemplateRenderer, get_template_renderer


class TestPromptTemplateRenderer:
    """Tests for the PromptTemplateRenderer class."""

    def test_render_simple_template(self):
        """Test rendering a simple template with variable substitution."""
        renderer = PromptTemplateRenderer()
        template = "Hello {{ name }}!"
        context = {"name": "World"}
        result = renderer.render_template(template, context)
        assert result == "Hello World!"

    def test_render_template_with_multiple_variables(self):
        """Test rendering a template with multiple variables."""
        renderer = PromptTemplateRenderer()
        template = "{{ greeting }} {{ name }} from {{ city }}!"
        context = {"greeting": "Hello", "name": "Alice", "city": "Berlin"}
        result = renderer.render_template(template, context)
        assert result == "Hello Alice from Berlin!"

    def test_render_template_with_conditional(self):
        """Test rendering a template with conditional blocks."""
        renderer = PromptTemplateRenderer()
        template = "{% if enabled %}Enabled{% else %}Disabled{% endif %}"

        # Test with True
        result = renderer.render_template(template, {"enabled": True})
        assert result == "Enabled"

        # Test with False
        result = renderer.render_template(template, {"enabled": False})
        assert result == "Disabled"

    def test_render_template_with_loop(self):
        """Test rendering a template with for loops."""
        renderer = PromptTemplateRenderer()
        template = "Tools: {% for tool in tools %}{{ tool }}{% if not loop.last %}, {% endif %}{% endfor %}"
        context = {"tools": ["search", "kb", "dlf"]}
        result = renderer.render_template(template, context)
        assert result == "Tools: search, kb, dlf"

    def test_render_template_with_filters(self):
        """Test rendering a template with Jinja2 filters."""
        renderer = PromptTemplateRenderer()
        template = "{{ text|upper }}"
        context = {"text": "hello"}
        result = renderer.render_template(template, context)
        assert result == "HELLO"

    def test_render_template_with_length_filter(self):
        """Test rendering a template with length filter."""
        renderer = PromptTemplateRenderer()
        template = "There are {{ items|length }} items"
        context = {"items": [1, 2, 3]}
        result = renderer.render_template(template, context)
        assert result == "There are 3 items"

    def test_render_non_template(self):
        """Test that non-Jinja2 content is returned unchanged."""
        renderer = PromptTemplateRenderer()
        content = "This is just plain text without any Jinja2 syntax."
        result = renderer.render_template(content, {})
        assert result == content

    def test_extract_variables(self):
        """Test extracting variables from a template."""
        renderer = PromptTemplateRenderer()
        template = "Hello {{ name }} from {{ city }}!"
        variables = renderer.extract_variables(template)
        assert variables == {"name", "city"}

    def test_extract_variables_empty(self):
        """Test extracting variables from non-template content."""
        renderer = PromptTemplateRenderer()
        content = "Plain text without variables"
        variables = renderer.extract_variables(content)
        assert variables == set()

    def test_validate_template(self):
        """Test template validation - checks if template defines required variables."""
        renderer = PromptTemplateRenderer()
        template = "Hello {{ name }}!"

        # Template has "name" variable, so if we require "name", it's valid
        is_valid, missing = renderer.validate_template(template, {"name"})
        assert is_valid is True
        assert missing == set()

        # Template has "name" but not "city", so requiring "city" means it's missing
        is_valid, missing = renderer.validate_template(template, {"city"})
        assert is_valid is False
        assert "city" in missing  # "city" is required but not in template

    def test_get_template_renderer_singleton(self):
        """Test that get_template_renderer returns a singleton."""
        renderer1 = get_template_renderer()
        renderer2 = get_template_renderer()
        assert renderer1 is renderer2

    def test_get_template_renderer_custom_dirs(self):
        """Test that get_template_renderer with custom dirs creates a new instance."""
        renderer1 = get_template_renderer()
        renderer2 = get_template_renderer([Path("custom/templates")])
        assert renderer1 is not renderer2

    def test_render_template_file(self):
        """Test rendering a template from a file."""
        renderer = PromptTemplateRenderer([Path("prompts")])
        # This will use the existing prompts directory
        # We need to create a simple test template
        test_prompt = Path("prompts/test_jinja2_template.md")
        test_prompt.parent.mkdir(parents=True, exist_ok=True)
        test_prompt.write_text("Test: {{ value }}")
        try:
            result = renderer.render_template_file("test_jinja2_template.md", {"value": "success"})
            assert "Test: success" in result
        finally:
            test_prompt.unlink()


class TestContextBuilders:
    """Tests for context builder utilities."""

    def test_build_answer_context_empty(self):
        """Test building answer context with empty settings."""
        from app.settings.answer import AnswerSettings

        settings = AnswerSettings()
        context = build_answer_context(settings)

        assert "available_tools" in context
        assert "knowledge_base_enabled" in context
        assert "dlf_enabled" in context

    def test_build_judge_context_empty(self, settings_factory):
        """Test building judge context with default settings."""
        settings = settings_factory()
        context = build_judge_context(settings)

        assert "repair_enabled" in context
        assert "max_repairs" in context

    def test_merge_contexts(self):
        """Test merging two context dictionaries."""
        base = {"a": 1, "b": 2}
        overrides = {"b": 3, "c": 4}
        result = merge_contexts(base, overrides)

        assert result["a"] == 1
        assert result["b"] == 3  # Overridden
        assert result["c"] == 4


class TestSettingsModels:
    """Tests for Jinja2-related settings models."""

    def test_tool_definition(self):
        """Test ToolDefinition creation."""
        tool = ToolDefinition(name="search_website", description="Search public-facing website documentation")
        assert tool.name == "search_website"
        assert tool.description == "Search public-facing website documentation"

    def test_answer_template_context(self):
        """Test AnswerTemplateContext creation."""
        tools = [ToolDefinition(name="search", description="Search tool")]
        context = AnswerTemplateContext(
            available_tools=tools,
            knowledge_base_enabled=True,
            dlf_enabled=False,
            retrieval_num_documents=5,
        )
        assert context.knowledge_base_enabled is True
        assert context.dlf_enabled is False
        assert len(context.available_tools) == 1

    def test_judge_template_context(self):
        """Test JudgeTemplateContext creation."""
        context = JudgeTemplateContext(
            repair_enabled=True,
            max_repairs=3,
        )
        assert context.repair_enabled is True
        assert context.max_repairs == 3


class TestIntegration:
    """Integration tests for Jinja2 with existing workflows."""

    @pytest.mark.asyncio
    async def test_triage_prompt_rendering(self):
        """Test that triage prompts are properly rendered with Jinja2."""
        from app.utils.paths import get_prompts_dir

        prompts_dir = get_prompts_dir()
        renderer = PromptTemplateRenderer([prompts_dir])

        # Load and render the triage prompt
        from app.utils.prompts import load_prompt

        template = load_prompt(prompts_dir / "triage" / "triage.prompt.md")

        # Check that it has Jinja2 syntax
        assert "{% if" in template or "{{ " in template

        # Build context manually for test (ZammadAISettings requires full config)
        context = {
            "knowledge_base_enabled": False,
            "dlf_enabled": False,
            "no_category_name": "Cannot Categorize",
            "no_action_name": "no_action",
            "categories": [{"name": "Test Category", "auto_publish": True}],
            "repair_enabled": False,
            "max_repairs": 0,
        }

        result = renderer.render_template(template, context)

        # Verify rendering worked
        assert "Cannot Categorize" in result
        assert "Test Category" in result

    @pytest.mark.asyncio
    async def test_answer_prompt_rendering(self):
        """Test that answer prompts are properly rendered with Jinja2."""
        from app.utils.paths import get_prompts_dir

        prompts_dir = get_prompts_dir()
        renderer = PromptTemplateRenderer([prompts_dir])

        # Load and render the agent prompt
        from app.utils.prompts import load_prompt

        template = load_prompt(prompts_dir / "answer" / "agent.prompt.md")

        # Check that it has Jinja2 syntax
        assert "{% for" in template or "{{ " in template

        # Render with test context
        context = {
            "available_tools": [{"name": "search_website", "description": "Search tool"}],
            "knowledge_base_enabled": True,
            "dlf_enabled": False,
        }
        result = renderer.render_template(template, context)

        # Verify rendering worked
        assert "search_website" in result
        assert "Search tool" in result

    def test_judge_prompt_rendering(self):
        """Test that judge prompts are properly rendered with Jinja2."""
        from app.utils.paths import get_prompts_dir

        prompts_dir = get_prompts_dir()
        renderer = PromptTemplateRenderer([prompts_dir])

        # Load and render the judge prompt
        from app.utils.prompts import load_prompt

        template = load_prompt(prompts_dir / "judge" / "judge.prompt.md")

        # Check that it has Jinja2 syntax
        assert "{{ repair_enabled" in template or "{% if" in template

        # Render with test context
        context = {
            "repair_enabled": True,
            "max_repairs": 3,
        }
        result = renderer.render_template(template, context)

        # Verify rendering worked
        assert "Repair is enabled" in result
