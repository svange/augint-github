"""Pluggable layout system for the TUI dashboard.

Each layout is a subclass of :class:`Layout` registered via :func:`register`.
The CLI exposes them through ``--layout <name>``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from rich.console import RenderableType

    from ..tui_dashboard import RepoStatus

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Layout(Protocol):
    """Interface every dashboard layout must satisfy."""

    name: str
    description: str

    def build_repo_panel(self, status: RepoStatus) -> RenderableType: ...

    def build_dashboard(
        self,
        statuses: list[RepoStatus],
        refresh_seconds: int,
        *,
        from_cache: bool = False,
    ) -> RenderableType: ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_LAYOUTS: dict[str, Layout] = {}


def register(layout: Layout) -> Layout:
    """Register a layout instance so the CLI can find it by name."""
    _LAYOUTS[layout.name] = layout
    return layout


def get_layout(name: str) -> Layout:
    """Return a registered layout by name, or raise ``KeyError``."""
    _ensure_builtins()
    return _LAYOUTS[name]


def available_layouts() -> list[str]:
    """Return the names of all registered layouts."""
    _ensure_builtins()
    return sorted(_LAYOUTS)


# Lazy-load built-in layouts on first access so the import cost is zero
# when layouts aren't needed (e.g. unit tests that only test data fetching).
_LOADED = False


def _ensure_builtins() -> None:
    global _LOADED  # noqa: PLW0603
    if _LOADED:
        return
    _LOADED = True
    # Importing the modules triggers their top-level ``register()`` calls.
    from . import compact, cyber, default  # noqa: F401
