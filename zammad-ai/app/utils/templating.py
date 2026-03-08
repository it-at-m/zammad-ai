import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape


def _to_json_filter(value: Any, **kwargs: Any) -> str:
    """Jinja filter to safely convert python dicts/objects to JSON strings."""
    return json.dumps(value, **kwargs)


def get_jinja_env(template_dir: Path | str | None = None) -> Environment:
    """
    Returns a configured Jinja2 Environment for rendering LLM prompts.
    Includes custom filters like |tojson.
    """
    if template_dir is None:
        template_dir = Path("prompts")

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["tojson"] = _to_json_filter
    return env


def render_template_string(template_str: str, **context: Any) -> str:
    """
    Render an inline string template using the shared Jinja environment.
    This is useful for Langfuse-fetched prompts that are strings instead of files.
    """
    env = get_jinja_env()
    template = env.from_string(template_str)
    return template.render(**context)
