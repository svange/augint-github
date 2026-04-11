"""Informational status dump for a GitHub repository.

``ai-gh status`` is intentionally opinion-free: it reports current
auto-merge state, any non-default repo configuration, all current
rulesets (including org-inherited ones), and whether a pipeline file
exists on disk. It no longer compares anything to an in-tool template.
"""

from pathlib import Path

import click
from rich import print
from rich.table import Table

from .common import get_github_repo, load_env_config
from .config import get_auto_merge_status, has_dev_branch
from .rulesets import display_rulesets, get_rulesets

# GitHub repo default values. A setting is reported in the "non-default"
# section only if its current value differs from what's listed here.
REPO_SETTING_DEFAULTS: dict[str, object] = {
    "allow_merge_commit": True,
    "allow_squash_merge": True,
    "allow_rebase_merge": True,
    "allow_auto_merge": False,
    "delete_branch_on_merge": False,
    "allow_update_branch": False,
    "web_commit_signoff_required": False,
    "has_issues": True,
    "has_projects": True,
    "has_wiki": True,
    "merge_commit_title": "MERGE_MESSAGE",
    "merge_commit_message": "PR_TITLE",
    "squash_merge_commit_title": "COMMIT_OR_PR_TITLE",
    "squash_merge_commit_message": "COMMIT_MESSAGES",
}


def _get_repo_attr(repo: object, name: str) -> object | None:
    """Read an attribute from a PyGithub Repository, returning None on failure."""
    try:
        value: object = getattr(repo, name)
    except Exception:
        return None
    return value


def check_auto_merge(repo) -> str:
    """Return a human-readable line describing the auto-merge state."""
    if get_auto_merge_status(repo):
        return "[green]enabled[/green]"
    return "[red]disabled[/red]"


def check_repo_settings(repo) -> list[tuple[str, str]]:
    """Return (setting, current_value) rows for any non-default repo setting.

    Skips settings that match GitHub's defaults. ``allow_auto_merge`` is
    intentionally reported here too even though it's also shown above, so
    users see the full merge policy in one table.
    """
    rows: list[tuple[str, str]] = []
    for name, default in REPO_SETTING_DEFAULTS.items():
        value = _get_repo_attr(repo, name)
        if value is None:
            continue
        if value != default:
            rows.append((name, str(value)))

    if has_dev_branch(repo):
        rows.append(("dev branch", "present"))

    return rows


def check_pipeline_file() -> str:
    """Return a human-readable line describing the pipeline file state."""
    if Path(".github/workflows/pipeline.yaml").exists():
        return "[green].github/workflows/pipeline.yaml exists[/green]"
    return (
        "[yellow].github/workflows/pipeline.yaml not found "
        "(run /ai-standardize-pipeline in augint-shell)[/yellow]"
    )


@click.command("status")
@click.option("--verbose", "-v", is_flag=True, help="Show additional detail.")
def status_command(verbose: bool) -> None:
    """Show repository configuration: auto-merge, non-default settings, rulesets, pipeline file."""
    gh_repo, gh_account, _ = load_env_config()
    if not gh_repo or not gh_account:
        raise click.ClickException("GH_REPO and GH_ACCOUNT must be set in .env or environment.")

    repo = get_github_repo(gh_account, gh_repo)

    print(f"\n[bold]Status: {gh_account}/{gh_repo}[/bold]\n")

    # 1. Auto-merge
    print(f"[bold]Auto-merge:[/bold] {check_auto_merge(repo)}")

    # 2. Non-default repo configuration
    non_default = check_repo_settings(repo)
    if non_default:
        table = Table(show_header=True, header_style="bold", title="Non-default settings")
        table.add_column("Setting")
        table.add_column("Value")
        for name, value in non_default:
            table.add_row(name, value)
        print(table)
    else:
        print("[dim]All repo settings are at GitHub defaults.[/dim]")

    # 3. Rulesets
    print("\n[bold]Rulesets[/bold]")
    rulesets = get_rulesets(repo)
    display_rulesets(rulesets)

    # 4. Pipeline file
    print(f"\n[bold]Pipeline:[/bold] {check_pipeline_file()}")
