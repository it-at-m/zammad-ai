"""Frontend integration package for the optional Gradio UI."""

from .integration import mount_frontend
from .ui import EXAMPLE_PAYLOADS, FrontendResult, build_frontend, process_ticket

__all__: list[str] = [
    "EXAMPLE_PAYLOADS",
    "FrontendResult",
    "build_frontend",
    "mount_frontend",
    "process_ticket",
]
