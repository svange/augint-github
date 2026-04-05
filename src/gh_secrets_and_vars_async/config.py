import click
from loguru import logger
from rich import print

from .common import get_github_repo, load_env_config


def get_auto_merge_status(repo) -> bool:
    """Return True if auto-merge is enabled on the repository."""
    return repo.allow_auto_merge or False


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


@click.command("config")
@click.option("--status", is_flag=True, default=False, help="Show current repo settings.")
@click.option("--auto-merge/--no-auto-merge", default=None, help="Enable or disable auto-merge.")
@click.option("--verbose", "-v", is_flag=True, help="Print detailed output.")
@click.option(
    "--dry-run", "-d", is_flag=True, help="Show what would be done without making changes."
)
def config_command(status: bool, auto_merge: bool | None, verbose: bool, dry_run: bool):
    """Check or set repository configuration (auto-merge, etc.)."""
    gh_repo, gh_account, gh_token = load_env_config()
    if not gh_repo or not gh_account:
        raise click.ClickException("GH_REPO and GH_ACCOUNT must be set in .env or environment.")

    repo = get_github_repo(gh_account, gh_repo)

    if auto_merge is not None:
        set_auto_merge(repo, auto_merge, dry_run=dry_run)
    else:
        current = get_auto_merge_status(repo)
        print(f"Repository: {gh_account}/{gh_repo}")
        print(f"Auto-merge: {'enabled' if current else 'disabled'}")
