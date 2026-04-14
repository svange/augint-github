"""Data fetching, caching, and layout-delegated rendering for the TUI dashboard."""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path

from github.GithubException import GithubException
from github.Repository import Repository
from loguru import logger

from .config import has_dev_branch

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


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


def load_cache() -> dict[str, RepoStatus]:
    """Load cached repo statuses from disk."""
    if not CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(CACHE_FILE.read_text())
        return {key: RepoStatus(**val) for key, val in data.get("repos", {}).items()}
    except (json.JSONDecodeError, TypeError, KeyError):
        return {}


def save_cache(statuses: list[RepoStatus]) -> None:
    """Persist repo statuses to disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {"repos": {s.full_name: asdict(s) for s in statuses}}
    CACHE_FILE.write_text(json.dumps(data, indent=2))


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


def get_run_status(repo: Repository, branch: str) -> tuple[str, str | None]:
    """Get the latest workflow run status and error info for a branch.

    Returns (status_string, error_description_or_None).
    """
    try:
        runs = repo.get_workflow_runs(branch=branch, exclude_pull_requests=True)  # type: ignore[arg-type]
        if runs.totalCount == 0:
            return "unknown", None
        run = runs[0]
        if run.status in ("in_progress", "queued"):
            return "in_progress", None
        if run.conclusion == "success":
            return "success", None
        if run.conclusion in ("failure", "timed_out", "action_required"):
            error = _get_failed_step(run)
            return "failure", error
        return "unknown", None
    except GithubException:
        return "unknown", None


def fetch_repo_status(
    repo: Repository,
    previous: RepoStatus | None = None,
) -> RepoStatus:
    """Fetch status data for a single repository.

    On any unexpected error returns *previous* (stale data) when available,
    or a degraded placeholder so the dashboard never crashes.
    """
    try:
        service = has_dev_branch(repo)
        main_status, main_error = get_run_status(repo, repo.default_branch)
        if service:
            dev_status, dev_error = get_run_status(repo, "dev")
        else:
            dev_status, dev_error = None, None

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
        )
    except Exception:
        logger.debug(f"fetch failed for {repo.full_name}: {traceback.format_exc()}")
        if previous is not None:
            return previous
        # Degraded placeholder -- keeps the dashboard alive
        return RepoStatus(
            name=repo.name,
            full_name=repo.full_name,
            is_service=False,
            main_status="unknown",
            main_error="fetch error",
            dev_status=None,
            dev_error=None,
            open_issues=0,
            open_prs=0,
            draft_prs=0,
        )


# ---------------------------------------------------------------------------
# Dashboard loop
# ---------------------------------------------------------------------------


def _refresh(
    repos: list[Repository],
    previous: list[RepoStatus],
) -> list[RepoStatus]:
    """Fetch fresh statuses, falling back to *previous* per-repo on error."""
    prev_map = {s.full_name: s for s in previous}
    return [fetch_repo_status(r, prev_map.get(r.full_name)) for r in repos]


def run_dashboard(
    repos: list[Repository],
    refresh_seconds: int,
    layout_name: str = "default",
) -> None:
    """Run the live-updating dashboard loop.

    Resilient to transient errors: API failures, rate limits, network
    drops, and even layout rendering bugs are caught and shown as an
    error banner while the last good frame is preserved.
    """
    from rich.console import Console
    from rich.live import Live
    from rich.status import Status
    from rich.text import Text

    from .tui_layouts import get_layout

    layout = get_layout(layout_name)
    console = Console()
    repo_names = {r.full_name for r in repos}
    consecutive_errors = 0

    # Try to show cached data immediately while fetching fresh data
    cache = load_cache()
    cached = [cache[name] for name in repo_names if name in cache]
    if cached:
        console.print(layout.build_dashboard(cached, refresh_seconds, from_cache=True))
        console.print()

    with Status("Fetching repository data...", console=console):
        statuses = _refresh(repos, cached)
    save_cache(statuses)

    with Live(console=console, refresh_per_second=1, screen=False) as live:
        live.update(layout.build_dashboard(statuses, refresh_seconds))
        while True:
            time.sleep(refresh_seconds)
            try:
                statuses = _refresh(repos, statuses)
                save_cache(statuses)
                live.update(layout.build_dashboard(statuses, refresh_seconds))
                consecutive_errors = 0
            except Exception:
                consecutive_errors += 1
                logger.debug(f"refresh error #{consecutive_errors}: {traceback.format_exc()}")
                # Show error banner above last good frame
                try:
                    from rich.console import Group

                    error_msg = Text.from_markup(
                        f"[bold red]Refresh failed[/bold red] [dim](attempt"
                        f" {consecutive_errors}, retrying in {refresh_seconds}s)[/dim]"
                    )
                    last_good = layout.build_dashboard(statuses, refresh_seconds)
                    live.update(Group(error_msg, Text(), last_good))
                except Exception:
                    pass  # even the error render failed; keep whatever is on screen
