"""Thin rulesets command: view or safely apply a caller-supplied spec.

ai-gh holds no ruleset template knowledge. Callers (e.g. augint-shell skills)
generate a ruleset spec in-context and hand it to ``ai-gh rulesets apply``,
which finds the repo-scope branch ruleset with a matching name and replaces
only that one -- never touching org-inherited, repository-scope, or tag-scope
rulesets.
"""

import json
from pathlib import Path

import click
from loguru import logger
from rich import print
from rich.panel import Panel
from rich.table import Table

from .common import (
    configure_logging,
    get_github_repo,
    load_env_config,
)

REQUIRED_SPEC_FIELDS = ("name", "target", "rules")


def get_rulesets(repo) -> list[dict]:
    """Fetch all rulesets for the repository with full details.

    The list endpoint only returns summaries. We fetch each ruleset
    individually to get conditions, rules, and bypass actors.
    """
    _headers, summaries = repo._requester.requestJsonAndCheck("GET", f"{repo.url}/rulesets")
    rulesets = []
    for summary in summaries:
        _h, detail = repo._requester.requestJsonAndCheck(
            "GET", f"{repo.url}/rulesets/{summary['id']}"
        )
        rulesets.append(dict(detail))
    return rulesets


def validate_ruleset_spec(spec: object) -> None:
    """Fail fast on a malformed spec. Raises click.ClickException with a clear message."""
    if not isinstance(spec, dict):
        raise click.ClickException("Ruleset spec must be a JSON object (dict).")

    for field in REQUIRED_SPEC_FIELDS:
        if field not in spec:
            raise click.ClickException(f"Ruleset spec is missing required field: '{field}'.")

    name = spec.get("name")
    if not isinstance(name, str) or not name.strip():
        raise click.ClickException("Ruleset spec 'name' must be a non-empty string.")

    target = spec.get("target")
    if target != "branch":
        raise click.ClickException(
            f"Ruleset spec 'target' must be 'branch' (got {target!r}). "
            "ai-gh only applies branch-scope rulesets."
        )

    rules = spec.get("rules")
    if not isinstance(rules, list):
        raise click.ClickException("Ruleset spec 'rules' must be a list.")


def find_replaceable_ruleset(repo, name: str) -> dict | None:
    """Find the one repo-scope branch ruleset whose name matches.

    Safety filters (the T0-1 fix):
    - ``target == "branch"`` -- never touch repository or tag scope.
    - ``source_type == "Repository"`` -- never touch org-inherited rulesets.
    - ``name`` exact match -- never touch unrelated rulesets.
    """
    for rs in get_rulesets(repo):
        if rs.get("target") != "branch":
            continue
        source_type = rs.get("source_type")
        if source_type and source_type != "Repository":
            continue
        if rs.get("name") != name:
            continue
        return rs
    return None


def _canonical_ruleset(rs: dict) -> dict:
    """Normalize a ruleset for structural comparison.

    Strips id/source/source_type metadata and sorts rules and bypass_actors
    so API-returned ordering differences don't cause false drift.
    """

    def _rule_sort_key(rule: dict) -> str:
        return str(rule.get("type", ""))

    def _actor_sort_key(actor: dict) -> tuple[str, int]:
        return (str(actor.get("actor_type", "")), int(actor.get("actor_id", 0) or 0))

    def _normalize_rule(rule: dict) -> dict:
        rtype = rule.get("type")
        if rtype == "required_status_checks":
            params = dict(rule.get("parameters", {}))
            checks = params.get("required_status_checks", [])
            params["required_status_checks"] = sorted(
                checks, key=lambda c: str(c.get("context", ""))
            )
            return {"type": rtype, "parameters": params}
        return {"type": rtype, "parameters": rule.get("parameters", {})}

    return {
        "name": rs.get("name"),
        "target": rs.get("target"),
        "enforcement": rs.get("enforcement"),
        "conditions": rs.get("conditions", {}),
        "rules": sorted((_normalize_rule(r) for r in rs.get("rules", [])), key=_rule_sort_key),
        "bypass_actors": sorted(rs.get("bypass_actors", []), key=_actor_sort_key),
    }


def rulesets_match(existing: dict, spec: dict) -> bool:
    """Return True if existing ruleset is already structurally equal to spec."""
    return _canonical_ruleset(existing) == _canonical_ruleset(spec)


def create_ruleset(repo, spec: dict, dry_run: bool = False) -> dict | None:
    """POST a new ruleset from a spec dict. Strips repo-specific metadata first."""
    payload = {k: v for k, v in spec.items() if k not in ("id", "source_type", "source")}
    if dry_run:
        logger.info(f"[DRY RUN] Would create ruleset: {payload.get('name', 'unknown')}")
        return payload
    _headers, data = repo._requester.requestJsonAndCheck(
        "POST", f"{repo.url}/rulesets", input=payload
    )
    result: dict = data
    logger.info(f"Created ruleset: {result.get('name', 'unknown')} (id={result.get('id', '?')})")
    return result


def apply_ruleset_spec(repo, spec: dict, dry_run: bool = False) -> dict | None:
    """Apply one ruleset spec safely and idempotently.

    - Validates the spec.
    - Finds a replaceable repo-scope branch ruleset with the same name.
    - If none found: create.
    - If found and already structurally equal: no-op.
    - If found but drifted: DELETE that one, then create the new version.

    Never touches org-inherited, repository-scope, or tag-scope rulesets.
    """
    validate_ruleset_spec(spec)
    name = spec["name"]

    existing = find_replaceable_ruleset(repo, name)

    if existing is not None and rulesets_match(existing, spec):
        logger.info(f"Ruleset '{name}' already up-to-date (id={existing.get('id', '?')}).")
        print(f"[green]Ruleset '{name}' is up-to-date. No changes.[/green]")
        return existing

    if existing is not None:
        rs_id = existing.get("id")
        if dry_run:
            logger.info(f"[DRY RUN] Would delete drifted ruleset '{name}' (id={rs_id})")
        else:
            repo._requester.requestJsonAndCheck("DELETE", f"{repo.url}/rulesets/{rs_id}")
            logger.info(f"Deleted drifted ruleset '{name}' (id={rs_id})")

    return create_ruleset(repo, spec, dry_run=dry_run)


def display_rulesets(rulesets: list[dict]) -> None:
    """Pretty-print rulesets using Rich.

    Shows name, enforcement, target, source_type (so org-inherited vs
    repo-owned is visible), branch patterns, rules, and bypass actors.
    """
    if not rulesets:
        print("[yellow]No rulesets configured for this repository.[/yellow]")
        return

    for rs in rulesets:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Field", style="bold cyan")
        table.add_column("Value")

        table.add_row("Enforcement", str(rs.get("enforcement", "unknown")))
        table.add_row("Target", str(rs.get("target", "unknown")))
        table.add_row("Source", str(rs.get("source_type", "Repository")))

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
        table.add_row("Rules", "\n".join(rule_types) if rule_types else "none")

        bypass = rs.get("bypass_actors", [])
        bypass_desc = [f"{b.get('actor_type', '?')} ({b.get('bypass_mode', '?')})" for b in bypass]
        table.add_row("Bypass", ", ".join(bypass_desc) if bypass_desc else "none")

        print(Panel(table, title=f"[bold]{rs.get('name', 'Unnamed')}[/bold]", expand=False))


@click.group("rulesets")
def rulesets_command() -> None:
    """View or apply branch rulesets to a GitHub repository."""


@rulesets_command.command("view")
@click.option("--verbose", "-v", is_flag=True, help="Print detailed output.")
def view_cmd(verbose: bool) -> None:
    """Show the current rulesets on the repository."""
    configure_logging(verbose)
    gh_repo, gh_account, _ = load_env_config()
    if not gh_repo or not gh_account:
        raise click.ClickException("GH_REPO and GH_ACCOUNT must be set in .env or environment.")
    repo = get_github_repo(gh_account, gh_repo)
    rulesets = get_rulesets(repo)
    display_rulesets(rulesets)


@rulesets_command.command("apply")
@click.argument(
    "spec_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--dry-run", "-d", is_flag=True, help="Show what would be done without making changes."
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed output.")
def apply_cmd(spec_path: Path, dry_run: bool, verbose: bool) -> None:
    """Apply a caller-supplied ruleset JSON spec to the repository.

    SPEC_PATH must point to a JSON file containing a single ruleset object
    conforming to GitHub's ruleset schema. The spec's 'name' is the match key:
    an existing repo-scope branch ruleset with the same name is replaced
    surgically. Org-inherited and non-branch rulesets are never touched.
    """
    configure_logging(verbose)

    try:
        raw = spec_path.read_text()
    except OSError as e:
        raise click.ClickException(f"Cannot read spec file {spec_path}: {e}") from e

    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Spec file {spec_path} is not valid JSON: {e}") from e

    validate_ruleset_spec(spec)

    gh_repo, gh_account, _ = load_env_config()
    if not gh_repo or not gh_account:
        raise click.ClickException("GH_REPO and GH_ACCOUNT must be set in .env or environment.")
    repo = get_github_repo(gh_account, gh_repo)

    try:
        result = apply_ruleset_spec(repo, spec, dry_run=dry_run)
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Failed to apply ruleset spec: {e}") from e

    if result is not None and verbose:
        display_rulesets([result])
