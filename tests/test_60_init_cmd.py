from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from gh_secrets_and_vars_async.init_cmd import detect_repo_type, ensure_env_file, init_command


class TestDetectRepoType:
    def test_detects_library(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "pipeline.yaml").write_text("name: License compliance\njobs:")
        assert detect_repo_type() == "library"

    def test_detects_iac_sam(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "template.yaml").write_text("AWSTemplateFormatVersion: '2010-09-09'")
        assert detect_repo_type() == "iac"

    def test_detects_iac_cdk(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cdk.json").write_text("{}")
        assert detect_repo_type() == "iac"

    def test_detects_iac_terraform(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "main.tf").write_text("resource {}")
        assert detect_repo_type() == "iac"

    def test_detects_library_from_pyproject(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pyproject.toml").write_text('[build-system]\nbuild-backend = "uv_build"')
        assert detect_repo_type() == "library"

    def test_returns_none_unknown(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert detect_repo_type() is None


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
    @patch("gh_secrets_and_vars_async.init_cmd.apply_template")
    @patch("gh_secrets_and_vars_async.init_cmd.set_repo_settings")
    @patch("gh_secrets_and_vars_async.init_cmd.has_dev_branch")
    @patch("gh_secrets_and_vars_async.init_cmd.get_github_repo")
    @patch("gh_secrets_and_vars_async.init_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.init_cmd.ensure_env_file")
    def test_init_all_skip(
        self,
        mock_ensure,
        mock_env,
        mock_get_repo,
        mock_has_dev,
        mock_settings,
        mock_rulesets,
        mock_push,
    ):
        mock_ensure.return_value = ".env"
        mock_env.return_value = ("repo", "account", "token")
        repo = MagicMock()
        mock_get_repo.return_value = repo

        runner = CliRunner()
        result = runner.invoke(
            init_command,
            [
                "--type",
                "library",
                "--no-rulesets",
                "--no-config",
                "--no-push",
                "--no-workflow",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        mock_rulesets.assert_not_called()
        mock_settings.assert_not_called()
        mock_push.assert_not_called()

    @patch("gh_secrets_and_vars_async.init_cmd.perform_update")
    @patch("gh_secrets_and_vars_async.init_cmd.apply_template")
    @patch("gh_secrets_and_vars_async.init_cmd.set_repo_settings")
    @patch("gh_secrets_and_vars_async.init_cmd.has_dev_branch")
    @patch("gh_secrets_and_vars_async.init_cmd.get_github_repo")
    @patch("gh_secrets_and_vars_async.init_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.init_cmd.ensure_env_file")
    def test_init_runs_all(
        self,
        mock_ensure,
        mock_env,
        mock_get_repo,
        mock_has_dev,
        mock_settings,
        mock_rulesets,
        mock_push,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_ensure.return_value = ".env"
        mock_env.return_value = ("repo", "account", "token")
        repo = MagicMock()
        mock_get_repo.return_value = repo
        mock_has_dev.return_value = False
        mock_rulesets.return_value = [{"name": "test"}]

        mock_push.return_value = {"SECRETS": [], "VARIABLES": []}

        runner = CliRunner()
        result = runner.invoke(init_command, ["--type", "library", "--dry-run"])
        assert result.exit_code == 0
        mock_settings.assert_called_once()
        mock_rulesets.assert_called_once()

    @patch("gh_secrets_and_vars_async.init_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.init_cmd.ensure_env_file")
    def test_init_missing_token(self, mock_ensure, mock_env):
        mock_ensure.return_value = ".env"
        mock_env.return_value = ("repo", "account", "")

        runner = CliRunner()
        result = runner.invoke(init_command, ["--type", "library"])
        assert result.exit_code != 0
