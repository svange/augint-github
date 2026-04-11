from unittest.mock import MagicMock, PropertyMock, patch

from click.testing import CliRunner

from gh_secrets_and_vars_async.status import (
    check_auto_merge,
    check_pipeline_file,
    check_repo_settings,
    status_command,
)


class TestCheckAutoMerge:
    def test_enabled(self):
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=True)
        assert "enabled" in check_auto_merge(repo)

    def test_disabled(self):
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=False)
        assert "disabled" in check_auto_merge(repo)


class TestCheckRepoSettings:
    @patch("gh_secrets_and_vars_async.status.has_dev_branch")
    def test_all_defaults_returns_empty(self, mock_dev):
        """A repo at GitHub defaults should produce no rows."""
        mock_dev.return_value = False
        repo = MagicMock()
        type(repo).allow_merge_commit = PropertyMock(return_value=True)
        type(repo).allow_squash_merge = PropertyMock(return_value=True)
        type(repo).allow_rebase_merge = PropertyMock(return_value=True)
        type(repo).allow_auto_merge = PropertyMock(return_value=False)
        type(repo).delete_branch_on_merge = PropertyMock(return_value=False)
        type(repo).allow_update_branch = PropertyMock(return_value=False)
        type(repo).web_commit_signoff_required = PropertyMock(return_value=False)
        type(repo).has_issues = PropertyMock(return_value=True)
        type(repo).has_projects = PropertyMock(return_value=True)
        type(repo).has_wiki = PropertyMock(return_value=True)
        type(repo).merge_commit_title = PropertyMock(return_value="MERGE_MESSAGE")
        type(repo).merge_commit_message = PropertyMock(return_value="PR_TITLE")
        type(repo).squash_merge_commit_title = PropertyMock(return_value="COMMIT_OR_PR_TITLE")
        type(repo).squash_merge_commit_message = PropertyMock(return_value="COMMIT_MESSAGES")
        assert check_repo_settings(repo) == []

    @patch("gh_secrets_and_vars_async.status.has_dev_branch")
    def test_reports_non_default_merge_strategy(self, mock_dev):
        mock_dev.return_value = False
        repo = MagicMock()
        type(repo).allow_merge_commit = PropertyMock(return_value=True)
        type(repo).allow_squash_merge = PropertyMock(return_value=False)  # non-default
        type(repo).allow_rebase_merge = PropertyMock(return_value=False)  # non-default
        type(repo).allow_auto_merge = PropertyMock(return_value=True)  # non-default
        type(repo).delete_branch_on_merge = PropertyMock(return_value=True)  # non-default
        type(repo).allow_update_branch = PropertyMock(return_value=False)
        type(repo).web_commit_signoff_required = PropertyMock(return_value=False)
        type(repo).has_issues = PropertyMock(return_value=True)
        type(repo).has_projects = PropertyMock(return_value=True)
        type(repo).has_wiki = PropertyMock(return_value=True)
        type(repo).merge_commit_title = PropertyMock(return_value="PR_TITLE")  # non-default
        type(repo).merge_commit_message = PropertyMock(return_value="PR_BODY")  # non-default
        type(repo).squash_merge_commit_title = PropertyMock(return_value="COMMIT_OR_PR_TITLE")
        type(repo).squash_merge_commit_message = PropertyMock(return_value="COMMIT_MESSAGES")
        rows = check_repo_settings(repo)
        names = {name for name, _ in rows}
        assert "allow_squash_merge" in names
        assert "allow_rebase_merge" in names
        assert "allow_auto_merge" in names
        assert "delete_branch_on_merge" in names
        assert "merge_commit_title" in names
        assert "merge_commit_message" in names
        assert "allow_merge_commit" not in names  # still default

    @patch("gh_secrets_and_vars_async.status.has_dev_branch")
    def test_reports_dev_branch(self, mock_dev):
        mock_dev.return_value = True
        repo = MagicMock()
        # All attrs at defaults
        for attr, val in [
            ("allow_merge_commit", True),
            ("allow_squash_merge", True),
            ("allow_rebase_merge", True),
            ("allow_auto_merge", False),
            ("delete_branch_on_merge", False),
            ("allow_update_branch", False),
            ("web_commit_signoff_required", False),
            ("has_issues", True),
            ("has_projects", True),
            ("has_wiki", True),
            ("merge_commit_title", "MERGE_MESSAGE"),
            ("merge_commit_message", "PR_TITLE"),
            ("squash_merge_commit_title", "COMMIT_OR_PR_TITLE"),
            ("squash_merge_commit_message", "COMMIT_MESSAGES"),
        ]:
            setattr(type(repo), attr, PropertyMock(return_value=val))
        rows = check_repo_settings(repo)
        assert ("dev branch", "present") in rows


class TestCheckPipelineFile:
    def test_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "pipeline.yaml").write_text("name: CI")
        assert "exists" in check_pipeline_file()

    def test_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert "not found" in check_pipeline_file()


class TestStatusCommandCLI:
    @patch("gh_secrets_and_vars_async.status.has_dev_branch")
    @patch("gh_secrets_and_vars_async.status.get_rulesets")
    @patch("gh_secrets_and_vars_async.status.get_github_repo")
    @patch("gh_secrets_and_vars_async.status.load_env_config")
    def test_runs(self, mock_env, mock_get_repo, mock_rulesets, mock_dev, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_env.return_value = ("repo", "account", "token")
        mock_dev.return_value = False
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=True)
        # Default values for everything else
        for attr, val in [
            ("allow_merge_commit", True),
            ("allow_squash_merge", True),
            ("allow_rebase_merge", True),
            ("delete_branch_on_merge", False),
            ("allow_update_branch", False),
            ("web_commit_signoff_required", False),
            ("has_issues", True),
            ("has_projects", True),
            ("has_wiki", True),
            ("merge_commit_title", "MERGE_MESSAGE"),
            ("merge_commit_message", "PR_TITLE"),
            ("squash_merge_commit_title", "COMMIT_OR_PR_TITLE"),
            ("squash_merge_commit_message", "COMMIT_MESSAGES"),
        ]:
            setattr(type(repo), attr, PropertyMock(return_value=val))
        mock_get_repo.return_value = repo
        mock_rulesets.return_value = []

        runner = CliRunner()
        result = runner.invoke(status_command, [])
        assert result.exit_code == 0

    @patch("gh_secrets_and_vars_async.status.load_env_config")
    def test_missing_env(self, mock_env):
        mock_env.return_value = ("", "", "")
        runner = CliRunner()
        result = runner.invoke(status_command, [])
        assert result.exit_code != 0

    def test_status_help_has_no_type_flag(self):
        runner = CliRunner()
        result = runner.invoke(status_command, ["--help"])
        assert result.exit_code == 0
        assert "--type" not in result.output
