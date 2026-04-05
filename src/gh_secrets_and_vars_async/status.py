import re
from pathlib import Path

import click
from rich import print
from rich.table import Table

from .common import get_github_repo, load_env_config, load_template
from .config import get_auto_merge_status
from .init_cmd import detect_repo_type
from .rulesets import get_rulesets

PASS = "[green]PASS[/green]"
FAIL = "[red]FAIL[/red]"
WARN = "[yellow]WARN[/yellow]"


def _expected_check_names(repo_type: str) -> set[str]:
    """Get the set of expected status check context names for a repo type."""
    if repo_type == "iac":
        template_names = ["iac_dev", "iac_production"]
    else:
        template_names = ["publishable_library"]

    names: set[str] = set()
    for tname in template_names:
        tmpl: dict = load_template("rulesets", tname)  # type: ignore[assignment]
        for rule in tmpl.get("rules", []):
            if rule["type"] == "required_status_checks":
                for check in rule.get("parameters", {}).get("required_status_checks", []):
                    names.add(check["context"])
    return names


def _expected_rulesets(repo_type: str) -> list[dict]:
    """Load expected ruleset templates for a repo type."""
    if repo_type == "iac":
        return [
            load_template("rulesets", "iac_dev"),  # type: ignore[list-item]
            load_template("rulesets", "iac_production"),  # type: ignore[list-item]
        ]
    return [load_template("rulesets", "publishable_library")]  # type: ignore[list-item]


def _extract_pipeline_job_names(pipeline_path: Path) -> set[str]:
    """Extract job name: values from a pipeline YAML without a YAML parser."""
    if not pipeline_path.exists():
        return set()

    content = pipeline_path.read_text()
    names: set[str] = set()
    in_jobs = False
    for line in content.splitlines():
        # Detect the top-level "jobs:" key
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        # A top-level key that isn't "jobs:" ends the jobs section
        if in_jobs and re.match(r"^[a-zA-Z]", line) and not line.startswith(" "):
            in_jobs = False
            continue
        if in_jobs:
            match = re.match(r"^\s+name:\s+(.+)$", line)
            if match:
                name = match.group(1).strip().strip("'\"")
                names.add(name)
    return names


def check_auto_merge(repo) -> tuple[str, str]:
    """Check auto-merge setting. Returns (status_icon, message)."""
    enabled = get_auto_merge_status(repo)
    if enabled:
        return PASS, "Auto-merge is enabled"
    return FAIL, "Auto-merge is disabled (run: ai-gh config --auto-merge)"


def check_rulesets(repo, repo_type: str) -> list[tuple[str, str]]:
    """Check rulesets against expected templates. Returns list of (status, message)."""
    results: list[tuple[str, str]] = []
    current = get_rulesets(repo)
    expected = _expected_rulesets(repo_type)

    current_names = {r["name"] for r in current}
    expected_names = {e["name"] for e in expected}

    for name in expected_names - current_names:
        results.append((FAIL, f"Missing ruleset: {name}"))

    for name in current_names - expected_names:
        results.append((WARN, f"Extra ruleset: {name} (not in template)"))

    for exp in expected:
        matching = [r for r in current if r["name"] == exp["name"]]
        if not matching:
            continue

        actual = matching[0]

        # Compare branches
        exp_branches = set(exp.get("conditions", {}).get("ref_name", {}).get("include", []))
        act_branches = set(actual.get("conditions", {}).get("ref_name", {}).get("include", []))
        if exp_branches != act_branches:
            results.append(
                (
                    FAIL,
                    f"{exp['name']}: branches mismatch (expected {exp_branches}, got {act_branches})",
                )
            )

        # Compare status checks
        exp_checks: set[str] = set()
        act_checks: set[str] = set()
        for rule in exp.get("rules", []):
            if rule["type"] == "required_status_checks":
                exp_checks = {c["context"] for c in rule["parameters"]["required_status_checks"]}
        for rule in actual.get("rules", []):
            if rule["type"] == "required_status_checks":
                act_checks = {
                    c["context"]
                    for c in rule.get("parameters", {}).get("required_status_checks", [])
                }

        for check in exp_checks - act_checks:
            results.append((FAIL, f"{exp['name']}: missing status check '{check}'"))
        for check in act_checks - exp_checks:
            results.append((WARN, f"{exp['name']}: extra status check '{check}'"))

        if exp_checks == act_checks and exp_branches == act_branches:
            results.append((PASS, f"{exp['name']}: matches template"))

    return results


def check_pipeline_file() -> tuple[str, str]:
    """Check if pipeline.yaml exists."""
    if Path(".github/workflows/pipeline.yaml").exists():
        return PASS, "pipeline.yaml exists"
    return FAIL, "pipeline.yaml not found (run: ai-gh workflow --type <type>)"


def check_pipeline_stages(repo_type: str) -> list[tuple[str, str]]:
    """Check pipeline job names against expected status check names."""
    results: list[tuple[str, str]] = []
    pipeline_path = Path(".github/workflows/pipeline.yaml")

    if not pipeline_path.exists():
        results.append((FAIL, "Cannot check stages: pipeline.yaml missing"))
        return results

    actual_names = _extract_pipeline_job_names(pipeline_path)
    expected_names = _expected_check_names(repo_type)

    for name in expected_names - actual_names:
        results.append((FAIL, f"Missing pipeline stage: '{name}'"))
    # Non-gate stages (release, publish, docs) are expected extras -- not flagged

    if expected_names <= actual_names:
        results.append((PASS, "All required pipeline stages present"))

    return results


@click.command("status")
@click.option(
    "--type",
    "repo_type",
    type=click.Choice(["iac", "library"]),
    default=None,
    help="Repository type (auto-detected if not specified).",
)
@click.option("--verbose", "-v", is_flag=True, help="Show passing checks too.")
def status_command(repo_type: str | None, verbose: bool):
    """Audit repository configuration against standard templates."""
    gh_repo, gh_account, gh_token = load_env_config()
    if not gh_repo or not gh_account:
        raise click.ClickException("GH_REPO and GH_ACCOUNT must be set in .env or environment.")

    repo = get_github_repo(gh_account, gh_repo)

    if not repo_type:
        detected = detect_repo_type()
        if detected:
            repo_type = detected
        else:
            repo_type = "library"
            print("[yellow]Could not auto-detect repo type, defaulting to 'library'[/yellow]")

    print(f"\n[bold]Status: {gh_account}/{gh_repo}[/bold] (type: {repo_type})\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Status", width=6)
    table.add_column("Check")

    all_checks: list[tuple[str, str]] = []

    # Auto-merge
    all_checks.append(check_auto_merge(repo))

    # Rulesets
    all_checks.extend(check_rulesets(repo, repo_type))

    # Pipeline file
    all_checks.append(check_pipeline_file())

    # Pipeline stages
    all_checks.extend(check_pipeline_stages(repo_type))

    for status, message in all_checks:
        if verbose or status != PASS:
            table.add_row(status, message)

    if not verbose and all(s == PASS for s, _ in all_checks):
        print("[green]All checks pass.[/green]")
    else:
        print(table)

    failures = sum(1 for s, _ in all_checks if s == FAIL)
    warnings = sum(1 for s, _ in all_checks if s == WARN)
    passes = sum(1 for s, _ in all_checks if s == PASS)
    print(f"\n{passes} passed, {warnings} warnings, {failures} failed")
