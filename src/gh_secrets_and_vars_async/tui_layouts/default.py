"""Default layout -- clean panels in a responsive grid."""

from __future__ import annotations

from datetime import UTC, datetime

from rich import box
from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from ..tui_dashboard import RepoStatus
from . import register

STATUS_ICON = {
    "success": "[green]\u25cf[/green]",
    "failure": "[red]\u25cf[/red]",
    "in_progress": "[yellow]\u25cf[/yellow]",
    "unknown": "[dim]\u25cf[/dim]",
}


class DefaultLayout:
    name = "default"
    description = "Clean panels in a responsive grid"

    def _border_style(self, status: RepoStatus) -> str:
        if status.main_status == "failure" or status.dev_status == "failure":
            return "red"
        if status.open_prs > 0:
            return "yellow"
        return "green"

    def build_repo_panel(self, status: RepoStatus) -> RenderableType:
        lines = Text()

        if status.is_service and status.dev_status is not None:
            lines.append("dev: ")
            lines.append_text(Text.from_markup(STATUS_ICON[status.dev_status]))
            lines.append("  main: ")
            lines.append_text(Text.from_markup(STATUS_ICON[status.main_status]))
        else:
            lines.append("main: ")
            lines.append_text(Text.from_markup(STATUS_ICON[status.main_status]))

        for error in (status.dev_error, status.main_error):
            if error:
                lines.append("\n")
                truncated = error if len(error) <= 40 else error[:37] + "..."
                lines.append_text(Text.from_markup(f"[red]> {truncated}[/red]"))

        lines.append("\n")
        pr_label = f"PRs: {status.open_prs}"
        if status.draft_prs:
            pr_label += f" ({status.draft_prs})"
        lines.append(f"Issues: {status.open_issues}  {pr_label}")

        return Panel(
            lines,
            title=f"[bold]{status.name}[/bold]",
            width=46,
            padding=(0, 1),
            border_style=self._border_style(status),
            box=box.ROUNDED,
        )

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
        panels = [self.build_repo_panel(s) for s in statuses]
        columns = Columns(panels, padding=(1, 1), expand=False)
        footer = Text.from_markup("[dim]Press Ctrl+C to exit[/dim]")
        return Group(header, Text(), columns, Text(), footer)


register(DefaultLayout())
