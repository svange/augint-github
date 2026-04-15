"""Click command for the interactive panel dashboard."""

from __future__ import annotations

import click
from loguru import logger
from rich import print

from .common import configure_logging, get_github_client, load_env_config
from .tui_cmd import _warn_rate_limit, list_repos, select_org_interactive, select_repos_interactive


@click.command("panel")
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
@click.option(
    "--theme",
    type=str,
    default="default",
    show_default=True,
    help="Dashboard theme (default, cyber, minimal, matrix).",
)
@click.option(
    "--stale-days",
    type=int,
    default=5,
    show_default=True,
    help="Days before a PR is considered stale.",
)
@click.option(
    "--env-auth",
    "--dotenv-auth",
    is_flag=True,
    help="Use GH_TOKEN from .env instead of gh auth token/keyring.",
)
@click.option("--verbose", "-v", is_flag=True, help="Show additional detail.")
def panel_command(
    show_all: bool,
    interactive: bool,
    refresh_seconds: int,
    org: str | None,
    theme: str,
    stale_days: int,
    env_auth: bool,
    verbose: bool,
) -> None:
    """Interactive health dashboard for GitHub repositories."""
    configure_logging(verbose)

    try:
        from .panel_app import run_panel
    except ImportError as exc:
        raise click.ClickException(
            "textual is required for panel. Install with: uv add 'augint-github[tui]'"
        ) from exc

    from .panel_themes import THEME_NAMES

    if theme not in THEME_NAMES:
        raise click.ClickException(f"Unknown theme '{theme}'. Available: {', '.join(THEME_NAMES)}")

    _, gh_account, _ = load_env_config()
    auth_source = "dotenv" if env_auth else "auto"
    if env_auth:
        logger.debug("Panel auth mode forced to .env (--env-auth).")
    g = get_github_client(auth_source=auth_source)

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

        repos = [get_github_repo(gh_account_env, gh_repo, auth_source=auth_source)]

    _warn_rate_limit(len(repos), refresh_seconds)

    org_name = org or gh_account or ""

    health_config = {
        "stale_pr_days": stale_days,
    }

    try:
        run_panel(
            repos,
            refresh_seconds=refresh_seconds,
            theme=theme,
            health_config=health_config,
            org_name=org_name,
        )
    except KeyboardInterrupt:
        print("\n[dim]Panel stopped.[/dim]")
