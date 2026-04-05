from click.testing import CliRunner

from gh_secrets_and_vars_async.cli import main


class TestCLIGroup:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "chezmoi" in result.output
        assert "sync" in result.output
        assert "rulesets" in result.output
        assert "config" in result.output
        assert "workflow" in result.output
        assert "status" in result.output
        assert "init" in result.output
        # push was removed in favor of sync
        assert "push" not in result.output

    def test_sync_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["sync", "--help"])
        assert result.exit_code == 0
        assert "secrets" in result.output.lower() or "variables" in result.output.lower()

    def test_rulesets_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["rulesets", "--help"])
        assert result.exit_code == 0
        assert "rulesets" in result.output.lower()

    def test_config_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["config", "--help"])
        assert result.exit_code == 0
        assert "auto-merge" in result.output

    def test_workflow_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["workflow", "--help"])
        assert result.exit_code == 0
        assert "pipeline" in result.output.lower() or "workflow" in result.output.lower()

    def test_status_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0
        assert "audit" in result.output.lower() or "status" in result.output.lower()

    def test_init_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["init", "--help"])
        assert result.exit_code == 0
        assert "rulesets" in result.output.lower() or "initialize" in result.output.lower()

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
