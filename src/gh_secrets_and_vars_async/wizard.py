"""Interactive setup wizard for ``ai-gh init``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import click
from loguru import logger
from rich import print
from rich.panel import Panel
from rich.table import Table

from .common import load_env_config, normalize_type
from .config import get_auto_merge_status, has_dev_branch, set_repo_settings
from .init_cmd import detect_repo_type
from .push import perform_update
from .rulesets import apply_custom_rulesets, apply_template
from .status import extract_all_workflow_jobs

WORKFLOWS_DIR = Path(".github/workflows")

# Default status checks used by the template rulesets
DEFAULT_CHECKS = {"Code quality", "Security scanning", "Unit tests", "License compliance"}

# Standard bypass actors shared by all ruleset templates
DEFAULT_BYPASS_ACTORS: list[dict] = [
    {"actor_type": "DeployKey", "bypass_mode": "always"},
    {"actor_id": 4, "actor_type": "RepositoryRole", "bypass_mode": "always"},
]


@dataclass
class WizardState:
    """Accumulates user choices throughout the wizard."""

    repo_type: str = ""
    auto_merge: bool = True
    delete_branch_on_merge: bool = True
    branch_patterns: list[str] = field(default_factory=list)
    selected_checks: list[str] = field(default_factory=list)
    generate_workflow: bool = False
    use_default_rulesets: bool = False
    push_secrets: bool = False
    workflow_lang: str = "python"


# ---------------------------------------------------------------------------
# Wizard steps
# ---------------------------------------------------------------------------


def step_repo_type(state: WizardState) -> None:
    """Detect repo type, let the user confirm or change it."""
    detected = detect_repo_type()
    if detected:
        print(f"Detected repo type: [cyan]{detected}[/cyan]")
        if click.confirm(f"Use '{detected}'?", default=True):
            state.repo_type = detected
            return

    state.repo_type = click.prompt(
        "Repository type",
        type=click.Choice(["service", "library", "iac"]),
        default="library",
    )


def step_repo_settings(repo: object, state: WizardState) -> None:
    """Show current repo settings and let user choose changes."""
    auto_merge = get_auto_merge_status(repo)
    dev = has_dev_branch(repo)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Setting", style="bold")
    table.add_column("Current")
    table.add_row("Auto-merge", "[green]enabled[/green]" if auto_merge else "[red]disabled[/red]")
    table.add_row("Dev branch", "[green]yes[/green]" if dev else "[dim]no[/dim]")
    print(Panel(table, title="[bold]Repo settings[/bold]", expand=False))

    state.auto_merge = click.confirm("Enable auto-merge?", default=True)
    state.delete_branch_on_merge = not dev
    if dev:
        print("[dim]Delete-branch-on-merge disabled (dev branch detected).[/dim]")
    else:
        state.delete_branch_on_merge = click.confirm("Delete branches on merge?", default=True)


def step_workflow_and_checks(state: WizardState) -> None:
    """Discover workflows, present jobs, let user pick required status checks."""
    discovered = extract_all_workflow_jobs(WORKFLOWS_DIR)

    if not discovered:
        print("[yellow]No workflow files found in .github/workflows/.[/yellow]")
        if click.confirm("Generate a workflow from template?", default=True):
            state.generate_workflow = True
            state.workflow_lang = click.prompt(
                "Language",
                type=click.Choice(["python", "typescript"]),
                default="python",
            )
        state.use_default_rulesets = True
        print("[dim]Default template rulesets will be applied.[/dim]")
        return

    # Build a flat, numbered list of all discovered jobs
    all_jobs: list[tuple[str, str]] = []  # (job_name, workflow_file)
    for wf_file, job_names in discovered.items():
        for name in sorted(job_names):
            all_jobs.append((name, wf_file))

    print(f"\n[bold]Discovered CI jobs ({len(all_jobs)}):[/bold]")
    for i, (name, wf_file) in enumerate(all_jobs, 1):
        default_marker = " [green](default)[/green]" if name in DEFAULT_CHECKS else ""
        print(f"  [{i}] {name}  [dim]({wf_file})[/dim]{default_marker}")

    # Pre-select defaults that exist in the discovered jobs
    default_indices = [str(i) for i, (name, _) in enumerate(all_jobs, 1) if name in DEFAULT_CHECKS]
    default_str = ",".join(default_indices) if default_indices else ""

    selection = click.prompt(
        "\nEnter job numbers for required status checks (comma-separated, or 'skip')",
        default=default_str,
    )

    if selection.strip().lower() == "skip":
        state.use_default_rulesets = True
        print("[dim]Default template rulesets will be applied.[/dim]")
        return

    # Parse selection
    try:
        indices = [int(s.strip()) for s in selection.split(",") if s.strip()]
    except ValueError:
        print("[red]Invalid input. Falling back to default template rulesets.[/red]")
        state.use_default_rulesets = True
        return

    selected: list[str] = []
    for idx in indices:
        if 1 <= idx <= len(all_jobs):
            selected.append(all_jobs[idx - 1][0])
        else:
            print(f"[yellow]Ignoring out-of-range index: {idx}[/yellow]")

    if not selected:
        print("[yellow]No valid selections. Falling back to default template rulesets.[/yellow]")
        state.use_default_rulesets = True
        return

    state.selected_checks = selected
    state.use_default_rulesets = False


def step_branch_protection(repo: object, state: WizardState) -> None:
    """Detect branches, let the user choose which to protect."""
    # Always offer ~DEFAULT_BRANCH
    options: list[str] = ["~DEFAULT_BRANCH"]

    dev = has_dev_branch(repo)
    if dev:
        options.append("refs/heads/dev")

    print("\n[bold]Branch protection[/bold]")
    for i, pattern in enumerate(options, 1):
        print(f"  [{i}] {pattern}")

    # Default: protect all detected options
    default_str = ",".join(str(i) for i in range(1, len(options) + 1))

    selection = click.prompt(
        "Enter numbers for branches to protect (comma-separated)",
        default=default_str,
    )

    selected: list[str] = []
    try:
        indices = [int(s.strip()) for s in selection.split(",") if s.strip()]
    except ValueError:
        print("[yellow]Invalid input. Protecting default branch only.[/yellow]")
        state.branch_patterns = ["~DEFAULT_BRANCH"]
        return

    for idx in indices:
        if 1 <= idx <= len(options):
            selected.append(options[idx - 1])
        else:
            print(f"[yellow]Ignoring out-of-range index: {idx}[/yellow]")

    state.branch_patterns = selected if selected else ["~DEFAULT_BRANCH"]


def step_secrets_push(state: WizardState) -> None:
    """Ask whether to sync .env secrets/variables to GitHub."""
    state.push_secrets = click.confirm("Sync .env secrets/variables to GitHub?", default=False)


# ---------------------------------------------------------------------------
# Ruleset construction
# ---------------------------------------------------------------------------


def build_rulesets(state: WizardState) -> list[dict]:
    """Construct ruleset dicts from wizard state. One per branch pattern."""
    rulesets: list[dict] = []
    for pattern in state.branch_patterns:
        if pattern == "~DEFAULT_BRANCH":
            name = f"{state.repo_type.title()} Production gate"
        elif "dev" in pattern:
            name = f"{state.repo_type.title()} Dev gate"
        else:
            name = f"Protection for {pattern}"

        ruleset: dict = {
            "name": name,
            "target": "branch",
            "enforcement": "active",
            "conditions": {
                "ref_name": {
                    "include": [pattern],
                    "exclude": [],
                },
            },
            "rules": [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "strict_required_status_checks_policy": False,
                        "do_not_enforce_on_create": False,
                        "required_status_checks": [{"context": c} for c in state.selected_checks],
                    },
                },
            ],
            "bypass_actors": list(DEFAULT_BYPASS_ACTORS),
        }
        rulesets.append(ruleset)
    return rulesets


# ---------------------------------------------------------------------------
# Plan display & execution
# ---------------------------------------------------------------------------


def show_plan(state: WizardState) -> None:
    """Display a summary of everything the wizard will do."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    table.add_row("Repo type", state.repo_type)
    table.add_row("Auto-merge", "enabled" if state.auto_merge else "disabled")
    table.add_row("Delete branch on merge", str(state.delete_branch_on_merge))
    table.add_row("Protected branches", ", ".join(state.branch_patterns) or "none")

    if state.use_default_rulesets:
        table.add_row("Rulesets", f"default template ({state.repo_type})")
    else:
        table.add_row("Status checks", ", ".join(state.selected_checks))

    if state.generate_workflow:
        table.add_row("Workflow", f"generate ({state.workflow_lang} {state.repo_type})")
    else:
        table.add_row("Workflow", "keep existing")

    table.add_row("Push secrets", "yes" if state.push_secrets else "no")

    print()
    print(Panel(table, title="[bold]Setup plan[/bold]", expand=False))


def execute_wizard_state(
    repo: object,
    state: WizardState,
    dry_run: bool = False,
    verbose: bool = False,
) -> None:
    """Apply all changes described by the wizard state."""
    import asyncio

    repo_type = normalize_type(state.repo_type)

    # 1. Repo settings
    set_repo_settings(repo, delete_branch_on_merge=state.delete_branch_on_merge, dry_run=dry_run)

    # 2. Workflow generation (if requested)
    if state.generate_workflow:
        from .workflow import workflow_command

        ctx = click.Context(workflow_command)
        ctx.invoke(
            workflow_command,
            workflow_type=repo_type,
            lang=state.workflow_lang,
            output_path=None,
            force=False,
            dry_run=dry_run,
        )

    # 3. Rulesets
    if state.use_default_rulesets:
        results = apply_template(repo, repo_type, dry_run=dry_run)
        logger.info(f"Applied {len(results)} default template ruleset(s).")
    else:
        rulesets = build_rulesets(state)
        results = apply_custom_rulesets(repo, rulesets, replace_existing=True, dry_run=dry_run)
        logger.info(f"Applied {len(results)} custom ruleset(s).")

    # 4. Secrets push
    if state.push_secrets:
        gh_repo, _gh_account, _gh_token = load_env_config()
        push_results: dict = asyncio.run(perform_update(str(gh_repo), verbose, dry_run))
        total = len(push_results.get("SECRETS", [])) + len(push_results.get("VARIABLES", []))
        print(f"Synced {total} secret(s)/variable(s).")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_wizard(
    repo: object,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    skip_config: bool = False,
    skip_rulesets: bool = False,
    skip_workflow: bool = False,
    skip_push: bool = False,
) -> WizardState:
    """Run the interactive setup wizard. Returns the accumulated state."""
    state = WizardState()

    # Repo type (always needed for naming)
    step_repo_type(state)

    # Repo settings (merge strategy, auto-merge)
    if not skip_config:
        step_repo_settings(repo, state)

    # Workflows & status checks (unless both rulesets and workflow are skipped)
    if not (skip_rulesets and skip_workflow):
        step_workflow_and_checks(state)

    # Branch protection
    if not skip_rulesets:
        step_branch_protection(repo, state)

    # Secrets push
    if not skip_push:
        step_secrets_push(state)

    return state
