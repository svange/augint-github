import click
from github.GithubException import GithubException
from loguru import logger
from rich import print

from .common import configure_logging, get_github_repo, load_env_config


def get_auto_merge_status(repo) -> bool:
    """Return True if auto-merge is enabled on the repository."""
    return repo.allow_auto_merge or False


def has_dev_branch(repo) -> bool:
    """Check if the repository has a dev branch."""
    try:
        repo.get_branch("dev")
        return True
    except GithubException:
        return False


def set_auto_merge(repo, enabled: bool, dry_run: bool = False) -> None:
    """Enable or disable auto-merge on the repository."""
    current = get_auto_merge_status(repo)
    action = "enable" if enabled else "disable"

    if current == enabled:
        print(f"Auto-merge is already {'enabled' if enabled else 'disabled'}.")
        return

    if dry_run:
        logger.info(f"[DRY RUN] Would {action} auto-merge.")
    else:
        repo.edit(allow_auto_merge=enabled)
        logger.info(f"Auto-merge {action}d.")

    print(f"Auto-merge: {'enabled' if enabled else 'disabled'}")


def set_repo_settings(repo, delete_branch_on_merge: bool, dry_run: bool = False) -> None:
    """Apply standardized repository merge and auto-merge settings.

    Enforces merge commits only (no squash/rebase), PR_TITLE/PR_BODY format,
    auto-merge enabled, and configurable branch deletion on merge.
    """
    if dry_run:
        logger.info(
            f"[DRY RUN] Would set: merge commits only, "
            f"delete_branch_on_merge={delete_branch_on_merge}"
        )
        print(
            f"[dim]Would apply standard settings "
            f"(delete_branch_on_merge={delete_branch_on_merge})[/dim]"
        )
        return

    repo.edit(
        allow_merge_commit=True,
        allow_squash_merge=False,
        allow_rebase_merge=False,
        allow_auto_merge=True,
        merge_commit_title="PR_TITLE",
        merge_commit_message="PR_BODY",
        delete_branch_on_merge=delete_branch_on_merge,
    )
    logger.info("Repository settings updated.")
    print(
        f"Merge: commits only (PR_TITLE / PR_BODY), delete_branch_on_merge={delete_branch_on_merge}"
    )


def display_repo_settings(repo, gh_account: str, gh_repo: str) -> None:
    """Display current repository settings."""
    print(f"Repository: {gh_account}/{gh_repo}")
    print(f"  Auto-merge: {'enabled' if get_auto_merge_status(repo) else 'disabled'}")
    print(f"  Merge commit: {'allowed' if repo.allow_merge_commit else 'disabled'}")
    print(f"  Squash merge: {'allowed' if repo.allow_squash_merge else 'disabled'}")
    print(f"  Rebase merge: {'allowed' if repo.allow_rebase_merge else 'disabled'}")
    print(f"  Delete branch on merge: {repo.delete_branch_on_merge}")


@click.command("config")
@click.option("--status", is_flag=True, default=False, help="Show current repo settings.")
@click.option("--auto-merge/--no-auto-merge", default=None, help="Enable or disable auto-merge.")
@click.option(
    "--standardize",
    is_flag=True,
    help="Apply standard merge settings (merge commits only, auto-merge, PR_TITLE).",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed output.")
@click.option(
    "--dry-run", "-d", is_flag=True, help="Show what would be done without making changes."
)
def config_command(
    status: bool, auto_merge: bool | None, standardize: bool, verbose: bool, dry_run: bool
):
    """Check or set repository configuration (merge strategy, auto-merge, etc.)."""
    configure_logging(verbose)
    gh_repo, gh_account, gh_token = load_env_config()
    if not gh_repo or not gh_account:
        raise click.ClickException("GH_REPO and GH_ACCOUNT must be set in .env or environment.")

    repo = get_github_repo(gh_account, gh_repo)

    if standardize:
        dev = has_dev_branch(repo)
        set_repo_settings(repo, delete_branch_on_merge=not dev, dry_run=dry_run)
    elif auto_merge is not None:
        set_auto_merge(repo, auto_merge, dry_run=dry_run)
    else:
        display_repo_settings(repo, gh_account, gh_repo)
