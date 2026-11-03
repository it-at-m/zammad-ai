"""Static guards against circular imports between settings and service packages."""

import ast
from pathlib import Path

SETTINGS_DIRECTORY = Path(__file__).parents[1] / "app" / "settings"
SETTINGS_PACKAGE = "app.settings"

ALLOWED_APP_PACKAGES = {
    "app.errors",
    "app.models",
    "app.settings",
    "app.utils",
}


def _top_level_package(module: str) -> str:
    """Return the second-level package of a dotted module path."""
    return ".".join(module.split(".")[:2])


def _resolve_import_base(node: ast.ImportFrom) -> str | None:
    """Resolve the base module of a from-import, including relative imports."""
    if node.level == 0:
        return node.module

    base_parts = SETTINGS_PACKAGE.split(".")
    drop = node.level - 1
    if drop >= len(base_parts):
        return None
    base = ".".join(base_parts[: len(base_parts) - drop])
    if node.module:
        base = f"{base}.{node.module}"
    return base


def test_settings_modules_only_import_leaf_app_packages() -> None:
    """Settings must not import service packages like app.answer.

    Instantiating ZammadAISettings runs model validators that may import helper
    modules. If such a validator imports a service package (for example
    app.answer), the import chain re-enters app.observe through getLogger and
    breaks while app.observe is still partially initialized.
    """
    offenders: list[str] = []

    for path in sorted(SETTINGS_DIRECTORY.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_import_base(node)
                if base is None:
                    continue
                imported_modules = [base, *(f"{base}.{alias.name}" for alias in node.names)]
            else:
                continue

            for module in imported_modules:
                root = _top_level_package(module)
                if root.startswith("app.") and root not in ALLOWED_APP_PACKAGES:
                    offenders.append(f"{path.name}: {module}")

    assert not offenders, f"Forbidden imports in app/settings: {offenders}"
