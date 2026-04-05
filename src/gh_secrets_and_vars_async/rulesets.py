import click
from loguru import logger
from rich import print
from rich.panel import Panel
from rich.table import Table

from .common import get_github_repo, load_env_config, load_template


def get_rulesets(repo) -> list[dict]:
    """Fetch all rulesets for the repository."""
    _headers, data = repo._requester.requestJsonAndCheck("GET", f"{repo.url}/rulesets")
    return list(data)


def delete_all_rulesets(repo, dry_run: bool = False) -> int:
    """Delete all existing rulesets. Returns count of deleted rulesets."""
    rulesets = get_rulesets(repo)
    count = 0
    for ruleset in rulesets:
        if dry_run:
            logger.info(f"[DRY RUN] Would delete ruleset: {ruleset['name']} (id={ruleset['id']})")
        else:
            repo._requester.requestJsonAndCheck("DELETE", f"{repo.url}/rulesets/{ruleset['id']}")
            logger.info(f"Deleted ruleset: {ruleset['name']} (id={ruleset['id']})")
        count += 1
    return count


def create_ruleset(repo, template: dict, dry_run: bool = False) -> dict | None:
    """Create a new ruleset from a template dict."""
    # Remove fields that are repo-specific metadata, not part of the creation payload
    payload = {k: v for k, v in template.items() if k not in ("id", "source_type", "source")}
    if dry_run:
        logger.info(f"[DRY RUN] Would create ruleset: {payload.get('name', 'unknown')}")
        return payload
    _headers, data = repo._requester.requestJsonAndCheck(
        "POST", f"{repo.url}/rulesets", input=payload
    )
    result: dict = data
    logger.info(f"Created ruleset: {result.get('name', 'unknown')} (id={result.get('id', '?')})")
    return result


def apply_template(repo, template_name: str, dry_run: bool = False) -> list[dict]:
    """Apply a ruleset template set. Deletes all existing rulesets first.

    Args:
        repo: GitHub Repository object.
        template_name: "iac" or "library".
        dry_run: If True, no changes are made.

    Returns:
        List of created ruleset dicts.
    """
    deleted = delete_all_rulesets(repo, dry_run=dry_run)
    if deleted:
        print(f"Removed {deleted} existing ruleset(s).")

    if template_name == "iac":
        template_dicts: list[dict] = [
            load_template("rulesets", "iac_dev"),  # type: ignore[list-item]
            load_template("rulesets", "iac_production"),  # type: ignore[list-item]
        ]
    elif template_name == "library":
        template_dicts = [
            load_template("rulesets", "publishable_library"),  # type: ignore[list-item]
        ]
    else:
        raise click.BadParameter(f"Unknown template: {template_name}. Use 'iac' or 'library'.")

    results: list[dict] = []
    for tmpl in template_dicts:
        result = create_ruleset(repo, tmpl, dry_run=dry_run)
        if result is not None:
            results.append(result)

    return results


def display_rulesets(rulesets: list[dict]) -> None:
    """Pretty-print rulesets using Rich."""
    if not rulesets:
        print("[yellow]No rulesets configured for this repository.[/yellow]")
        return

    for rs in rulesets:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Field", style="bold cyan")
        table.add_column("Value")

        table.add_row("Enforcement", rs.get("enforcement", "unknown"))

        conditions = rs.get("conditions", {}).get("ref_name", {})
        branches = ", ".join(conditions.get("include", []))
        table.add_row("Branches", branches or "none")

        rules = rs.get("rules", [])
        rule_types = []
        for rule in rules:
            if rule["type"] == "required_status_checks":
                checks = rule.get("parameters", {}).get("required_status_checks", [])
                check_names = [c["context"] for c in checks]
                rule_types.append(f"status_checks: {', '.join(check_names)}")
            else:
                rule_types.append(rule["type"])
        table.add_row("Rules", "\n".join(rule_types))

        bypass = rs.get("bypass_actors", [])
        bypass_desc = [f"{b.get('actor_type', '?')} ({b.get('bypass_mode', '?')})" for b in bypass]
        table.add_row("Bypass", ", ".join(bypass_desc) if bypass_desc else "none")

        print(Panel(table, title=f"[bold]{rs.get('name', 'Unnamed')}[/bold]", expand=False))


@click.command("rulesets")
@click.option("--view", is_flag=True, default=False, help="Show current rulesets.")
@click.option(
    "--apply",
    "apply_template_name",
    type=click.Choice(["iac", "library"]),
    default=None,
    help="Apply a ruleset template (replaces all existing rulesets).",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed output.")
@click.option(
    "--dry-run", "-d", is_flag=True, help="Show what would be done without making changes."
)
def rulesets_command(view: bool, apply_template_name: str | None, verbose: bool, dry_run: bool):
    """View or apply branch rulesets to a GitHub repository."""
    gh_repo, gh_account, gh_token = load_env_config()
    if not gh_repo or not gh_account:
        raise click.ClickException("GH_REPO and GH_ACCOUNT must be set in .env or environment.")

    repo = get_github_repo(gh_account, gh_repo)

    if apply_template_name:
        results = apply_template(repo, apply_template_name, dry_run=dry_run)
        print(
            f"\n[green]Applied '{apply_template_name}' template ({len(results)} ruleset(s)).[/green]"
        )
        if verbose:
            display_rulesets(results)
    else:
        rulesets = get_rulesets(repo)
        display_rulesets(rulesets)
