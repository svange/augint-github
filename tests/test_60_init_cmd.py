from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from gh_secrets_and_vars_async.init_cmd import ensure_env_file, init_command


class TestEnsureEnvFile:
    def test_creates_new_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env_path = tmp_path / ".env"

        runner = CliRunner()
        runner.invoke(
            _make_test_command(ensure_env_file),
            input="myaccount\nmyrepo\nmytoken\n",
        )
        assert env_path.exists()
        content = env_path.read_text()
        assert "GH_ACCOUNT=myaccount" in content
        assert "GH_REPO=myrepo" in content
        assert "GH_TOKEN=mytoken" in content

    def test_appends_missing_vars(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env_path = tmp_path / ".env"
        env_path.write_text("GH_ACCOUNT=existing\n")

        runner = CliRunner()
        runner.invoke(
            _make_test_command(ensure_env_file),
            input="myrepo\nmytoken\n",
        )
        content = env_path.read_text()
        assert "GH_ACCOUNT=existing" in content
        assert "GH_REPO=myrepo" in content
        assert "GH_TOKEN=mytoken" in content

    def test_no_prompt_when_complete(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env_path = tmp_path / ".env"
        env_path.write_text("GH_ACCOUNT=a\nGH_REPO=r\nGH_TOKEN=t\n")

        runner = CliRunner()
        result = runner.invoke(_make_test_command(ensure_env_file))
        assert result.exit_code == 0


def _make_test_command(func):
    """Wrap a function in a Click command for CliRunner testing."""
    import click

    @click.command()
    def cmd():
        func()

    return cmd


class TestInitCommandCLI:
    @patch("gh_secrets_and_vars_async.init_cmd.perform_update")
    @patch("gh_secrets_and_vars_async.init_cmd.get_github_repo")
    @patch("gh_secrets_and_vars_async.init_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.init_cmd.ensure_env_file")
    def test_init_skip_push(
        self,
        mock_ensure,
        mock_env,
        mock_get_repo,
        mock_push,
    ):
        mock_ensure.return_value = ".env"
        mock_env.return_value = ("repo", "account", "token")
        mock_get_repo.return_value = MagicMock()

        runner = CliRunner()
        result = runner.invoke(init_command, ["--no-push", "--dry-run"])
        assert result.exit_code == 0
        mock_push.assert_not_called()

    @patch("gh_secrets_and_vars_async.init_cmd.perform_update")
    @patch("gh_secrets_and_vars_async.init_cmd.get_github_repo")
    @patch("gh_secrets_and_vars_async.init_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.init_cmd.ensure_env_file")
    def test_init_runs_push(
        self,
        mock_ensure,
        mock_env,
        mock_get_repo,
        mock_push,
    ):
        mock_ensure.return_value = ".env"
        mock_env.return_value = ("repo", "account", "token")
        mock_get_repo.return_value = MagicMock()
        mock_push.return_value = {"SECRETS": [], "VARIABLES": []}

        runner = CliRunner()
        result = runner.invoke(init_command, ["--dry-run"])
        assert result.exit_code == 0
        mock_push.assert_called_once()

    @patch("gh_secrets_and_vars_async.init_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.init_cmd.ensure_env_file")
    def test_init_missing_token(self, mock_ensure, mock_env):
        mock_ensure.return_value = ".env"
        mock_env.return_value = ("repo", "account", "")

        runner = CliRunner()
        result = runner.invoke(init_command, [])
        assert result.exit_code != 0

    @patch("gh_secrets_and_vars_async.init_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.init_cmd.ensure_env_file")
    def test_init_missing_repo(self, mock_ensure, mock_env):
        mock_ensure.return_value = ".env"
        mock_env.return_value = ("", "", "")

        runner = CliRunner()
        result = runner.invoke(init_command, [])
        assert result.exit_code != 0

    def test_init_help_has_no_removed_flags(self):
        runner = CliRunner()
        result = runner.invoke(init_command, ["--help"])
        assert result.exit_code == 0
        assert "--type" not in result.output
        assert "--lang" not in result.output
        assert "--no-config" not in result.output
        assert "--no-rulesets" not in result.output
        assert "--no-workflow" not in result.output
        assert "--batch" not in result.output
        assert "--interactive" not in result.output
