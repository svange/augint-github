"""Data fetching, caching, and Rich rendering for the TUI dashboard."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path

from github.GithubException import GithubException
from github.Repository import Repository
from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from .config import has_dev_branch

STATUS_ICON = {
    "success": "[green]\u25cf[/green]",
    "failure": "[red]\u25cf[/red]",
    "in_progress": "[yellow]\u25cf[/yellow]",
    "unknown": "[dim]\u25cf[/dim]",
}

CACHE_DIR = Path.home() / ".cache" / "ai-gh"
CACHE_FILE = CACHE_DIR / "tui_cache.json"


@dataclass
class RepoStatus:
    name: str
    full_name: str
    is_service: bool
    main_status: str
    main_error: str | None
    dev_status: str | None
    dev_error: str | None
    open_issues: int
    open_prs: int
    draft_prs: int
    # ISO-8601 UTC timestamp of the most recent failing run on each branch.
    # Used to drive the "recently broken" border flash in the TUI (< 12h old).
    main_failing_since: str | None = None
    dev_failing_since: str | None = None


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


def load_cache() -> dict[str, RepoStatus]:
    """Load cached repo statuses from disk."""
    if not CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(CACHE_FILE.read_text())
        # Keep the loader tolerant of cache files written by older versions
        # that don't know about newer optional fields (e.g. *_failing_since).
        allowed = {f.name for f in fields(RepoStatus)}
        return {
            key: RepoStatus(**{k: v for k, v in val.items() if k in allowed})
            for key, val in data.get("repos", {}).items()
        }
    except (json.JSONDecodeError, TypeError, KeyError):
        return {}


def save_cache(
    statuses: list[RepoStatus],
    healths: list | None = None,
) -> None:
    """Persist repo statuses and optional health data to disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data: dict = {"repos": {s.full_name: asdict(s) for s in statuses}}
    if healths:
        data["health"] = {h.status.full_name: h.to_dict() for h in healths}
        data["health_ts"] = datetime.now(UTC).isoformat()
    elif CACHE_FILE.exists():
        try:
            existing = json.loads(CACHE_FILE.read_text())
            if "health" in existing:
                data["health"] = existing["health"]
                data["health_ts"] = existing.get("health_ts")
        except (json.JSONDecodeError, KeyError):
            pass
    CACHE_FILE.write_text(json.dumps(data, indent=2))


def load_health_cache(
    statuses: dict[str, RepoStatus],
) -> dict:
    """Load cached health data. Returns dict of full_name -> RepoHealth."""
    if not CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(CACHE_FILE.read_text())
        health_data = data.get("health", {})
        if not health_data:
            return {}
        from .health import RepoHealth

        result = {}
        for full_name, health_dict in health_data.items():
            if full_name in statuses:
                result[full_name] = RepoHealth.from_dict(statuses[full_name], health_dict)
        return result
    except (json.JSONDecodeError, TypeError, KeyError, ImportError):
        return {}


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def _get_failed_step(run):
    """Get a description of the first failed job/step from a workflow run."""
    try:
        jobs = run.jobs()
        for job in jobs:
            if job.conclusion == "failure":
                for step in job.steps:
                    if step.conclusion == "failure":
                        return f"{job.name}: {step.name}"
                return str(job.name)
    except (GithubException, AttributeError):
        pass
    return None


def get_run_status(repo: Repository, branch: str) -> tuple[str, str | None, str | None]:
    """Get the latest workflow run status and error info for a branch.

    Returns ``(status_string, error_description_or_None, failing_since_iso)``.
    ``failing_since_iso`` is the run's ``updated_at`` (UTC, ISO-8601) when
    the conclusion is a failure, otherwise ``None``. It lets the TUI decide
    whether a failure is recent enough to flash the card border.
    """
    try:
        runs = repo.get_workflow_runs(branch=branch, exclude_pull_requests=True)  # type: ignore[arg-type]
        if runs.totalCount == 0:
            return "unknown", None, None
        run = runs[0]
        if run.status in ("in_progress", "queued"):
            return "in_progress", None, None
        if run.conclusion == "success":
            return "success", None, None
        if run.conclusion in ("failure", "timed_out", "action_required"):
            error = _get_failed_step(run)
            when = getattr(run, "updated_at", None) or getattr(run, "run_started_at", None)
            failing_since = _to_iso_utc(when)
            return "failure", error, failing_since
        return "unknown", None, None
    except GithubException:
        return "unknown", None, None


def _to_iso_utc(when) -> str | None:
    """Best-effort conversion of a PyGithub datetime into an ISO-8601 UTC string."""
    if when is None:
        return None
    try:
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return str(when.astimezone(UTC).isoformat())
    except Exception:
        return None


def fetch_repo_status(repo: Repository) -> RepoStatus:
    """Fetch status data for a single repository."""
    service = has_dev_branch(repo)
    main_status, main_error, main_failing_since = get_run_status(repo, repo.default_branch)
    if service:
        dev_status, dev_error, dev_failing_since = get_run_status(repo, "dev")
    else:
        dev_status, dev_error, dev_failing_since = None, None, None

    pulls = repo.get_pulls(state="open")
    open_prs = pulls.totalCount
    draft_prs = sum(1 for pr in pulls if pr.draft)

    # open_issues_count includes PRs in GitHub's API
    open_issues = max(0, repo.open_issues_count - open_prs)

    return RepoStatus(
        name=repo.name,
        full_name=repo.full_name,
        is_service=service,
        main_status=main_status,
        main_error=main_error,
        dev_status=dev_status,
        dev_error=dev_error,
        open_issues=open_issues,
        open_prs=open_prs,
        draft_prs=draft_prs,
        main_failing_since=main_failing_since,
        dev_failing_since=dev_failing_since,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _border_style(status: RepoStatus) -> str:
    """Determine panel border color based on repo state."""
    if status.main_status == "failure":
        return "red"
    if status.dev_status == "failure":
        return "red"
    if status.open_prs > 0:
        return "yellow"
    return "green"


def build_repo_panel(status: RepoStatus) -> Panel:
    """Build a Rich Panel for a single repo's status."""
    lines = Text()

    if status.is_service and status.dev_status is not None:
        lines.append("dev: ")
        lines.append_text(Text.from_markup(STATUS_ICON[status.dev_status]))
        lines.append("  main: ")
        lines.append_text(Text.from_markup(STATUS_ICON[status.main_status]))
    else:
        lines.append("main: ")
        lines.append_text(Text.from_markup(STATUS_ICON[status.main_status]))

    # Error details for failed branches
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
        border_style=_border_style(status),
    )


def build_dashboard(
    statuses: list[RepoStatus],
    refresh_seconds: int,
    *,
    from_cache: bool = False,
) -> Group:
    """Build the full dashboard renderable."""
    now = datetime.now(UTC).strftime("%H:%M:%S UTC")
    cache_tag = "  [dim](cached)[/dim]" if from_cache else ""
    header = Text.from_markup(
        f"[bold]ai-gh dashboard[/bold]  |  {now}  |  refresh: {refresh_seconds}s{cache_tag}"
    )
    panels = [build_repo_panel(s) for s in statuses]
    columns = Columns(panels, padding=(1, 1), expand=False)
    footer = Text.from_markup("[dim]Press Ctrl+C to exit[/dim]")
    return Group(header, Text(), columns, Text(), footer)


# ---------------------------------------------------------------------------
# Dashboard loop
# ---------------------------------------------------------------------------


def run_dashboard(repos: list[Repository], refresh_seconds: int) -> None:
    """Run the live-updating dashboard loop."""
    from rich.console import Console
    from rich.live import Live
    from rich.status import Status

    console = Console()
    repo_names = {r.full_name for r in repos}

    # Try to show cached data immediately while fetching fresh data
    cache = load_cache()
    cached = [cache[name] for name in repo_names if name in cache]
    if cached:
        console.print(build_dashboard(cached, refresh_seconds, from_cache=True))
        console.print()

    with Status("Fetching repository data...", console=console):
        statuses = [fetch_repo_status(r) for r in repos]
    save_cache(statuses)

    with Live(console=console, refresh_per_second=1, screen=False) as live:
        live.update(build_dashboard(statuses, refresh_seconds))
        while True:
            time.sleep(refresh_seconds)
            statuses = [fetch_repo_status(r) for r in repos]
            save_cache(statuses)
            live.update(build_dashboard(statuses, refresh_seconds))
