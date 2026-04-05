import asyncio
import shutil
import subprocess
from pathlib import Path

import click
from loguru import logger
from rich import print

from .common import configure_logging
from .push import perform_update


def _run_chezmoi(
    args: list[str], *, dry_run: bool = False, verbose: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a chezmoi command and return the result.

    Uses list args (not shell=True) for cross-platform compatibility.
    Raises click.ClickException on non-zero exit codes.
    """
    cmd = ["chezmoi", *args]
    if dry_run:
        print(f"[dim]\\[DRY RUN] Would run: {' '.join(cmd)}[/dim]")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    logger.debug(f"Running: {cmd}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if verbose and result.stdout:
        print(result.stdout.rstrip())

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise click.ClickException(f"chezmoi {' '.join(args)} failed: {detail}")

    return result


def _build_commit_message(project_name: str, status_output: str) -> str:
    """Build a descriptive commit message from chezmoi git status --porcelain output."""
    files = []
    for line in status_output.strip().splitlines():
        # Porcelain format: "XY filename" or "XY filename -> renamed"
        if len(line) > 3:
            files.append(line[3:].strip())

    file_list = ", ".join(files) if files else "env files"
    return f"chezmoi: sync {project_name} env files\n\nFiles: {file_list}"


@click.command("chezmoi")
@click.option("--save", is_flag=True, default=False, help="Explicit save flag (default behavior).")
@click.option("--no-sync", is_flag=True, help="Skip pushing secrets to GitHub.")
@click.option("--verbose", "-v", is_flag=True, help="Print detailed output.")
@click.option(
    "--dry-run", "-d", is_flag=True, help="Show what would be done without making changes."
)
@click.argument("filename", type=click.Path(), default=".env")
def chezmoi_command(save: bool, no_sync: bool, verbose: bool, dry_run: bool, filename: str) -> None:
    """Back up .env to chezmoi and sync secrets to GitHub."""
    configure_logging(verbose)

    # Validate chezmoi is installed
    if not shutil.which("chezmoi"):
        raise click.ClickException(
            "chezmoi is not installed. Install from https://chezmoi.io/install/"
        )

    env_path = Path(filename).resolve()

    # Validate file exists
    if not env_path.exists():
        raise click.ClickException(f"File not found: {env_path}")

    project_name = Path.cwd().name

    # Step 1: Add .env to chezmoi source
    print(f"[bold]Adding {filename} to chezmoi...[/bold]")
    _run_chezmoi(["add", str(env_path)], dry_run=dry_run, verbose=verbose)

    # Step 2: Stage changes
    _run_chezmoi(["git", "add", "--", "."], dry_run=dry_run, verbose=verbose)

    # Step 3: Check for changes
    status_result = _run_chezmoi(
        ["git", "status", "--", "--porcelain"], dry_run=dry_run, verbose=verbose
    )
    status_output = status_result.stdout.strip()

    if status_output or dry_run:
        # Step 4: Commit
        message = _build_commit_message(project_name, status_output)
        print("[bold]Committing to chezmoi...[/bold]")
        _run_chezmoi(["git", "commit", "--", "-m", message], dry_run=dry_run, verbose=verbose)

        # Step 5: Pull --rebase (safe: working tree is clean after commit)
        print("[bold]Syncing with chezmoi remote...[/bold]")
        _run_chezmoi(["git", "pull", "--", "--rebase"], dry_run=dry_run, verbose=verbose)

        # Step 6: Push
        _run_chezmoi(["git", "push"], dry_run=dry_run, verbose=verbose)
        print("[green]chezmoi backup complete.[/green]")
    else:
        print("[yellow]No chezmoi changes to commit.[/yellow]")

    # Step 7: Push secrets to GitHub
    if not no_sync:
        print("\n[bold]Syncing secrets to GitHub...[/bold]")
        results = asyncio.run(perform_update(filename, verbose, dry_run))
        total_secrets = len(results["SECRETS"])
        total_vars = len(results["VARIABLES"])
        print(f"[green]Updated {total_secrets} secrets and {total_vars} variables.[/green]")
    else:
        print("[dim]Skipping GitHub sync (--no-sync).[/dim]")
