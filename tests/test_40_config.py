from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from click.testing import CliRunner
from github.GithubException import GithubException

from gh_secrets_and_vars_async.config import (
    config_command,
    get_auto_merge_status,
    has_dev_branch,
    set_auto_merge,
    set_repo_settings,
)


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    type(repo).allow_auto_merge = PropertyMock(return_value=False)
    return repo


class TestGetAutoMergeStatus:
    def test_enabled(self):
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=True)
        assert get_auto_merge_status(repo) is True

    def test_disabled(self):
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=False)
        assert get_auto_merge_status(repo) is False

    def test_none_returns_false(self):
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=None)
        assert get_auto_merge_status(repo) is False


class TestHasDevBranch:
    def test_has_dev(self):
        repo = MagicMock()
        repo.get_branch.return_value = MagicMock()
        assert has_dev_branch(repo) is True
        repo.get_branch.assert_called_once_with("dev")

    def test_no_dev(self):
        repo = MagicMock()
        repo.get_branch.side_effect = GithubException(404, "Not Found", None)
        assert has_dev_branch(repo) is False


class TestSetAutoMerge:
    def test_enable(self, mock_repo):
        set_auto_merge(mock_repo, enabled=True)
        mock_repo.edit.assert_called_once_with(allow_auto_merge=True)

    def test_disable(self):
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=True)
        set_auto_merge(repo, enabled=False)
        repo.edit.assert_called_once_with(allow_auto_merge=False)

    def test_already_enabled(self):
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=True)
        set_auto_merge(repo, enabled=True)
        repo.edit.assert_not_called()

    def test_dry_run(self, mock_repo):
        set_auto_merge(mock_repo, enabled=True, dry_run=True)
        mock_repo.edit.assert_not_called()


class TestSetRepoSettings:
    def test_sets_all_settings(self):
        repo = MagicMock()
        set_repo_settings(repo)
        repo.edit.assert_called_once_with(
            allow_merge_commit=True,
            allow_squash_merge=False,
            allow_rebase_merge=False,
            allow_auto_merge=True,
            merge_commit_title="PR_TITLE",
            merge_commit_message="PR_BODY",
            delete_branch_on_merge=True,
        )

    def test_delete_branch_always_true(self):
        """delete_branch_on_merge is always True; dev branches are protected
        from deletion by the branch ruleset, not by this flag."""
        repo = MagicMock()
        set_repo_settings(repo)
        call_kwargs = repo.edit.call_args[1]
        assert call_kwargs["delete_branch_on_merge"] is True
        assert call_kwargs["allow_squash_merge"] is False
        assert call_kwargs["allow_rebase_merge"] is False

    def test_dry_run(self):
        repo = MagicMock()
        set_repo_settings(repo, dry_run=True)
        repo.edit.assert_not_called()


class TestConfigCommandCLI:
    @patch("gh_secrets_and_vars_async.config.get_github_repo")
    @patch("gh_secrets_and_vars_async.config.load_env_config")
    def test_status_default(self, mock_env, mock_get_repo):
        mock_env.return_value = ("repo", "account", "token")
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=True)
        type(repo).allow_merge_commit = PropertyMock(return_value=True)
        type(repo).allow_squash_merge = PropertyMock(return_value=False)
        type(repo).allow_rebase_merge = PropertyMock(return_value=False)
        type(repo).delete_branch_on_merge = PropertyMock(return_value=True)
        mock_get_repo.return_value = repo

        runner = CliRunner()
        result = runner.invoke(config_command, [])
        assert result.exit_code == 0
        assert "enabled" in result.output

    @patch("gh_secrets_and_vars_async.config.get_github_repo")
    @patch("gh_secrets_and_vars_async.config.load_env_config")
    def test_enable_auto_merge(self, mock_env, mock_get_repo):
        mock_env.return_value = ("repo", "account", "token")
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=False)
        mock_get_repo.return_value = repo

        runner = CliRunner()
        result = runner.invoke(config_command, ["--auto-merge"])
        assert result.exit_code == 0
        repo.edit.assert_called_once_with(allow_auto_merge=True)

    @patch("gh_secrets_and_vars_async.config.get_github_repo")
    @patch("gh_secrets_and_vars_async.config.load_env_config")
    def test_standardize(self, mock_env, mock_get_repo):
        mock_env.return_value = ("repo", "account", "token")
        repo = MagicMock()
        repo.get_branch.side_effect = GithubException(404, "Not Found", None)
        mock_get_repo.return_value = repo

        runner = CliRunner()
        result = runner.invoke(config_command, ["--standardize"])
        assert result.exit_code == 0
        repo.edit.assert_called_once()
        call_kwargs = repo.edit.call_args[1]
        assert call_kwargs["allow_squash_merge"] is False
        assert call_kwargs["delete_branch_on_merge"] is True

    @patch("gh_secrets_and_vars_async.config.get_github_repo")
    @patch("gh_secrets_and_vars_async.config.load_env_config")
    def test_standardize_with_dev_branch(self, mock_env, mock_get_repo):
        """delete_branch_on_merge is always True regardless of dev branch.
        Dev branches are protected from deletion by the branch ruleset."""
        mock_env.return_value = ("repo", "account", "token")
        repo = MagicMock()
        repo.get_branch.return_value = MagicMock()  # dev branch exists
        mock_get_repo.return_value = repo

        runner = CliRunner()
        result = runner.invoke(config_command, ["--standardize"])
        assert result.exit_code == 0
        call_kwargs = repo.edit.call_args[1]
        assert call_kwargs["delete_branch_on_merge"] is True

    @patch("gh_secrets_and_vars_async.config.load_env_config")
    def test_missing_env(self, mock_env):
        mock_env.return_value = ("", "", "")
        runner = CliRunner()
        result = runner.invoke(config_command, [])
        assert result.exit_code != 0
