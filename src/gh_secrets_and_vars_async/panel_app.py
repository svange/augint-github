"""Textual interactive health dashboard application."""

from __future__ import annotations

import hashlib
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING

from rich import box
from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import Hit, Hits, Provider
from textual.containers import Container, Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Header, Static

from .health import FetchContext, RepoHealth, Severity, run_health_checks
from .panel_themes import THEME_NAMES, THEMES, DashboardThemeSpec, get_theme_spec
from .panel_usage import UsageStats, fetch_all_usage
from .tui_dashboard import (
    RepoStatus,
    fetch_repo_status,
    load_cache,
    load_health_cache,
    save_cache,
)

if TYPE_CHECKING:
    from github.Repository import Repository

    from gh_secrets_and_vars_async.health._models import HealthCheckResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEVERITY_ICON = {
    Severity.CRITICAL: Text("●", style="bold red"),
    Severity.HIGH: Text("●", style="bold #ff8800"),
    Severity.MEDIUM: Text("●", style="yellow"),
    Severity.LOW: Text("●", style="dim cyan"),
    Severity.OK: Text("●", style="green"),
}

_PANEL_WIDTH = 38
_PANEL_MIN_WIDTH = 24
_PANEL_MAX_WIDTH = 60
_PANEL_WIDTH_STEP = 2
_PANEL_GAP = 1
_PANEL_ROW_GAP = 1
_GRID_PADDING = (_PANEL_ROW_GAP, _PANEL_GAP)
_TEAM_FILTER_PREFIX = "team:"
_UNASSIGNED_TEAM = "unassigned"
_TEAM_PERMISSION_ORDER = {"admin": 0, "maintain": 1, "push": 2, "triage": 3, "pull": 4}
_TEAM_ACCENTS = [
    "#6ea8ff",
    "#78dba9",
    "#f7b267",
    "#d387ff",
    "#7ad3f7",
    "#ff8fab",
    "#c3e88d",
    "#ffcb6b",
]
_STATUS_BADGES = {
    "success": (" PASS ", "bold #101010 on #72f1b8"),
    "failure": (" FAIL ", "bold white on #ff3355"),
    "in_progress": (" RUN ", "bold #101010 on #ffd84d"),
    "unknown": (" ? ", "bold #101010 on #b8bcc8"),
}
_MOUSE_BUTTON_LEFT = 1
_MOUSE_BUTTON_MIDDLE = 2
_MOUSE_BUTTON_RIGHT = 3

SORT_MODES = ["health", "alpha", "problem"]
FILTER_MODES = ["all", "broken-ci", "no-renovate", "stale-prs", "issues"]
LAYOUT_MODES = ["packed", "grouped"]


@dataclass(frozen=True)
class RepoTeamInfo:
    """Primary and secondary GitHub team ownership for a repository."""

    primary: str = _UNASSIGNED_TEAM
    all: tuple[str, ...] = ()


@dataclass(frozen=True)
class TeamTint:
    """Visual tint used to mark team ownership."""

    accent: str
    background: str


@dataclass(frozen=True)
class RepoCardRegion:
    """Screen-space hitbox for a rendered repo card inside the rich grid."""

    full_name: str
    x: int
    y: int
    width: int
    height: int


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _truncate(value: str | None, width: int) -> str:
    if not value:
        return ""
    if len(value) <= width:
        return value
    return value[: max(0, width - 3)] + "..."


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    red, green, blue = rgb
    return f"#{red:02x}{green:02x}{blue:02x}"


def _blend_hex(base: str, accent: str, ratio: float) -> str:
    base_rgb = _hex_to_rgb(base)
    accent_rgb = _hex_to_rgb(accent)
    mixed_channels = [
        round((1 - ratio) * base_channel + ratio * accent_channel)
        for base_channel, accent_channel in zip(base_rgb, accent_rgb, strict=True)
    ]
    mixed = (mixed_channels[0], mixed_channels[1], mixed_channels[2])
    return _rgb_to_hex(mixed)


def _status_badge(status: str | None) -> Text:
    label, style = _STATUS_BADGES.get(status or "unknown", _STATUS_BADGES["unknown"])
    return Text(label, style=style)


def _severity_style(severity: Severity) -> str:
    if severity == Severity.CRITICAL:
        return "bold red"
    if severity == Severity.HIGH:
        return "bold #ff8800"
    if severity == Severity.MEDIUM:
        return "yellow"
    if severity == Severity.LOW:
        return "dim cyan"
    return "green"


def _lookup_check(health: RepoHealth, check_name: str) -> HealthCheckResult | None:
    return next((check for check in health.checks if check.check_name == check_name), None)


def _team_filter_mode(team_key: str) -> str:
    return f"{_TEAM_FILTER_PREFIX}{team_key}"


def _team_key_from_filter(mode: str) -> str | None:
    if mode.startswith(_TEAM_FILTER_PREFIX):
        return mode.removeprefix(_TEAM_FILTER_PREFIX)
    return None


def _display_team_label(team_key: str, team_labels: dict[str, str]) -> str:
    if team_key == _UNASSIGNED_TEAM:
        return "Unassigned"
    return team_labels.get(team_key, team_key.replace("-", " ").title())


def _format_filter_label(mode: str, team_labels: dict[str, str]) -> str:
    team_key = _team_key_from_filter(mode)
    if team_key is None:
        return mode
    return f"team:{_display_team_label(team_key, team_labels)}"


def _team_sort_key(team) -> tuple[int, str]:
    permission = getattr(team, "permission", "") or ""
    slug = getattr(team, "slug", "") or getattr(team, "name", "") or ""
    return _TEAM_PERMISSION_ORDER.get(permission, 99), slug.lower()


def _repo_team_info(
    repo_name: str,
    repo_teams: dict[str, RepoTeamInfo],
) -> RepoTeamInfo:
    return repo_teams.get(repo_name, RepoTeamInfo())


def _team_tint(team_key: str, theme_spec: DashboardThemeSpec) -> TeamTint:
    if team_key == _UNASSIGNED_TEAM:
        return TeamTint(accent=theme_spec.dim_text, background=theme_spec.card_background)

    digest = hashlib.sha1(team_key.encode("utf-8")).digest()
    accent = _TEAM_ACCENTS[int.from_bytes(digest[:2], "big") % len(_TEAM_ACCENTS)]
    return TeamTint(accent=accent, background=theme_spec.card_background)


def _team_badge(label: str, tint: TeamTint, *, extra_count: int = 0) -> Text:
    short_label = label
    if len(short_label) > 12:
        short_label = short_label[:9] + "..."
    if extra_count > 0:
        short_label += f"+{extra_count}"
    return Text(f" {short_label} ", style=f"bold #101010 on {tint.accent}")


def _team_summary_label(info: RepoTeamInfo, team_labels: dict[str, str]) -> tuple[str, int]:
    label = _display_team_label(info.primary, team_labels)
    extra_count = max(0, len(info.all) - 1)
    return label, extra_count


def _group_team_key(
    health: RepoHealth,
    filter_mode: str,
    repo_teams: dict[str, RepoTeamInfo],
) -> str:
    info = _repo_team_info(health.status.full_name, repo_teams)
    filter_team = _team_key_from_filter(filter_mode)
    if filter_team is not None and filter_team in info.all:
        return filter_team
    return info.primary


def _grouped_healths(
    healths: list[RepoHealth],
    repo_teams: dict[str, RepoTeamInfo],
    filter_mode: str,
) -> list[tuple[str, list[RepoHealth]]]:
    grouped: dict[str, list[RepoHealth]] = {}
    for health in healths:
        team_key = _group_team_key(health, filter_mode, repo_teams)
        grouped.setdefault(team_key, []).append(health)
    return list(grouped.items())


def _layout_sections(
    healths: list[RepoHealth],
    repo_teams: dict[str, RepoTeamInfo],
    filter_mode: str,
    layout_mode: str,
) -> list[tuple[str | None, list[RepoHealth]]]:
    if layout_mode == "packed":
        return [(None, healths)]
    return [
        (team_key, team_healths)
        for team_key, team_healths in _grouped_healths(healths, repo_teams, filter_mode)
    ]


def _flatten_sections(
    sections: list[tuple[str | None, list[RepoHealth]]],
) -> list[RepoHealth]:
    return [health for _, team_healths in sections for health in team_healths]


def _available_filter_modes(
    team_labels: dict[str, str], repo_teams: dict[str, RepoTeamInfo]
) -> list[str]:
    team_keys = {team for info in repo_teams.values() for team in (info.all or (info.primary,))}
    dynamic_team_filters = [
        _team_filter_mode(team_key)
        for team_key in sorted(
            team_keys, key=lambda key: _display_team_label(key, team_labels).lower()
        )
    ]
    return [*FILTER_MODES, *dynamic_team_filters]


def _visible_healths_for(
    healths: list[RepoHealth],
    sort_mode: str,
    filter_mode: str,
    repo_teams: dict[str, RepoTeamInfo],
    layout_mode: str = LAYOUT_MODES[0],
) -> list[RepoHealth]:
    filtered = _apply_filter(healths, filter_mode, repo_teams)
    sorted_healths = _apply_sort(filtered, sort_mode)
    return _flatten_sections(_layout_sections(sorted_healths, repo_teams, filter_mode, layout_mode))


def _build_ci_line(status: RepoStatus) -> Text:
    line = Text()
    if status.is_service and status.dev_status is not None:
        line.append("dev ", style="bold")
        line.append_text(_status_badge(status.dev_status))
        line.append("  main ", style="bold")
        line.append_text(_status_badge(status.main_status))
    else:
        line.append("main ", style="bold")
        line.append_text(_status_badge(status.main_status))
    return line


def _build_counts_line(status: RepoStatus, health: RepoHealth) -> Text:
    stale_prs = _lookup_check(health, "stale_prs")
    issue_count = _lookup_check(health, "open_issues")
    pr_style = "yellow" if stale_prs and stale_prs.severity != Severity.OK else None
    issue_style = "yellow" if issue_count and issue_count.severity != Severity.OK else None

    line = Text()
    line.append("issues ", style="bold")
    line.append(str(status.open_issues), style=issue_style)
    line.append("  prs ", style="bold")
    pr_label = str(status.open_prs)
    if status.draft_prs:
        pr_label += f" ({status.draft_prs}d)"
    line.append(pr_label, style=pr_style)
    return line


def _build_renovate_line(health: RepoHealth) -> Text:
    result = _lookup_check(health, "renovate_enabled")
    line = Text()
    line.append("renovate ", style="bold")
    if result is None:
        line.append("unknown", style="dim")
    elif result.severity == Severity.OK:
        line.append("enabled", style="green")
    else:
        line.append(_truncate(result.summary, 24), style=_severity_style(result.severity))
    return line


def _detail_lines(status: RepoStatus, health: RepoHealth, limit: int) -> list[Text]:
    lines: list[Text] = []

    for label, error in (("dev", status.dev_error), ("main", status.main_error)):
        if error:
            line = Text()
            line.append(f"{label}: ", style="bold")
            line.append(_truncate(error, 26), style="bold red")
            lines.append(line)
            if len(lines) >= limit:
                return lines

    for finding in health.findings:
        line = Text()
        line.append_text(_SEVERITY_ICON.get(finding.severity, _SEVERITY_ICON[Severity.OK]).copy())
        label = finding.check_name.replace("_", " ")
        line.append(f" {label}: ", style="bold")
        line.append(_truncate(finding.summary, 24), style=_severity_style(finding.severity))
        lines.append(line)
        if len(lines) >= limit:
            return lines

    while len(lines) < limit:
        placeholder = (
            Text("all checks green", style="green")
            if len(lines) == 0
            and not health.findings
            and not status.main_error
            and not status.dev_error
            else Text(" ", style="dim")
        )
        lines.append(placeholder)

    return lines


def _panel_border_style(
    health: RepoHealth,
    theme_spec: DashboardThemeSpec,
    *,
    selected: bool,
) -> str:
    status = health.status
    if status.main_status == "failure" or status.dev_status == "failure":
        return theme_spec.card_error
    if health.worst_severity == Severity.CRITICAL:
        return theme_spec.card_error
    if health.worst_severity in (Severity.HIGH, Severity.MEDIUM) or status.open_prs > 0:
        return theme_spec.card_warning
    return theme_spec.card_success


def _build_repo_panel(
    health: RepoHealth,
    theme_spec: DashboardThemeSpec,
    repo_teams: dict[str, RepoTeamInfo],
    team_labels: dict[str, str],
    *,
    selected: bool,
    panel_width: int = _PANEL_WIDTH,
) -> Panel:
    status = health.status
    team_info = _repo_team_info(status.full_name, repo_teams)
    team_label, extra_teams = _team_summary_label(team_info, team_labels)
    team_tint = _team_tint(team_info.primary, theme_spec)

    title = Text()
    if selected:
        title.append(" FOCUS ", style=f"bold #101010 on {theme_spec.card_selected}")
        title.append(" ")
    title.append(status.name, style=f"bold {theme_spec.card_text}")
    if status.is_service:
        title.append("  svc", style=theme_spec.dim_text)

    subtitle = _team_badge(team_label, team_tint, extra_count=extra_teams)

    summary = Text()
    summary.append("health ", style="bold")
    summary.append_text(
        _SEVERITY_ICON.get(health.worst_severity, _SEVERITY_ICON[Severity.OK]).copy()
    )
    summary.append(
        f" {health.worst_severity.name.lower()}",
        style=_severity_style(health.worst_severity),
    )
    summary.append(f"  score {health.score}", style=theme_spec.dim_text)

    body_lines = [
        summary,
        _build_ci_line(status),
        _build_counts_line(status, health),
        _build_renovate_line(health),
        *_detail_lines(status, health, limit=2),
    ]

    return Panel(
        Group(*body_lines),
        title=title,
        subtitle=subtitle,
        subtitle_align="right",
        box=box.ROUNDED,
        border_style=_panel_border_style(health, theme_spec, selected=selected),
        width=panel_width,
        padding=(0, 1),
        style=f"{theme_spec.card_text} on {theme_spec.card_background}",
    )


def _build_repo_grid(
    healths: list[RepoHealth],
    selected_repo: str | None,
    theme_spec: DashboardThemeSpec,
    repo_teams: dict[str, RepoTeamInfo],
    team_labels: dict[str, str],
    filter_mode: str,
    layout_mode: str = LAYOUT_MODES[0],
    panel_width: int = _PANEL_WIDTH,
) -> Panel | Columns | Group:
    if not healths:
        return Panel(
            Text("No repositories match the current filter.", style=theme_spec.dim_text),
            title=Text("Repositories", style=f"bold {theme_spec.card_text}"),
            border_style=theme_spec.card_border,
            style=f"{theme_spec.card_text} on {theme_spec.card_background}",
            box=box.ROUNDED,
        )

    sections: list = []
    grouped_sections = _layout_sections(healths, repo_teams, filter_mode, layout_mode)
    for index, (team_key, team_healths) in enumerate(grouped_sections):
        if team_key is not None:
            tint = _team_tint(team_key, theme_spec)
            header = Text()
            header.append_text(_team_badge(_display_team_label(team_key, team_labels), tint))
            header.append(f"  {len(team_healths)} repos", style=theme_spec.dim_text)
            sections.append(header)
        sections.append(
            Columns(
                [
                    _build_repo_panel(
                        health,
                        theme_spec,
                        repo_teams,
                        team_labels,
                        selected=health.status.full_name == selected_repo,
                        panel_width=panel_width,
                    )
                    for health in team_healths
                ],
                padding=_GRID_PADDING,
                expand=False,
            )
        )
        if team_key is not None and index < len(grouped_sections) - 1:
            sections.append(Text())
    return Group(*sections)


def _panel_height(panel: Panel, panel_width: int = _PANEL_WIDTH) -> int:
    console = Console(width=panel_width)
    options = console.options.update(width=panel_width)
    return len(console.render_lines(panel, options))


def _build_repo_card_regions(
    healths: list[RepoHealth],
    selected_repo: str | None,
    theme_spec: DashboardThemeSpec,
    repo_teams: dict[str, RepoTeamInfo],
    team_labels: dict[str, str],
    filter_mode: str,
    available_width: int,
    layout_mode: str = LAYOUT_MODES[0],
    panel_width: int = _PANEL_WIDTH,
) -> list[RepoCardRegion]:
    if not healths:
        return []

    column_count = max(1, available_width // (panel_width + _PANEL_GAP))
    grouped = _layout_sections(healths, repo_teams, filter_mode, layout_mode)
    regions: list[RepoCardRegion] = []
    y = 0

    for group_index, (team_key, team_healths) in enumerate(grouped):
        if team_key is not None:
            y += 1
        for row_start in range(0, len(team_healths), column_count):
            row_healths = team_healths[row_start : row_start + column_count]
            row_cards = [
                _build_repo_panel(
                    health,
                    theme_spec,
                    repo_teams,
                    team_labels,
                    selected=health.status.full_name == selected_repo,
                    panel_width=panel_width,
                )
                for health in row_healths
            ]
            row_heights = [_panel_height(p, panel_width) for p in row_cards]
            row_height = max(row_heights, default=0)
            for column_index, (health, height) in enumerate(
                zip(row_healths, row_heights, strict=True)
            ):
                regions.append(
                    RepoCardRegion(
                        full_name=health.status.full_name,
                        x=column_index * (panel_width + _PANEL_GAP),
                        y=y,
                        width=panel_width,
                        height=height,
                    )
                )
            y += row_height
            if row_start + column_count < len(team_healths):
                y += _PANEL_ROW_GAP
        if team_key is not None and group_index < len(grouped) - 1:
            y += 1

    return regions


def _repo_at_position(card_regions: list[RepoCardRegion], x: int, y: int) -> str | None:
    return next(
        (
            region.full_name
            for region in card_regions
            if region.x <= x < region.x + region.width and region.y <= y < region.y + region.height
        ),
        None,
    )


def _build_focus_panel(
    health: RepoHealth | None,
    theme_spec: DashboardThemeSpec,
    repo_teams: dict[str, RepoTeamInfo],
    team_labels: dict[str, str],
    *,
    selected_position: int,
    repo_count: int,
) -> Panel:
    if health is None:
        return Panel(
            Text("No repo selected.", style=theme_spec.dim_text),
            title=Text("Focus", style=f"bold {theme_spec.card_text}"),
            border_style=theme_spec.card_border,
            box=box.ROUNDED,
            style=f"{theme_spec.card_text} on {theme_spec.card_background}",
        )

    status = health.status
    team_info = _repo_team_info(status.full_name, repo_teams)
    team_label, extra_teams = _team_summary_label(team_info, team_labels)
    team_tint = _team_tint(team_info.primary, theme_spec)
    title = Text()
    title.append("Focus", style=f"bold {theme_spec.card_text}")
    title.append(f"  {selected_position}/{repo_count}", style=theme_spec.dim_text)

    header = Text(status.full_name, style=f"bold {theme_spec.card_text}")
    if status.is_service:
        header.append("  service", style=theme_spec.card_warning)

    team_line = Text()
    team_line.append("team ", style="bold")
    team_line.append_text(_team_badge(team_label, team_tint, extra_count=extra_teams))

    lines = [
        header,
        team_line,
        _build_ci_line(status),
        _build_counts_line(status, health),
        _build_renovate_line(health),
    ]

    focus_details = _detail_lines(status, health, limit=3)
    if focus_details:
        lines.append(Text("findings", style="bold"))
        lines.extend(focus_details)

    return Panel(
        Group(*lines),
        title=title,
        border_style=theme_spec.card_selected,
        box=box.ROUNDED,
        style=f"{theme_spec.card_text} on {theme_spec.card_background}",
        padding=(0, 1),
    )


def _build_controls_panel(
    theme_spec: DashboardThemeSpec,
    team_labels: dict[str, str],
    *,
    layout_mode: str,
    sort_mode: str,
    filter_mode: str,
    theme_name: str,
) -> Panel:
    filter_label = _format_filter_label(filter_mode, team_labels)
    body = Text()
    body.append("sort   ", style="bold")
    body.append(f"{sort_mode}\n")
    body.append("filter ", style="bold")
    if filter_mode == "all":
        body.append(f"{filter_label}\n", style=theme_spec.dim_text)
    else:
        body.append(f"{filter_label}\n", style="yellow")
    body.append("layout ", style="bold")
    layout_style = theme_spec.card_selected if layout_mode == "packed" else theme_spec.dim_text
    body.append(f"{layout_mode}\n", style=layout_style)
    body.append("theme  ", style="bold")
    body.append(f"{theme_name}\n", style=theme_spec.card_selected)
    body.append("\n")
    body.append("team tint ", style="bold")
    body.append("background = primary team\n", style=theme_spec.dim_text)
    body.append("arrows / h l j k\n", style="bold")
    body.append("move across the grid\n", style=theme_spec.dim_text)
    body.append("enter  details\n", style="bold")
    body.append("click  details\n", style="bold")
    body.append("mid    actions tab\n", style="bold")
    body.append("right  esc on overlays\n", style=theme_spec.dim_text)
    body.append("o      open repo\n", style="bold")
    body.append("s f g t r cycle and refresh", style=theme_spec.dim_text)

    return Panel(
        body,
        title=Text("Controls", style=f"bold {theme_spec.card_text}"),
        border_style=theme_spec.card_border,
        box=box.ROUNDED,
        style=f"{theme_spec.card_text} on {theme_spec.card_background}",
        padding=(0, 1),
    )


def _build_progress_bar(
    fraction: float,
    width: int = 16,
    *,
    usage_style: bool = True,
) -> Text:
    """Build a text-based progress bar.

    usage_style=True colors by severity (green/yellow/red). For time bars,
    usage_style=False colors cyan throughout (time elapsing is not a warning).
    """
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    empty = width - filled
    if usage_style:
        if fraction >= 0.9:
            bar_style = "bold red"
        elif fraction >= 0.7:
            bar_style = "yellow"
        else:
            bar_style = "green"
    else:
        bar_style = "cyan"
    bar = Text("[", style="dim")
    bar.append("#" * filled, style=bar_style)
    bar.append("-" * empty, style="dim")
    bar.append("]", style="dim")
    return bar


def _format_token_count(count: int) -> str:
    """Format large token counts for display."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def _format_time_remaining(seconds: int) -> str:
    """Format seconds as '3d 14h' or '6h 23m' or '12m 5s'."""
    if seconds <= 0:
        return "0s"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


# Keep backward-compat alias for existing tests/imports.
def _build_usage_progress_bar(fraction: float, width: int = 16) -> Text:
    bar = _build_progress_bar(fraction, width, usage_style=True)
    if fraction >= 0.9:
        pct_style = "bold red"
    elif fraction >= 0.7:
        pct_style = "yellow"
    else:
        pct_style = "green"
    bar.append(f" {fraction * 100:.0f}%", style=pct_style)
    return bar


def _build_usage_panel(
    usage_stats: list[UsageStats],
    theme_spec: DashboardThemeSpec,
) -> Panel:
    """Build the API usage dashboard panel for the sidebar."""
    body = Text()

    for i, stats in enumerate(usage_stats):
        if i > 0:
            body.append("\n")

        status_icon = {
            "ok": Text("*", style="green"),
            "warning": Text("*", style="yellow"),
            "critical": Text("*", style="bold red"),
            "empty": Text("-", style="dim"),
            "unknown": Text("?", style="dim"),
            "unconfigured": Text("-", style="dim"),
        }.get(stats.status, Text("?", style="dim"))

        body.append_text(status_icon)
        body.append(f" {stats.display_name}", style="bold")
        body.append(f" ({stats.window_days}d)")
        if stats.tier:
            body.append(f"  {stats.tier}", style=theme_spec.dim_text)
        body.append("\n")

        if stats.status == "unconfigured":
            body.append(f"  {stats.error or 'not configured'}\n", style=theme_spec.dim_text)
            continue

        if stats.status == "unknown" and stats.messages == 0 and stats.sessions == 0:
            body.append(f"  {stats.error or 'unavailable'}\n", style=theme_spec.dim_text)
            continue

        if stats.status == "empty":
            body.append(
                f"  {stats.note or stats.error or 'no activity in window'}\n",
                style=theme_spec.dim_text,
            )
            continue

        # Usage progress bar (messages / limit)
        fraction = stats.usage_fraction
        body.append("  used  ", style="bold")
        if fraction is not None:
            body.append_text(_build_progress_bar(fraction, usage_style=True))
            pct = fraction * 100
            pct_style = (
                "bold red" if pct >= 90 else "yellow" if pct >= 70 else "green"
            )
            body.append(f" {pct:.0f}%", style=pct_style)
            body.append(f"\n        {stats.messages:,} / {stats.limit:,} msgs\n")
        else:
            body.append(f"{stats.messages:,} msgs\n", style=theme_spec.dim_text)

        # Time remaining progress bar (elapsed fraction of window)
        elapsed = stats.time_elapsed_fraction
        if elapsed is not None and stats.time_remaining_seconds is not None:
            body.append("  time  ", style="bold")
            body.append_text(_build_progress_bar(elapsed, usage_style=False))
            body.append(
                f" {_format_time_remaining(stats.time_remaining_seconds)} left\n",
                style=theme_spec.dim_text,
            )

        # Counts line
        body.append("  sessions ", style="bold")
        body.append(f"{stats.sessions:,}", style=theme_spec.dim_text)
        body.append("  tools ", style="bold")
        body.append(f"{stats.tool_calls:,}\n", style=theme_spec.dim_text)

        if stats.input_tokens > 0 or stats.output_tokens > 0:
            body.append("  tokens ", style="bold")
            body.append(
                f"in {_format_token_count(stats.input_tokens)} "
                f"out {_format_token_count(stats.output_tokens)}\n",
                style=theme_spec.dim_text,
            )

        if stats.note:
            body.append(f"  {stats.note}\n", style=theme_spec.dim_text)

    return Panel(
        body,
        title=Text("Usage", style=f"bold {theme_spec.card_text}"),
        border_style=theme_spec.card_border,
        box=box.ROUNDED,
        style=f"{theme_spec.card_text} on {theme_spec.card_background}",
        padding=(0, 1),
    )


def _selected_position(healths: list[RepoHealth], selected_repo: str | None) -> int:
    if not selected_repo:
        return 0
    for index, health in enumerate(healths, start=1):
        if health.status.full_name == selected_repo:
            return index
    return 0


# ---------------------------------------------------------------------------
# Command palette providers
# ---------------------------------------------------------------------------


class ThemeProvider(Provider):
    """Command palette provider for theme switching."""

    async def discover(self) -> Hits:
        for name in THEME_NAMES:
            yield Hit(
                score=1.0,
                match_display=f"Switch theme: {name}",
                command=partial(self._switch, name),
                help=f"Apply the {name} theme",
            )

    async def search(self, query: str) -> Hits:
        for name in THEME_NAMES:
            if query.lower() in name:
                yield Hit(
                    score=1.0,
                    match_display=f"Switch theme: {name}",
                    command=partial(self._switch, name),
                    help=f"Apply the {name} theme",
                )

    async def _switch(self, name: str) -> None:
        self.app.theme = name
        if isinstance(self.app, DashboardApp):
            self.app._update_ui()


class RefreshProvider(Provider):
    """Command palette provider for manual refresh."""

    async def discover(self) -> Hits:
        yield Hit(
            score=0.5,
            match_display="Force refresh now",
            command=self._do_refresh,
            help="Fetch fresh data from GitHub API",
        )

    async def search(self, query: str) -> Hits:
        if "refresh" in query.lower():
            yield Hit(
                score=1.0,
                match_display="Force refresh now",
                command=self._do_refresh,
                help="Fetch fresh data from GitHub API",
            )

    async def _do_refresh(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app._trigger_refresh()


class FilterProvider(Provider):
    """Command palette provider for filter switching, including team filters."""

    async def discover(self) -> Hits:
        app = self.app
        if not isinstance(app, DashboardApp):
            return
        for mode in app.available_filter_modes():
            yield Hit(
                score=0.8,
                match_display=f"Filter: {app.filter_label(mode)}",
                command=partial(self._switch, mode),
                help=f"Show {app.filter_label(mode)} repositories",
            )

    async def search(self, query: str) -> Hits:
        app = self.app
        if not isinstance(app, DashboardApp):
            return
        lowered = query.lower()
        for mode in app.available_filter_modes():
            label = app.filter_label(mode)
            if lowered in label.lower() or lowered in mode.lower():
                yield Hit(
                    score=1.0,
                    match_display=f"Filter: {label}",
                    command=partial(self._switch, mode),
                    help=f"Show {label} repositories",
                )

    async def _switch(self, mode: str) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app.filter_mode = mode


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


class HelpScreen(ModalScreen[None]):
    """Modal overlay showing keybinding reference."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-container {
        width: 60;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("question_mark", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="help-container"):
            yield Static(id="help-content")

    def on_mount(self) -> None:
        lines = Text()
        lines.append("Keybindings\n\n", style="bold underline")
        bindings = [
            ("j / Down", "Move down a row"),
            ("k / Up", "Move up a row"),
            ("h / Left", "Move one card left"),
            ("l / Right", "Move one card right"),
            ("Enter", "Drill into selected repo"),
            ("Left click", "Open repo details"),
            ("Middle click", "Open Actions in new tab"),
            ("Right click", "Back / dismiss overlay"),
            ("Escape", "Back / dismiss overlay"),
            ("Ctrl+Scroll", "Resize card width"),
            ("s", "Cycle sort mode"),
            ("f", "Cycle filter mode, including teams"),
            ("g", "Toggle grouped / packed layout"),
            ("t", "Cycle theme"),
            ("r", "Force refresh"),
            ("o", "Open repo in browser"),
            ("/", "Command palette"),
            ("?", "This help screen"),
            ("q", "Quit"),
        ]
        for key, desc in bindings:
            lines.append(f"  {key:<14}", style="bold")
            lines.append(f" {desc}\n")
        self.query_one("#help-content", Static).update(lines)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == _MOUSE_BUTTON_RIGHT:
            self.app.pop_screen()
            event.stop()


class DrillDownScreen(Screen[None]):
    """Detail view for a single repo's health findings."""

    DEFAULT_CSS = """
    #drilldown-content {
        padding: 1 2;
    }
    #repo-title {
        text-style: bold;
        margin-bottom: 1;
    }
    .health-section {
        margin-bottom: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("o", "open_browser", "Open in browser"),
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
    ]

    def __init__(self, health: RepoHealth) -> None:
        super().__init__()
        self.health = health

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="drilldown-content"):
            yield Static(id="repo-title")
            yield Static(id="health-detail")
        yield Footer()

    def on_mount(self) -> None:
        status = self.health.status
        title = Text()
        title.append(status.full_name, style="bold")
        if status.is_service:
            title.append("  [service]", style="dim")
        self.query_one("#repo-title", Static).update(title)
        self._render_health_detail()

    def _render_health_detail(self) -> None:
        content = Text()
        status = self.health.status

        content.append("CI Status\n", style="bold underline")
        content.append("  main: ")
        content.append_text(_status_badge(status.main_status))
        if status.main_error:
            content.append(f" -- {status.main_error}", style="red")
        content.append("\n")
        if status.is_service and status.dev_status:
            content.append("  dev:  ")
            content.append_text(_status_badge(status.dev_status))
            if status.dev_error:
                content.append(f" -- {status.dev_error}", style="red")
            content.append("\n")
        actions_url = f"https://github.com/{status.full_name}/actions"
        content.append("  ")
        content.append("View actions", style=f"link {actions_url}")
        content.append("\n\n")

        findings = self.health.findings
        if findings:
            content.append("Health Findings\n", style="bold underline")
            for finding in findings:
                sev_icon = _SEVERITY_ICON.get(finding.severity, _SEVERITY_ICON[Severity.OK])
                content.append("  ")
                content.append_text(sev_icon.copy())
                content.append(f" {finding.check_name}: {finding.summary}\n")
                if finding.link:
                    content.append("    ")
                    content.append("Open in browser", style=f"link {finding.link}")
                    content.append("\n")
            content.append("\n")

        content.append("Summary\n", style="bold underline")
        content.append(f"  Open issues: {status.open_issues}\n")
        content.append(f"  Open PRs:    {status.open_prs}")
        if status.draft_prs:
            content.append(f" ({status.draft_prs} draft)")
        content.append("\n")
        issues_url = f"https://github.com/{status.full_name}/issues"
        content.append("  ")
        content.append("View issues", style=f"link {issues_url}")
        content.append("  ")
        prs_url = f"https://github.com/{status.full_name}/pulls"
        content.append("View PRs", style=f"link {prs_url}")
        content.append("\n")

        self.query_one("#health-detail", Static).update(content)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_open_browser(self) -> None:
        url = f"https://github.com/{self.health.status.full_name}"
        webbrowser.open(url)

    def action_open_actions_browser(self) -> None:
        url = f"https://github.com/{self.health.status.full_name}/actions"
        webbrowser.open_new_tab(url)

    def action_scroll_down(self) -> None:
        self.query_one(VerticalScroll).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one(VerticalScroll).scroll_up()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == _MOUSE_BUTTON_RIGHT:
            self.action_go_back()
            event.stop()
        elif event.button == _MOUSE_BUTTON_MIDDLE:
            self.action_open_actions_browser()
            event.stop()


class RepoGrid(Static):
    """Focusable render surface for the repo card grid."""

    can_focus = True

    BINDINGS = [
        Binding("down", "cursor_down", "Down", show=False, priority=True),
        Binding("j", "cursor_down", "Down", show=False, priority=True),
        Binding("up", "cursor_up", "Up", show=False, priority=True),
        Binding("k", "cursor_up", "Up", show=False, priority=True),
        Binding("left", "cursor_left", "Left", show=False, priority=True),
        Binding("h", "cursor_left", "Left", show=False, priority=True),
        Binding("right", "cursor_right", "Right", show=False, priority=True),
        Binding("l", "cursor_right", "Right", show=False, priority=True),
        Binding("enter", "open_detail", "Open", show=False, priority=True),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._card_regions: list[RepoCardRegion] = []

    def set_card_regions(self, card_regions: list[RepoCardRegion]) -> None:
        self._card_regions = card_regions

    def card_region(self, full_name: str | None) -> RepoCardRegion | None:
        if full_name is None:
            return None
        return next(
            (region for region in self._card_regions if region.full_name == full_name), None
        )

    def repo_at(self, x: int, y: int) -> str | None:
        return _repo_at_position(self._card_regions, x, y)

    def _grid_column_count(self) -> int:
        app = self.app
        pw = app.panel_width if isinstance(app, DashboardApp) else _PANEL_WIDTH
        usable_width = max(self.size.width, pw)
        return max(1, usable_width // (pw + _PANEL_GAP))

    def action_cursor_down(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app.move_selection(self._grid_column_count())

    def action_cursor_up(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app.move_selection(-self._grid_column_count())

    def action_cursor_left(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app.move_selection(-1)

    def action_cursor_right(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app.move_selection(1)

    def action_open_detail(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app.open_selected_detail()

    def key_enter(self) -> None:
        self.action_open_detail()

    def key_ctrl_m(self) -> None:
        self.action_open_detail()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if event.ctrl:
            app = self.app
            if isinstance(app, DashboardApp):
                app.panel_width = min(_PANEL_MAX_WIDTH, app.panel_width + _PANEL_WIDTH_STEP)
            event.stop()
            event.prevent_default()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if event.ctrl:
            app = self.app
            if isinstance(app, DashboardApp):
                app.panel_width = max(_PANEL_MIN_WIDTH, app.panel_width - _PANEL_WIDTH_STEP)
            event.stop()
            event.prevent_default()

    def on_click(self, event: events.Click) -> None:
        app = self.app
        if not isinstance(app, DashboardApp):
            return

        repo_full_name = self.repo_at(event.x, event.y)
        if repo_full_name is None:
            return

        self.focus()
        app.select_repo(repo_full_name)
        if event.button == _MOUSE_BUTTON_LEFT:
            app.open_selected_detail()
        elif event.button == _MOUSE_BUTTON_MIDDLE:
            app.open_repo_actions(repo_full_name)
        else:
            return
        event.stop()


class MainScreen(Screen[None]):
    """Primary screen with a panel-oriented repo browser."""

    DEFAULT_CSS = """
    MainScreen {
        layers: background content;
    }
    #chrome {
        layer: content;
        width: 100%;
        height: 100%;
        background: transparent;
    }
    #status-bar {
        height: 1;
        dock: top;
        background: $surface;
        padding: 0 2;
        color: $text;
    }
    #dashboard-body {
        height: 1fr;
        padding: 1 1 1 2;
        background: transparent;
    }
    #panel-scroll {
        width: 1fr;
        padding-right: 1;
        background: transparent;
    }
    #repo-grid {
        width: 100%;
        height: auto;
        background: transparent;
    }
    #sidebar {
        width: 30;
        min-width: 26;
        height: 1fr;
        padding-right: 1;
        background: transparent;
    }
    #sidebar-focus, #sidebar-usage, #sidebar-controls {
        width: 100%;
        margin-bottom: 1;
        background: transparent;
    }
    """

    BINDINGS = [
        Binding("down", "cursor_down", "Down", show=False, priority=True),
        Binding("j", "cursor_down", "Down", show=False, priority=True),
        Binding("up", "cursor_up", "Up", show=False, priority=True),
        Binding("k", "cursor_up", "Up", show=False, priority=True),
        Binding("left", "cursor_left", "Left", show=False, priority=True),
        Binding("h", "cursor_left", "Left", show=False, priority=True),
        Binding("right", "cursor_right", "Right", show=False, priority=True),
        Binding("l", "cursor_right", "Right", show=False, priority=True),
        Binding("enter", "open_detail", "Open", show=False, priority=True),
        Binding("s", "cycle_sort", "Sort"),
        Binding("f", "cycle_filter", "Filter"),
        Binding("g", "cycle_layout", "Layout"),
        Binding("o", "open_browser", "Open"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.visible_repo_count = 0

    def compose(self) -> ComposeResult:
        with Container(id="chrome"):
            yield Header()
            yield Static(id="status-bar")
            with Horizontal(id="dashboard-body"):
                with VerticalScroll(id="panel-scroll"):
                    yield RepoGrid(id="repo-grid")
                with VerticalScroll(id="sidebar"):
                    yield Static(id="sidebar-focus")
                    yield Static(id="sidebar-usage")
                    yield Static(id="sidebar-controls")
            yield Footer()

    def on_mount(self) -> None:
        self.query_one(RepoGrid).focus()

    def on_resize(self, _event: events.Resize) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app.call_after_refresh(app._update_ui)

    def update_table(self, healths: list[RepoHealth], sort_mode: str, filter_mode: str) -> None:
        app = self.app
        if not isinstance(app, DashboardApp):
            return

        sorted_healths = _visible_healths_for(
            healths,
            sort_mode,
            filter_mode,
            app._repo_teams,
            app.layout_mode,
        )
        self.visible_repo_count = len(sorted_healths)

        app._ensure_selection(sorted_healths)
        selected = app._selected_health(sorted_healths)
        selected_repo = app._selected_repo_full_name
        selected_position = _selected_position(sorted_healths, selected_repo)
        theme_spec = get_theme_spec(app.theme)
        grid = self.query_one(RepoGrid)
        scroll = self.query_one("#panel-scroll", VerticalScroll)
        pw = app.panel_width
        grid_width = max(grid.size.width, scroll.size.width - 1, pw)
        grid.set_card_regions(
            _build_repo_card_regions(
                sorted_healths,
                selected_repo,
                theme_spec,
                app._repo_teams,
                app._team_labels,
                filter_mode,
                grid_width,
                app.layout_mode,
                panel_width=pw,
            )
        )

        grid.update(
            _build_repo_grid(
                sorted_healths,
                selected_repo,
                theme_spec,
                app._repo_teams,
                app._team_labels,
                filter_mode,
                app.layout_mode,
                panel_width=pw,
            )
        )
        self.query_one("#sidebar-focus", Static).update(
            _build_focus_panel(
                selected,
                theme_spec,
                app._repo_teams,
                app._team_labels,
                selected_position=selected_position,
                repo_count=self.visible_repo_count,
            )
        )
        self.query_one("#sidebar-usage", Static).update(
            _build_usage_panel(app._usage_stats, theme_spec)
        )
        self.query_one("#sidebar-controls", Static).update(
            _build_controls_panel(
                theme_spec,
                app._team_labels,
                layout_mode=app.layout_mode,
                sort_mode=sort_mode,
                filter_mode=filter_mode,
                theme_name=app.theme,
            )
        )
        grid.focus()
        self._scroll_selection_into_view()

    def update_status_bar(
        self,
        org: str,
        last_refresh: str,
        sort_mode: str,
        filter_mode: str,
        repo_count: int,
        consecutive_errors: int = 0,
    ) -> None:
        app = self.app
        if not isinstance(app, DashboardApp):
            return
        theme_name = app.theme
        selected_repo = app._selected_repo_full_name
        team_labels = app._team_labels
        layout_mode = app.layout_mode
        filter_label = _format_filter_label(filter_mode, team_labels)

        bar = Text()
        bar.append(org or "repos", style="bold")

        # Countdown / stale / refreshing indicator
        now = datetime.now(UTC)
        if app._is_refreshing:
            bar.append(" | refreshing...", style="bold yellow")
        elif app._last_refresh_time is not None:
            age = (now - app._last_refresh_time).total_seconds()
            stale_threshold = app._refresh_seconds * 1.5
            if age > stale_threshold:
                age_min = int(age // 60)
                bar.append(f" | /!\\ stale ({age_min}m ago)", style="bold yellow")
            elif app._next_refresh_at is not None:
                remaining = max(0, (app._next_refresh_at - now).total_seconds())
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                bar.append(f" | [r] {mins}m {secs:02d}s", style="dim")
            else:
                bar.append(f" | {last_refresh}", style="dim")
        else:
            bar.append(f" | {last_refresh}", style="dim")

        bar.append(f" | sort {sort_mode}", style="dim")
        if filter_mode != "all":
            bar.append(f" | filter {filter_label}", style="yellow")
        bar.append(f" | {repo_count} visible", style="dim")
        if selected_repo:
            bar.append(f" | {selected_repo.split('/')[-1]}", style="bold")
        bar.append(f" | layout {layout_mode}", style="dim")
        bar.append(f" | theme {theme_name}", style="dim")
        if consecutive_errors > 0:
            bar.append(f" | {consecutive_errors} error(s)", style="bold red")
        self.query_one("#status-bar", Static).update(bar)

    def _grid_column_count(self) -> int:
        return self.query_one(RepoGrid)._grid_column_count()

    def _scroll_selection_into_view(self) -> None:
        app = self.app
        if not isinstance(app, DashboardApp) or not app._selected_repo_full_name:
            return

        grid = self.query_one(RepoGrid)
        selected_region = grid.card_region(app._selected_repo_full_name)
        if selected_region is None:
            return

        self.query_one("#panel-scroll", VerticalScroll).scroll_to(
            y=max(0, selected_region.y - 1),
            animate=True,
            force=True,
            duration=0.15,
        )

    def action_cursor_down(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app.move_selection(self._grid_column_count())

    def action_cursor_up(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app.move_selection(-self._grid_column_count())

    def action_cursor_left(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app.move_selection(-1)

    def action_cursor_right(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app.move_selection(1)

    def action_open_detail(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            app.open_selected_detail()

    def action_cycle_sort(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            idx = (SORT_MODES.index(app.sort_mode) + 1) % len(SORT_MODES)
            app.sort_mode = SORT_MODES[idx]
            app.notify(f"Sort: {app.sort_mode}", timeout=2)

    def action_cycle_filter(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            filters = app.available_filter_modes()
            try:
                idx = filters.index(app.filter_mode)
            except ValueError:
                idx = -1
            app.filter_mode = filters[(idx + 1) % len(filters)]
            app.notify(f"Filter: {app.filter_label(app.filter_mode)}", timeout=2)

    def action_cycle_layout(self) -> None:
        app = self.app
        if isinstance(app, DashboardApp):
            idx = (LAYOUT_MODES.index(app.layout_mode) + 1) % len(LAYOUT_MODES)
            app.layout_mode = LAYOUT_MODES[idx]
            app.notify(f"Layout: {app.layout_mode}", timeout=2)

    def action_open_browser(self) -> None:
        app = self.app
        if not isinstance(app, DashboardApp):
            return
        selected = app.selected_health()
        if selected is not None:
            webbrowser.open(f"https://github.com/{selected.status.full_name}")


# ---------------------------------------------------------------------------
# Sorting and filtering helpers
# ---------------------------------------------------------------------------


def _apply_sort(healths: list[RepoHealth], mode: str) -> list[RepoHealth]:
    if mode == "alpha":
        return sorted(healths, key=lambda h: h.status.name.lower())
    if mode == "problem":
        return sorted(healths, key=lambda h: (int(h.worst_severity), h.status.name.lower()))
    return sorted(healths, key=lambda h: h.score)


def _apply_filter(
    healths: list[RepoHealth],
    mode: str,
    repo_teams: dict[str, RepoTeamInfo] | None = None,
) -> list[RepoHealth]:
    repo_teams = repo_teams or {}
    if mode == "all":
        return healths
    if mode == "broken-ci":
        return [
            h
            for h in healths
            if any(c.check_name == "broken_ci" and c.severity != Severity.OK for c in h.checks)
        ]
    if mode == "no-renovate":
        return [
            h
            for h in healths
            if any(
                c.check_name == "renovate_enabled" and c.severity != Severity.OK for c in h.checks
            )
        ]
    if mode == "stale-prs":
        return [
            h
            for h in healths
            if any(c.check_name == "stale_prs" and c.severity != Severity.OK for c in h.checks)
        ]
    if mode == "issues":
        return [
            h
            for h in healths
            if any(c.check_name == "open_issues" and c.severity != Severity.OK for c in h.checks)
        ]
    team_key = _team_key_from_filter(mode)
    if team_key is not None:
        if team_key == _UNASSIGNED_TEAM:
            return [
                h
                for h in healths
                if _repo_team_info(h.status.full_name, repo_teams).primary == _UNASSIGNED_TEAM
            ]
        return [
            h for h in healths if team_key in _repo_team_info(h.status.full_name, repo_teams).all
        ]
    return healths


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------


class DashboardApp(App[None]):
    """Interactive health dashboard for GitHub repositories."""

    TITLE = "ai-gh panel"
    ANIMATION_LEVEL = "full"

    DEFAULT_CSS = """
    Screen {
        background: $background;
    }
    """

    COMMANDS = {ThemeProvider, RefreshProvider, FilterProvider}

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("t", "cycle_theme", "Theme"),
        Binding("question_mark", "show_help", "Help"),
        Binding("down", "move_down", show=False, priority=True),
        Binding("j", "move_down", show=False, priority=True),
        Binding("up", "move_up", show=False, priority=True),
        Binding("k", "move_up", show=False, priority=True),
        Binding("left", "move_left", show=False, priority=True),
        Binding("h", "move_left", show=False, priority=True),
        Binding("right", "move_right", show=False, priority=True),
        Binding("l", "move_right", show=False, priority=True),
        Binding("enter", "open_selected", show=False, priority=True),
        Binding("o", "open_selected_browser", show=False, priority=True),
    ]

    def __init__(
        self,
        repos: list[Repository],
        refresh_seconds: int = 600,
        initial_theme: str = "default",
        health_config: dict | None = None,
        org_name: str = "",
        skip_refresh: bool = False,
    ) -> None:
        super().__init__()
        self._repos = repos
        self._refresh_seconds = refresh_seconds
        self._initial_theme = initial_theme
        self._health_config = health_config or {}
        self._org_name = org_name
        self._skip_refresh = skip_refresh
        self._healths: list[RepoHealth] = []
        self._health_by_name: dict[str, RepoHealth] = {}
        self._repo_teams: dict[str, RepoTeamInfo] = {}
        self._team_labels: dict[str, str] = {_UNASSIGNED_TEAM: "Unassigned"}
        self._selected_repo_full_name: str | None = None
        self._last_refresh = "loading..."
        self._refresh_cycle = 0
        self._consecutive_errors = 0
        self._last_error: str | None = None
        self._is_refreshing = False
        self._last_refresh_time: datetime | None = None
        self._next_refresh_at: datetime | None = None
        # Populate synchronously so the sidebar has data on first paint.
        try:
            self._usage_stats: list[UsageStats] = fetch_all_usage()
        except Exception:
            self._usage_stats = []

    sort_mode: reactive[str] = reactive(SORT_MODES[0])
    filter_mode: reactive[str] = reactive(FILTER_MODES[0])
    layout_mode: reactive[str] = reactive(LAYOUT_MODES[0])
    panel_width: reactive[int] = reactive(_PANEL_WIDTH)

    def on_mount(self) -> None:
        for theme in THEMES:
            self.register_theme(theme)
        self.theme = self._initial_theme

        self.push_screen(MainScreen())
        if self._repos:
            self.call_after_refresh(self._load_cached)
            if not self._skip_refresh:
                self.set_interval(self._refresh_seconds, self._trigger_refresh)
                self._trigger_refresh()
        else:
            self.call_after_refresh(self._update_ui)
        self.set_interval(1, self._tick_countdown)
        # Refresh usage independently on a short cadence; local reads are cheap.
        self.set_interval(60, self._refresh_usage)

    def _visible_healths(self) -> list[RepoHealth]:
        return _visible_healths_for(
            self._healths,
            self.sort_mode,
            self.filter_mode,
            self._repo_teams,
            self.layout_mode,
        )

    def available_filter_modes(self) -> list[str]:
        return _available_filter_modes(self._team_labels, self._repo_teams)

    def filter_label(self, mode: str) -> str:
        return _format_filter_label(mode, self._team_labels)

    def _remember_repo_teams(self, repo) -> None:
        full_name = getattr(repo, "full_name", "")
        if not full_name or full_name in self._repo_teams:
            return
        try:
            teams = sorted(repo.get_teams(), key=_team_sort_key)
        except Exception:
            self._repo_teams[full_name] = RepoTeamInfo()
            return

        team_keys: list[str] = []
        for team in teams:
            slug = getattr(team, "slug", "") or ""
            if not slug:
                continue
            name = getattr(team, "name", "") or slug
            team_keys.append(slug)
            self._team_labels.setdefault(slug, name)

        if not team_keys:
            self._repo_teams[full_name] = RepoTeamInfo()
            return

        self._repo_teams[full_name] = RepoTeamInfo(primary=team_keys[0], all=tuple(team_keys))

    def _ensure_selection(self, visible_healths: list[RepoHealth]) -> None:
        if not visible_healths:
            self._selected_repo_full_name = None
            return
        visible_names = {health.status.full_name for health in visible_healths}
        if self._selected_repo_full_name not in visible_names:
            self._selected_repo_full_name = visible_healths[0].status.full_name

    def _selected_health(
        self, visible_healths: list[RepoHealth] | None = None
    ) -> RepoHealth | None:
        healths = visible_healths if visible_healths is not None else self._visible_healths()
        if not healths:
            return None
        self._ensure_selection(healths)
        return next(
            (
                health
                for health in healths
                if health.status.full_name == self._selected_repo_full_name
            ),
            healths[0],
        )

    def selected_health(self) -> RepoHealth | None:
        return self._selected_health()

    def select_repo(self, full_name: str) -> None:
        visible_healths = self._visible_healths()
        visible_names = {health.status.full_name for health in visible_healths}
        if full_name not in visible_names:
            return
        self._selected_repo_full_name = full_name
        self._update_ui()

    def move_selection(self, delta: int) -> None:
        visible_healths = self._visible_healths()
        if not visible_healths:
            return

        self._ensure_selection(visible_healths)
        current_index = next(
            (
                index
                for index, health in enumerate(visible_healths)
                if health.status.full_name == self._selected_repo_full_name
            ),
            0,
        )
        new_index = max(0, min(len(visible_healths) - 1, current_index + delta))
        self._selected_repo_full_name = visible_healths[new_index].status.full_name
        self._update_ui()

    def open_selected_detail(self) -> None:
        selected = self.selected_health()
        if selected is not None:
            self.push_screen(DrillDownScreen(selected))

    def open_repo_actions(self, full_name: str) -> None:
        webbrowser.open_new_tab(f"https://github.com/{full_name}/actions")

    def _load_cached(self) -> None:
        try:
            cache = load_cache()
            if not cache:
                return
            statuses = list(cache.values())
            health_cache = load_health_cache(cache)
            self._healths = [
                health_cache.get(s.full_name) or RepoHealth(status=s) for s in statuses
            ]
            self._health_by_name = {h.status.full_name: h for h in self._healths}
            self._last_refresh = "cached" if not self._skip_refresh else "cached (no refresh)"
            if self._skip_refresh:
                self._last_refresh_time = datetime.now(UTC)
            self._update_ui()
        except Exception as exc:
            self.notify(
                f"Cache load failed: {exc.__class__.__name__}",
                severity="warning",
                timeout=5,
            )

    def _refresh_usage(self) -> None:
        try:
            self._usage_stats = fetch_all_usage()
            self._update_ui()
        except Exception:
            pass

    def _trigger_refresh(self) -> None:
        self._is_refreshing = True
        self._next_refresh_at = datetime.now(UTC) + timedelta(seconds=self._refresh_seconds)
        self.run_worker(self._do_refresh_sync, thread=True, exit_on_error=False)

    def _do_refresh_sync(self) -> None:
        try:
            self._do_refresh_inner()
            self._consecutive_errors = 0
            self._last_error = None
        except Exception as exc:
            self._is_refreshing = False
            self._consecutive_errors += 1
            self._last_error = f"{exc.__class__.__name__}: {exc}"
            short = exc.__class__.__name__
            if self._consecutive_errors == 1:
                self.call_from_thread(
                    self.notify,
                    f"Refresh failed: {short} -- showing stale data",
                    severity="warning",
                    timeout=8,
                )
            elif self._consecutive_errors % 5 == 0:
                self.call_from_thread(
                    self.notify,
                    f"Refresh failing ({self._consecutive_errors}x): {short}",
                    severity="error",
                    timeout=8,
                )
            self.call_from_thread(self._update_ui)

    def _do_refresh_inner(self) -> None:
        repos = self._repos
        config = self._health_config

        statuses: list[RepoStatus] = []
        for repo in repos:
            self._remember_repo_teams(repo)
            try:
                statuses.append(fetch_repo_status(repo))
            except Exception:
                statuses.append(
                    RepoStatus(
                        name=repo.name,
                        full_name=repo.full_name,
                        is_service=False,
                        main_status="unknown",
                        main_error=None,
                        dev_status=None,
                        dev_error=None,
                        open_issues=0,
                        open_prs=0,
                        draft_prs=0,
                    )
                )

        healths: list[RepoHealth] = []
        for repo, status in zip(repos, statuses, strict=True):
            try:
                ctx = FetchContext.build(repo)
                healths.append(run_health_checks(repo, status, config=config, context=ctx))
            except Exception:
                healths.append(RepoHealth(status=status))

        try:
            save_cache(statuses, healths=healths)
        except Exception:
            pass

        self._healths = healths
        self._health_by_name = {h.status.full_name: h for h in healths}
        self._last_refresh = datetime.now(UTC).strftime("%H:%M:%S UTC")
        self._last_refresh_time = datetime.now(UTC)
        self._is_refreshing = False
        self._refresh_cycle += 1

        try:
            self._usage_stats = fetch_all_usage()
        except Exception:
            pass

        self.call_from_thread(self._update_ui)

    def _update_ui(self) -> None:
        try:
            screen = self.screen
            if isinstance(screen, MainScreen):
                screen.update_table(self._healths, self.sort_mode, self.filter_mode)
                screen.update_status_bar(
                    self._org_name,
                    self._last_refresh,
                    self.sort_mode,
                    self.filter_mode,
                    screen.visible_repo_count,
                    self._consecutive_errors,
                )
        except Exception as exc:
            try:
                self.notify(
                    f"UI update error: {exc.__class__.__name__}",
                    severity="warning",
                    timeout=3,
                )
            except Exception:
                pass

    def _tick_countdown(self) -> None:
        """Update the status bar every second for the countdown timer."""
        try:
            screen = self.screen
            if isinstance(screen, MainScreen):
                screen.update_status_bar(
                    self._org_name,
                    self._last_refresh,
                    self.sort_mode,
                    self.filter_mode,
                    screen.visible_repo_count,
                    self._consecutive_errors,
                )
        except Exception:
            pass

    def action_refresh_now(self) -> None:
        self.notify("Refreshing...", timeout=2)
        self._trigger_refresh()

    async def action_quit(self) -> None:
        # Cancel in-flight threaded workers so shutdown doesn't wait on GH calls.
        try:
            self.workers.cancel_all()
        except Exception:
            pass
        self.exit()

    def _grid_step(self) -> int:
        screen = self.screen
        if isinstance(screen, MainScreen):
            return screen._grid_column_count()
        return 1

    def action_move_down(self) -> None:
        if isinstance(self.screen, MainScreen):
            self.move_selection(self._grid_step())

    def action_move_up(self) -> None:
        if isinstance(self.screen, MainScreen):
            self.move_selection(-self._grid_step())

    def action_move_left(self) -> None:
        if isinstance(self.screen, MainScreen):
            self.move_selection(-1)

    def action_move_right(self) -> None:
        if isinstance(self.screen, MainScreen):
            self.move_selection(1)

    def action_open_selected(self) -> None:
        if isinstance(self.screen, MainScreen):
            self.open_selected_detail()

    def action_open_selected_browser(self) -> None:
        if not isinstance(self.screen, MainScreen):
            return
        selected = self.selected_health()
        if selected is not None:
            webbrowser.open(f"https://github.com/{selected.status.full_name}")

    def action_cycle_theme(self) -> None:
        try:
            idx = THEME_NAMES.index(self.theme)
        except ValueError:
            idx = -1
        next_idx = (idx + 1) % len(THEME_NAMES)
        self.theme = THEME_NAMES[next_idx]
        self._update_ui()
        self.notify(f"Theme: {THEME_NAMES[next_idx]}", timeout=2)

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def watch_sort_mode(self, _old: str, _new: str) -> None:
        self._update_ui()

    def watch_filter_mode(self, _old: str, _new: str) -> None:
        self._update_ui()

    def watch_layout_mode(self, _old: str, _new: str) -> None:
        self._update_ui()

    def watch_panel_width(self, _old: int, _new: int) -> None:
        self._update_ui()


def run_panel(
    repos: list[Repository],
    refresh_seconds: int = 600,
    theme: str = "default",
    health_config: dict | None = None,
    org_name: str = "",
    skip_refresh: bool = False,
) -> None:
    """Launch the interactive panel dashboard."""
    app = DashboardApp(
        repos=repos,
        refresh_seconds=refresh_seconds,
        initial_theme=theme,
        health_config=health_config,
        org_name=org_name,
        skip_refresh=skip_refresh,
    )
    app.run()
