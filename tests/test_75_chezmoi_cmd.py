import subprocess
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from gh_secrets_and_vars_async.chezmoi_cmd import _build_commit_message, chezmoi_command


class TestBuildCommitMessage:
    def test_single_file(self):
        status = " M home/user/projects/myrepo/dot_env\n"
        msg = _build_commit_message("myrepo", status)
        assert "myrepo" in msg
        assert "dot_env" in msg

    def test_multiple_files(self):
        status = " M dot_env\n A dot_env.local\n"
        msg = _build_commit_message("myrepo", status)
        assert "dot_env" in msg
        assert "dot_env.local" in msg

    def test_empty_status(self):
        msg = _build_commit_message("myrepo", "")
        assert "myrepo" in msg
        assert "env files" in msg


class TestChezmoiCommand:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(chezmoi_command, ["--help"])
        assert result.exit_code == 0
        assert "chezmoi" in result.output.lower()
        assert "--no-sync" in result.output
        assert "--dry-run" in result.output

    @patch("gh_secrets_and_vars_async.chezmoi_cmd.shutil.which", return_value=None)
    def test_not_installed(self, mock_which):
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".env").write_text("FOO=bar\n")
            result = runner.invoke(chezmoi_command, [])
            assert result.exit_code != 0
            assert "not installed" in result.output

    def test_missing_file(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            with patch(
                "gh_secrets_and_vars_async.chezmoi_cmd.shutil.which",
                return_value="/usr/bin/chezmoi",
            ):
                result = runner.invoke(chezmoi_command, ["nonexistent.env"])
                assert result.exit_code != 0
                assert "not found" in result.output.lower()

    @patch("gh_secrets_and_vars_async.chezmoi_cmd.perform_update")
    @patch("gh_secrets_and_vars_async.chezmoi_cmd.subprocess.run")
    @patch("gh_secrets_and_vars_async.chezmoi_cmd.shutil.which", return_value="/usr/bin/chezmoi")
    def test_save_full_flow(self, mock_which, mock_run, mock_update):
        mock_update.return_value = {"SECRETS": ["a"], "VARIABLES": ["b"]}

        def side_effect(cmd, **kwargs):
            # Return porcelain output for status check
            if cmd == ["chezmoi", "git", "status", "--", "--porcelain"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=" M dot_env\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".env").write_text("GH_REPO=test\nGH_ACCOUNT=acct\nGH_TOKEN=tok\n")
            result = runner.invoke(chezmoi_command, [])

        assert result.exit_code == 0, result.output

        # Verify correct command sequence
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert cmds[0][1] == "add"  # chezmoi add
        assert cmds[1][1:3] == ["git", "add"]  # chezmoi git add
        assert cmds[2][1:3] == ["git", "status"]  # chezmoi git status
        assert cmds[3][1:3] == ["git", "commit"]  # chezmoi git commit
        assert cmds[4][1:3] == ["git", "pull"]  # chezmoi git pull --rebase
        assert "--rebase" in cmds[4]
        assert cmds[5][1:3] == ["git", "push"]  # chezmoi git push

        # Verify perform_update was called
        mock_update.assert_called_once()

    @patch("gh_secrets_and_vars_async.chezmoi_cmd.perform_update")
    @patch("gh_secrets_and_vars_async.chezmoi_cmd.subprocess.run")
    @patch("gh_secrets_and_vars_async.chezmoi_cmd.shutil.which", return_value="/usr/bin/chezmoi")
    def test_save_no_changes_skips_commit(self, mock_which, mock_run, mock_update):
        mock_update.return_value = {"SECRETS": [], "VARIABLES": []}

        # All commands succeed, status returns empty (no changes)
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".env").write_text("FOO=bar\n")
            result = runner.invoke(chezmoi_command, [])

        assert result.exit_code == 0
        assert "No chezmoi changes" in result.output

        # Should only have: add, git add, git status (no commit/pull/push)
        assert mock_run.call_count == 3

        # perform_update still called
        mock_update.assert_called_once()

    @patch("gh_secrets_and_vars_async.chezmoi_cmd.perform_update")
    @patch("gh_secrets_and_vars_async.chezmoi_cmd.subprocess.run")
    @patch("gh_secrets_and_vars_async.chezmoi_cmd.shutil.which", return_value="/usr/bin/chezmoi")
    def test_save_no_sync(self, mock_which, mock_run, mock_update):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".env").write_text("FOO=bar\n")
            result = runner.invoke(chezmoi_command, ["--no-sync"])

        assert result.exit_code == 0
        assert "Skipping GitHub sync" in result.output
        mock_update.assert_not_called()

    @patch("gh_secrets_and_vars_async.chezmoi_cmd.subprocess.run")
    @patch("gh_secrets_and_vars_async.chezmoi_cmd.shutil.which", return_value="/usr/bin/chezmoi")
    def test_save_dry_run(self, mock_which, mock_run):
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".env").write_text("FOO=bar\n")
            result = runner.invoke(chezmoi_command, ["--dry-run", "--no-sync"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        # subprocess.run should NOT be called in dry-run mode
        mock_run.assert_not_called()

    @patch("gh_secrets_and_vars_async.chezmoi_cmd.subprocess.run")
    @patch("gh_secrets_and_vars_async.chezmoi_cmd.shutil.which", return_value="/usr/bin/chezmoi")
    def test_chezmoi_command_failure(self, mock_which, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            [], 1, stdout="", stderr="permission denied"
        )

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".env").write_text("FOO=bar\n")
            result = runner.invoke(chezmoi_command, ["--no-sync"])

        assert result.exit_code != 0
        assert "permission denied" in result.output

    def test_commit_message_includes_project_name(self):
        msg = _build_commit_message("augint-mono", " M dot_env\n")
        assert "augint-mono" in msg
        assert msg.startswith("chezmoi: sync augint-mono")
