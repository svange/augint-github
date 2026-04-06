from pathlib import Path

import click
from rich import print

from .common import load_template, normalize_type


@click.command("workflow")
@click.option(
    "--type",
    "workflow_type",
    type=click.Choice(["service", "library", "iac"]),
    required=True,
    help="Workflow type to generate.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(),
    default=None,
    help="Output path (default: .github/workflows/pipeline.yaml).",
)
@click.option(
    "--lang",
    "lang",
    type=click.Choice(["python", "typescript"]),
    default="python",
    help="Language/ecosystem (default: python).",
)
@click.option("--force", is_flag=True, help="Overwrite existing pipeline.yaml.")
@click.option("--dry-run", "-d", is_flag=True, help="Print to stdout instead of writing.")
def workflow_command(
    workflow_type: str, lang: str, output_path: str | None, force: bool, dry_run: bool
):
    """Generate a CI/CD pipeline.yaml aligned with ruleset status checks."""
    workflow_type = normalize_type(workflow_type)
    lang_prefix = "py" if lang == "python" else "ts"
    template_name = f"{lang_prefix}_{workflow_type}_pipeline"
    content = load_template("workflows", template_name)

    default_path = Path(".github/workflows/pipeline.yaml")
    example_path = Path(".github/workflows/example-pipeline.yaml")

    if output_path:
        target = Path(output_path)
    elif default_path.exists() and not force:
        target = example_path
        print(f"[yellow]pipeline.yaml already exists. Writing to {example_path} instead.[/yellow]")
        print("[yellow]Use --force to overwrite, or --output to specify a path.[/yellow]")
    else:
        target = default_path

    if dry_run:
        print(f"[bold]Would write to: {target}[/bold]\n")
        print(content)
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(content))
    print(f"[green]Wrote {workflow_type} pipeline to {target}[/green]")
