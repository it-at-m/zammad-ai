"""Jinja2 template rendering utilities for prompt composition.

This module provides a centralized way to render Jinja2 templates for prompt
generation across the Zammad-AI application. It supports template loading from
files, string-based templates, and variable extraction for validation.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, meta

from app.utils.logging import getLogger

logger = getLogger("zammad-ai.jinja2")


class PromptTemplateRenderer:
    """Render Jinja2 templates for prompt composition.

    This class provides a centralized way to render Jinja2 templates with support
    for loading templates from files, rendering from strings, and extracting
    variable definitions from templates for validation.

    The renderer caches the Jinja2 environment and provides methods for both
    file-based and string-based template rendering.

    Attributes:
        template_dirs: List of directories to search for template files.
    """

    def __init__(self, template_dirs: list[Path] | None = None) -> None:
        """Initialize with optional template directories.

        Args:
            template_dirs: List of directories to search for templates.
                Defaults to ["prompts"] relative to the application root.
        """
        self.template_dirs = template_dirs or [Path("prompts")]
        self._env: Environment | None = None

    @property
    def environment(self) -> Environment:
        """Create and cache Jinja2 environment.

        The environment is configured with:
        - FileSystemLoader for the configured template directories
        - autoescape disabled (we handle escaping in prompts ourselves)
        - trim_blocks and lstrip_blocks enabled for cleaner output

        Returns:
            Configured Jinja2 Environment instance.
        """
        if self._env is None:
            # Create a single FileSystemLoader with all directories
            search_paths = [str(d.resolve()) for d in self.template_dirs]
            self._env = Environment(
                loader=FileSystemLoader(search_paths),
                autoescape=False,
                trim_blocks=True,
                lstrip_blocks=True,
                keep_trailing_newline=True,
            )
        return self._env

    def render_template(
        self,
        template_content: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Render a template string with the given context.

        This method takes a Jinja2 template as a string and renders it with
        the provided context variables. If the template contains no Jinja2
        syntax, it is returned unchanged for backward compatibility.

        Args:
            template_content: Jinja2 template as a string.
            context: Dictionary of variables for template rendering.
                If None, an empty dict is used.

        Returns:
            Rendered template as a string.

        Raises:
            jinja2.UndefinedError: If strict mode is enabled and an undefined
                variable is encountered.

        Example:
            >>> renderer = PromptTemplateRenderer()
            >>> template = "Hello {{ name }}!"
            >>> renderer.render_template(template, {"name": "World"})
            'Hello World!'
        """
        if context is None:
            context = {}

        # Quick check: if template has no Jinja2 syntax, return as-is
        if not self._has_jinja2_syntax(template_content):
            return template_content

        try:
            template = self.environment.from_string(template_content)
            return template.render(**context)
        except Exception:
            logger.error("Failed to render Jinja2 template.", exc_info=True)
            # In non-strict mode, we still want to return something
            # Return the template with placeholders for missing vars
            return template_content

    def render_template_file(
        self,
        template_path: Path | str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Render a template file with the given context.

        This method loads a template from a file and renders it with the
        provided context variables.

        Args:
            template_path: Path to the template file (relative or absolute).
            context: Dictionary of variables for template rendering.
                If None, an empty dict is used.

        Returns:
            Rendered template as a string.

        Raises:
            jinja2.TemplateNotFound: If the template file cannot be found.
            jinja2.UndefinedError: If strict mode is enabled and an undefined
                variable is encountered.

        Example:
            >>> renderer = PromptTemplateRenderer()
            >>> renderer.render_template_file("prompts/answer/agent.prompt.md", {})
        """
        if context is None:
            context = {}

        try:
            template = self.environment.get_template(str(template_path))
            return template.render(**context)
        except Exception:
            logger.error(f"Failed to render Jinja2 template file '{template_path}'.", exc_info=True)
            raise

    def extract_variables(self, template_content: str) -> set[str]:
        """Extract all variables used in a template.

        This method parses the template and extracts all variable names that
        are used in the template. This is useful for validating that all
        required variables are provided in the context.

        Args:
            template_content: Jinja2 template as a string.

        Returns:
            Set of variable names used in the template.

        Example:
            >>> renderer = PromptTemplateRenderer()
            >>> template = "Hello {{ name }} from {{ city }}!"
            >>> renderer.extract_variables(template)
            {'name', 'city'}
        """
        if not self._has_jinja2_syntax(template_content):
            return set()

        try:
            ast = self.environment.parse(template_content)
            variables = meta.find_undeclared_variables(ast)
            return variables
        except Exception:
            # If parsing fails, return empty set
            return set()

    def _has_jinja2_syntax(self, content: str) -> bool:
        """Check if content contains Jinja2 syntax.

        This performs a quick string check for common Jinja2 delimiters
        to avoid unnecessary parsing of non-template content.

        Args:
            content: String to check.

        Returns:
            True if content appears to contain Jinja2 syntax.
        """
        return any(delimiter in content for delimiter in ["{{", "{%", "{#"])

    def validate_template(
        self,
        template_content: str,
        required_variables: set[str],
    ) -> tuple[bool, set[str]]:
        """Validate that a template contains all required variables.

        Args:
            template_content: Jinja2 template as a string.
            required_variables: Set of variable names that must be present.

        Returns:
            Tuple of (is_valid, missing_variables) where is_valid is True if all
            required variables are present, and missing_variables is the set
            of variable names that are required but not found in the template.
        """
        template_vars = self.extract_variables(template_content)
        missing = required_variables - template_vars
        return (len(missing) == 0, missing)


# Module-level singleton for convenience
_renderer: PromptTemplateRenderer | None = None


def get_template_renderer(
    template_dirs: list[Path] | None = None,
) -> PromptTemplateRenderer:
    """Get a shared template renderer instance.

    This function returns a singleton renderer instance by default, but can
    create a new instance with custom template directories if needed.

    Args:
        template_dirs: Optional list of template directories. If provided,
            a new renderer is created with these directories. Otherwise,
            the shared singleton is returned.

    Returns:
        PromptTemplateRenderer instance.

    Example:
        >>> renderer = get_template_renderer()
        >>> custom_renderer = get_template_renderer([Path("custom/templates")])
    """
    global _renderer
    if template_dirs is not None:
        return PromptTemplateRenderer(template_dirs)
    if _renderer is None:
        _renderer = PromptTemplateRenderer()
    return _renderer
