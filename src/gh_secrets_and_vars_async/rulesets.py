"""Read-only rulesets helpers used by ``ai-gh status``.

Mutating operations (apply, delete) have been removed -- callers should
use ``gh api repos/{owner}/{repo}/rulesets`` directly.
"""

from rich import print
from rich.panel import Panel
from rich.table import Table


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
