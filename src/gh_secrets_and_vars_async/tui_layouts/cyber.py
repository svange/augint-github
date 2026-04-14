"""Cyber layout -- neon-on-dark aesthetic with heavy borders."""

from __future__ import annotations

from datetime import UTC, datetime

from rich import box
from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from ..tui_dashboard import RepoStatus
from . import register

# Neon palette
_CYAN = "#00ffff"
_MAGENTA = "#ff00ff"
_GREEN = "#39ff14"
_RED = "#ff3131"
_YELLOW = "#ffff00"
_DIM = "#555555"
_BG = "#0a0a1a"
_PANEL_BG = "#0d0d24"
_FAIL_BG = "#1a0008"

_DOT = {
    "success": f"[{_GREEN}]\u25c9[/{_GREEN}]",
    "failure": f"[{_RED}]\u25c9[/{_RED}]",
    "in_progress": f"[{_YELLOW}]\u25c9[/{_YELLOW}]",
    "unknown": f"[{_DIM}]\u25cb[/{_DIM}]",
}

_LABEL_STYLE = f"bold {_CYAN}"
_ACCENT = _MAGENTA


class CyberLayout:
    name = "cyber"
    description = "Neon-on-dark with heavy borders"

    def _border_style(self, status: RepoStatus) -> Style:
        if status.main_status == "failure" or status.dev_status == "failure":
            return Style(color=_RED, bold=True)
        if status.main_status == "in_progress" or status.dev_status == "in_progress":
            return Style(color=_YELLOW)
        return Style(color=_CYAN)

    def _panel_bg(self, status: RepoStatus) -> Style:
        if status.main_status == "failure" or status.dev_status == "failure":
            return Style(bgcolor=_FAIL_BG)
        return Style(bgcolor=_PANEL_BG)

    def build_repo_panel(self, status: RepoStatus) -> RenderableType:
        lines = Text()

        if status.is_service and status.dev_status is not None:
            lines.append_text(Text.from_markup(f"[{_DIM}]dev [/{_DIM}]"))
            lines.append_text(Text.from_markup(_DOT[status.dev_status]))
            lines.append("  ")
            lines.append_text(Text.from_markup(f"[{_DIM}]main [/{_DIM}]"))
            lines.append_text(Text.from_markup(_DOT[status.main_status]))
        else:
            lines.append_text(Text.from_markup(f"[{_DIM}]main [/{_DIM}]"))
            lines.append_text(Text.from_markup(_DOT[status.main_status]))

        for error in (status.dev_error, status.main_error):
            if error:
                lines.append("\n")
                truncated = error if len(error) <= 36 else error[:33] + "..."
                lines.append_text(Text.from_markup(f"[{_RED}]>> {truncated}[/{_RED}]"))

        lines.append("\n")
        lines.append_text(
            Text.from_markup(
                f"[{_DIM}]iss [/{_DIM}][{_ACCENT}]{status.open_issues}[/{_ACCENT}]"
                f"  [{_DIM}]pr [/{_DIM}][{_ACCENT}]{status.open_prs}[/{_ACCENT}]"
            )
        )
        if status.draft_prs:
            lines.append_text(Text.from_markup(f"[{_DIM}] ({status.draft_prs})[/{_DIM}]"))

        return Panel(
            lines,
            title=f"[{_LABEL_STYLE}] {status.name} [/{_LABEL_STYLE}]",
            title_align="left",
            width=46,
            padding=(0, 1),
            border_style=self._border_style(status),
            style=self._panel_bg(status),
            box=box.HEAVY,
        )

    def build_dashboard(
        self,
        statuses: list[RepoStatus],
        refresh_seconds: int,
        *,
        from_cache: bool = False,
    ) -> RenderableType:
        now = datetime.now(UTC).strftime("%H:%M:%S UTC")
        cache_tag = f"  [{_DIM}](cached)[/{_DIM}]" if from_cache else ""

        header = Text.from_markup(
            f"[{_LABEL_STYLE}]ai-gh[/{_LABEL_STYLE}]"
            f" [{_DIM}]|[/{_DIM}] [{_ACCENT}]{now}[/{_ACCENT}]"
            f" [{_DIM}]|[/{_DIM}] [{_DIM}]refresh {refresh_seconds}s[/{_DIM}]{cache_tag}"
        )

        panels = [self.build_repo_panel(s) for s in statuses]
        columns = Columns(panels, padding=(1, 1), expand=False)

        footer = Text.from_markup(f"[{_DIM}]ctrl+c to exit[/{_DIM}]")

        outer = Panel(
            Group(columns, Text(), footer),
            title=header,
            title_align="left",
            border_style=Style(color=_DIM),
            box=box.DOUBLE,
            style=Style(bgcolor=_BG),
            padding=(1, 2),
        )
        return Group(Text(), outer)


register(CyberLayout())
