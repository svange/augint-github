"""Lightweight repo bootstrap: ensure .env and push secrets.

For full repository standardization (repo settings, rulesets, pipeline,
pre-commit, renovate, release, dotfiles) use ``/ai-standardize-repo``
from augint-shell. ai-gh init is intentionally minimal.
"""

import asyncio
from pathlib import Path

import click
from rich import print
from rich.panel import Panel
from rich.table import Table

from .common import configure_logging, get_github_repo, load_env_config
from .push import perform_update


def ensure_env_file(filename: str = ".env") -> str:
    """Ensure .env exists with required GH_* values. Prompts interactively if missing.

    Returns the filename used.
    """
    env_path = Path(filename)
    existing_lines: list[str] = []
    existing_keys: set[str] = set()

    if env_path.exists():
        existing_lines = env_path.read_text().splitlines()
        for line in existing_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                existing_keys.add(key)

    required = {
        "GH_ACCOUNT": ("GitHub account/org name", None),
        "GH_REPO": ("Repository name", Path.cwd().name),
        "GH_TOKEN": ("GitHub token (PAT)", None),
    }

    new_entries: list[str] = []
    for key, (prompt_text, default) in required.items():
        if key not in existing_keys:
            hide = key == "GH_TOKEN"
            value = click.prompt(prompt_text, default=default, hide_input=hide)
            new_entries.append(f"{key}={value}")

    if new_entries:
        with env_path.open("a") as f:
            if existing_lines and existing_lines[-1].strip():
                f.write("\n")
            f.write("\n".join(new_entries) + "\n")
        print(f"[green]Updated {filename} with {len(new_entries)} new value(s).[/green]")

    return filename


@click.command("init")
@click.option("--no-push", is_flag=True, help="Skip secrets/variables push step.")
@click.option("--verbose", "-v", is_flag=True, help="Print detailed output.")
@click.option(
    "--dry-run", "-d", is_flag=True, help="Show what would be done without making changes."
)
def init_command(no_push: bool, verbose: bool, dry_run: bool) -> None:
    """Bootstrap a GitHub repository: .env + secrets.

    For full standardization (repo settings, rulesets, pipeline, pre-commit,
    renovate, etc.) use /ai-standardize-repo from augint-shell.
    """
    configure_logging(verbose)

    filename = ensure_env_file()
    gh_repo, gh_account, gh_token = load_env_config(filename)

    if not gh_repo or not gh_account:
        raise click.ClickException("GH_REPO and GH_ACCOUNT are required.")
    if not gh_token:
        raise click.ClickException("GH_TOKEN is required.")

    try:
        get_github_repo(gh_account, gh_repo)
    except Exception as e:
        raise click.ClickException(f"Cannot connect to {gh_account}/{gh_repo}: {e}") from e

    print(f"\n[bold]Initializing {gh_account}/{gh_repo}[/bold]\n")

    summary = Table(show_header=False, box=None, padding=(0, 2))
    summary.add_column("Setting", style="bold")
    summary.add_column("Result")
    summary.add_row("Repository", f"{gh_account}/{gh_repo}")

    # Secrets push
    if not no_push:
        push_results: dict = asyncio.run(perform_update(filename, verbose, dry_run))
        total = len(push_results.get("SECRETS", [])) + len(push_results.get("VARIABLES", []))
        summary.add_row("Secrets/Vars", f"{total} synced")
    else:
        summary.add_row("Secrets/Vars", "skipped")

    print()
    print(Panel(summary, title="[bold green]Setup Complete[/bold green]", expand=False))
    print(
        "[dim]For repo settings, rulesets, pipeline, pre-commit, renovate, release, "
        "and dotfiles, run /ai-standardize-repo in augint-shell.[/dim]"
    )
