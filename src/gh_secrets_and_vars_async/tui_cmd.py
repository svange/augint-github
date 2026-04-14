"""Click command and orchestration for the TUI dashboard."""

from __future__ import annotations

import click
from github import Github
from github.GithubException import GithubException, UnknownObjectException
from github.Repository import Repository
from loguru import logger
from rich import print
from rich.text import Text

from .common import configure_logging, get_github_client, load_env_config
from .tui_dashboard import run_dashboard


def list_repos(g: Github, owner: str) -> list[Repository]:
    """List non-archived repos for a user or organization.

    Tries organization first (which includes private repos the token
    can see), then falls back to the authenticated user's own repos.
    """
    try:
        repos = list(g.get_organization(owner).get_repos(type="all"))
    except (UnknownObjectException, GithubException):
        # Not an org -- treat as a user.  If owner matches the
        # authenticated user, get_user().get_repos() returns private
        # repos; otherwise only public repos are visible.
        repos = list(g.get_user(owner).get_repos())
    return [r for r in repos if not r.archived]


def select_org_interactive(g: Github) -> str:
    """Prompt the user to select an organization or personal account."""
    user = g.get_user()
    login: str = user.login
    orgs = list(user.get_orgs())

    if not orgs:
        return login

    print(Text.from_markup("\n[bold]Select account:[/bold]"))
    choices: list[str] = []
    for i, org in enumerate(orgs, 1):
        org_login: str = org.login
        print(f"  {i}. {org_login}")
        choices.append(org_login)
    personal_idx = len(choices) + 1
    print(f"  {personal_idx}. {login} [dim](personal)[/dim]")
    choices.append(login)

    while True:
        raw: int = click.prompt("Choice", type=int)
        if 1 <= raw <= len(choices):
            selected: str = choices[raw - 1]
            return selected
        print("[red]Invalid selection.[/red]")


def select_repos_interactive(repos: list[Repository]) -> list[Repository]:
    """Prompt the user to select repos from a numbered list."""
    if not repos:
        raise click.ClickException("No repositories found.")

    print(Text.from_markup("\n[bold]Select repositories[/bold] (comma-separated, e.g. 1,3,5):"))
    for i, repo in enumerate(repos, 1):
        print(f"  {i}. {repo.name}")

    while True:
        raw = click.prompt("Selection")
        try:
            indices = [int(x.strip()) for x in raw.split(",")]
            selected = [repos[i - 1] for i in indices if 1 <= i <= len(repos)]
        except (ValueError, IndexError):
            selected = []
        if selected:
            return selected
        print("[red]Invalid selection. Try again.[/red]")


def _warn_rate_limit(repo_count: int, refresh_seconds: int) -> None:
    """Warn if estimated API usage would exceed GitHub rate limits."""
    calls_per_repo = 7
    hourly = repo_count * calls_per_repo * (3600 // refresh_seconds)
    if hourly > 4000:
        logger.warning(
            f"Estimated ~{hourly} API calls/hour for {repo_count} repos at "
            f"{refresh_seconds}s refresh. GitHub allows 5000/hour. "
            f"Consider increasing --refresh-seconds."
        )
        print(
            f"[yellow]Warning: ~{hourly} API calls/hour estimated. "
            f"Consider using --refresh-seconds {max(refresh_seconds, 120)}.[/yellow]"
        )


@click.command("tui")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show all repos for the account/org.")
@click.option("--interactive", "-i", is_flag=True, help="Interactively select repos to monitor.")
@click.option(
    "--refresh-seconds",
    type=int,
    default=600,
    show_default=True,
    help="Refresh interval in seconds.",
)
@click.option("--org", type=str, default=None, help="Specify organization directly.")
@click.option("--verbose", "-v", is_flag=True, help="Show additional detail.")
def tui_command(
    show_all: bool,
    interactive: bool,
    refresh_seconds: int,
    org: str | None,
    verbose: bool,
) -> None:
    """Live dashboard showing pipeline status, issues, and PRs."""
    configure_logging(verbose)

    _, gh_account, _ = load_env_config()
    g = get_github_client()

    repos: list[Repository]

    if interactive:
        owner = org if org else select_org_interactive(g)
        all_repos = list_repos(g, owner)
        repos = select_repos_interactive(all_repos)
    elif show_all:
        owner = org if org else gh_account
        if not owner:
            raise click.ClickException(
                "GH_ACCOUNT must be set in .env or environment, or use --org."
            )
        repos = list_repos(g, owner)
        if not repos:
            raise click.ClickException(f"No repositories found for {owner}.")
    else:
        gh_repo, gh_account_env, _ = load_env_config()
        if not gh_repo or not gh_account_env:
            raise click.ClickException(
                "GH_REPO and GH_ACCOUNT must be set in .env or environment. "
                "Use --all or --interactive for multi-repo mode."
            )
        from .common import get_github_repo

        repos = [get_github_repo(gh_account_env, gh_repo)]

    _warn_rate_limit(len(repos), refresh_seconds)

    try:
        run_dashboard(repos, refresh_seconds)
    except KeyboardInterrupt:
        print("\n[dim]Dashboard stopped.[/dim]")
