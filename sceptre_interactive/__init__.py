"""
Sceptre Interactive Plugin

Live, docker-pull style progress display for Sceptre stack operations.
"""

from importlib.metadata import PackageNotFoundError, version

from sceptre_interactive.cli import register
from sceptre_interactive.session import InteractiveSession

try:
    __version__ = version("sceptre-interactive-plugin")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"

__all__ = ["register", "InteractiveSession"]
