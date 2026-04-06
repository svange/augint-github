from pathlib import Path

import click
from rich import print
from rich.panel import Panel
from rich.table import Table

from .common import configure_logging, get_github_repo, load_env_config, normalize_type
from .config import has_dev_branch, set_repo_settings
from .push import perform_update
from .rulesets import apply_template


def ensure_env_file(filename: str = ".env") -> str:
    """Ensure .env exists with required GH_* values. Prompts interactively if missing.

    Returns the filename used.
    """
    env_path = Path(filename)
    existing_lines = []
    existing_keys = set()

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

    new_entries = []
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


def detect_repo_type() -> str | None:
    """Auto-detect repository type based on file contents.

    Returns "library" or "service" or None if unable to detect.
    """
    pipeline = Path(".github/workflows/pipeline.yaml")
    if pipeline.exists():
        content = pipeline.read_text().lower()
        if "license compliance" in content or "pip-licenses" in content:
            return "library"
        if "sam" in content or "cdk" in content or "terraform" in content:
            return "service"

    pyproject = Path("pyproject.toml")
    if pyproject.exists():
        content = pyproject.read_text().lower()
        if "build-backend" in content:
            return "library"

    for indicator in ["template.yaml", "template.yml", "samconfig.toml", "cdk.json", "main.tf"]:
        if Path(indicator).exists():
            return "service"

    return None


@click.command("init")
@click.option(
    "--type",
    "repo_type",
    type=click.Choice(["service", "library", "iac"]),
    default=None,
    help="Repository type (auto-detected if not specified).",
)
@click.option(
    "--lang",
    "lang",
    type=click.Choice(["python", "typescript"]),
    default="python",
    help="Language/ecosystem (default: python).",
)
@click.option("--no-rulesets", is_flag=True, help="Skip ruleset setup.")
@click.option("--no-config", is_flag=True, help="Skip auto-merge setup.")
@click.option("--no-push", is_flag=True, help="Skip secrets/variables push.")
@click.option("--no-workflow", is_flag=True, help="Skip workflow generation.")
@click.option("--verbose", "-v", is_flag=True, help="Print detailed output.")
@click.option(
    "--dry-run", "-d", is_flag=True, help="Show what would be done without making changes."
)
def init_command(
    repo_type: str | None,
    lang: str,
    no_rulesets: bool,
    no_config: bool,
    no_push: bool,
    no_workflow: bool,
    verbose: bool,
    dry_run: bool,
):
    """Initialize a GitHub repository with rulesets, auto-merge, and secrets."""
    configure_logging(verbose)
    import asyncio

    from .workflow import workflow_command

    # Step 1: Ensure .env
    filename = ensure_env_file()
    gh_repo, gh_account, gh_token = load_env_config(filename)

    if not gh_repo or not gh_account:
        raise click.ClickException("GH_REPO and GH_ACCOUNT are required.")
    if not gh_token:
        raise click.ClickException("GH_TOKEN is required.")

    # Step 2: Validate connection
    try:
        repo = get_github_repo(gh_account, gh_repo)
    except Exception as e:
        raise click.ClickException(f"Cannot connect to {gh_account}/{gh_repo}: {e}") from e

    print(f"\n[bold]Initializing {gh_account}/{gh_repo}[/bold]\n")

    # Step 3: Detect or prompt for repo type
    if not repo_type:
        detected = detect_repo_type()
        if detected:
            repo_type = detected
            print(f"Auto-detected repo type: [cyan]{repo_type}[/cyan]")
        else:
            repo_type = click.prompt(
                "Repository type",
                type=click.Choice(["service", "library", "iac"]),
                default="library",
            )

    repo_type = normalize_type(repo_type)

    summary = Table(show_header=False, box=None, padding=(0, 2))
    summary.add_column("Setting", style="bold")
    summary.add_column("Result")
    summary.add_row("Repository", f"{gh_account}/{gh_repo}")
    summary.add_row("Type", repo_type)

    # Step 4: Repo settings (merge strategy, auto-merge, branch deletion)
    if not no_config:
        dev = has_dev_branch(repo)
        set_repo_settings(repo, delete_branch_on_merge=not dev, dry_run=dry_run)
        summary.add_row("Merge strategy", "merge commits only")
        summary.add_row("Delete branch on merge", str(not dev))
    else:
        summary.add_row("Repo settings", "skipped")

    # Step 5: Rulesets
    if not no_rulesets:
        results = apply_template(repo, repo_type, dry_run=dry_run)
        summary.add_row("Rulesets", f"{len(results)} applied ({repo_type})")
    else:
        summary.add_row("Rulesets", "skipped")

    # Step 6: Workflow
    if not no_workflow:
        ctx = click.Context(workflow_command)
        ctx.invoke(
            workflow_command,
            workflow_type=repo_type,
            lang=lang,
            output_path=None,
            force=False,
            dry_run=dry_run,
        )
        summary.add_row("Workflow", "generated")
    else:
        summary.add_row("Workflow", "skipped")

    # Step 7: Push secrets/vars
    if not no_push:
        push_results: dict = asyncio.run(perform_update(filename, verbose, dry_run))
        total = len(push_results["SECRETS"]) + len(push_results["VARIABLES"])
        summary.add_row("Secrets/Vars", f"{total} synced")
    else:
        summary.add_row("Secrets/Vars", "skipped")

    print()
    print(Panel(summary, title="[bold green]Setup Complete[/bold green]", expand=False))
