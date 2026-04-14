"""Compact layout -- dense single-line-per-repo table."""

from __future__ import annotations

from datetime import UTC, datetime

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..tui_dashboard import RepoStatus
from . import register

_DOT = {
    "success": "[green]\u25cf[/green]",
    "failure": "[red]\u25cf[/red]",
    "in_progress": "[yellow]\u25cf[/yellow]",
    "unknown": "[dim]\u25cf[/dim]",
}


class CompactLayout:
    name = "compact"
    description = "Dense table, one row per repo"

    def build_repo_panel(self, status: RepoStatus) -> RenderableType:
        # Not used directly, but satisfies the protocol for symmetry.
        return Text(status.name)

    def build_dashboard(
        self,
        statuses: list[RepoStatus],
        refresh_seconds: int,
        *,
        from_cache: bool = False,
    ) -> RenderableType:
        now = datetime.now(UTC).strftime("%H:%M:%S UTC")
        cache_tag = "  [dim](cached)[/dim]" if from_cache else ""
        header = Text.from_markup(
            f"[bold]ai-gh dashboard[/bold]  |  {now}  |  refresh: {refresh_seconds}s{cache_tag}"
        )

        table = Table(
            box=box.SIMPLE_HEAVY,
            show_edge=False,
            pad_edge=False,
            expand=False,
        )
        table.add_column("Repo", style="bold", min_width=20)
        table.add_column("main", justify="center", width=6)
        table.add_column("dev", justify="center", width=6)
        table.add_column("Issues", justify="right", width=6)
        table.add_column("PRs", justify="right", width=10)

        for s in statuses:
            main_dot = Text.from_markup(_DOT[s.main_status])
            dev_dot = Text.from_markup(_DOT[s.dev_status]) if s.dev_status else Text("-")
            pr_text = str(s.open_prs)
            if s.draft_prs:
                pr_text += f" ({s.draft_prs})"

            row_style = ""
            if s.main_status == "failure" or s.dev_status == "failure":
                row_style = "on #1a0000"

            table.add_row(
                s.name,
                main_dot,
                dev_dot,
                str(s.open_issues),
                pr_text,
                style=row_style,
            )

        body = Panel(
            table,
            border_style="dim",
            box=box.ROUNDED,
            padding=(0, 1),
        )
        footer = Text.from_markup("[dim]Press Ctrl+C to exit[/dim]")
        return Group(header, Text(), body, Text(), footer)


register(CompactLayout())
