import click

from .push import push_command


@click.group()
def main() -> None:
    """GitHub repository setup and management tools."""


main.add_command(push_command, "sync")


def _register_subcommands() -> None:
    """Register subcommands that depend on other modules."""
    from .chezmoi_cmd import chezmoi_command
    from .config import config_command
    from .init_cmd import init_command
    from .rulesets import rulesets_command
    from .status import status_command
    from .tui_cmd import tui_command

    main.add_command(chezmoi_command, "chezmoi")
    main.add_command(rulesets_command, "rulesets")
    main.add_command(config_command, "config")
    main.add_command(status_command, "status")
    main.add_command(init_command, "init")
    main.add_command(tui_command, "tui")


_register_subcommands()
