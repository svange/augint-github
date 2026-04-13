from click.testing import CliRunner

from gh_secrets_and_vars_async.cli import main


class TestCLIGroup:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "chezmoi" in result.output
        assert "sync" in result.output
        assert "config" in result.output
        assert "status" in result.output
        assert "init" in result.output
        # removed commands
        assert "rulesets" not in result.output
        assert "workflow" not in result.output
        assert "push" not in result.output

    def test_sync_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["sync", "--help"])
        assert result.exit_code == 0
        assert "secrets" in result.output.lower() or "variables" in result.output.lower()

    def test_rulesets_command_removed(self):
        runner = CliRunner()
        result = runner.invoke(main, ["rulesets"])
        assert result.exit_code != 0

    def test_config_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["config", "--help"])
        assert result.exit_code == 0
        assert "auto-merge" in result.output

    def test_workflow_command_removed(self):
        runner = CliRunner()
        result = runner.invoke(main, ["workflow"])
        # Click reports "No such command 'workflow'"
        assert result.exit_code != 0

    def test_status_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output.lower() or "repository" in result.output.lower()

    def test_init_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["init", "--help"])
        assert result.exit_code == 0
        assert "bootstrap" in result.output.lower() or "init" in result.output.lower()

    def test_chezmoi_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["chezmoi", "--help"])
        assert result.exit_code == 0
        assert "chezmoi" in result.output.lower()
        assert "--no-sync" in result.output

    def test_unknown_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["nonexistent"])
        assert result.exit_code != 0
