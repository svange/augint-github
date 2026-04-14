"""Tests for the TUI dashboard command."""

from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from gh_secrets_and_vars_async.cli import main
from gh_secrets_and_vars_async.tui_cmd import (
    _warn_rate_limit,
    list_repos,
    select_org_interactive,
    select_repos_interactive,
)
from gh_secrets_and_vars_async.tui_dashboard import (
    RepoStatus,
    _get_failed_step,
    fetch_repo_status,
    get_run_status,
    load_cache,
    save_cache,
)
from gh_secrets_and_vars_async.tui_layouts import available_layouts, get_layout

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_repo(
    name="myrepo",
    full_name="org/myrepo",
    default_branch="main",
    has_dev=False,
    open_issues_count=5,
    archived=False,
):
    repo = MagicMock()
    repo.name = name
    repo.full_name = full_name
    repo.default_branch = default_branch
    repo.open_issues_count = open_issues_count
    repo.archived = archived
    return repo


def _mock_workflow_run(status="completed", conclusion="success"):
    run = MagicMock()
    run.status = status
    run.conclusion = conclusion
    return run


def _mock_pulls(total=3, drafts=1):
    pulls = MagicMock()
    pulls.totalCount = total
    pr_list = []
    for i in range(total):
        pr = MagicMock()
        pr.draft = i < drafts
        pr_list.append(pr)
    pulls.__iter__ = MagicMock(return_value=iter(pr_list))
    return pulls


# ---------------------------------------------------------------------------
# get_run_status
# ---------------------------------------------------------------------------


class TestGetRunStatus:
    def test_success(self):
        repo = _mock_repo()
        run = _mock_workflow_run(status="completed", conclusion="success")
        runs = MagicMock()
        runs.totalCount = 1
        runs.__getitem__ = MagicMock(return_value=run)
        repo.get_workflow_runs.return_value = runs

        status, error = get_run_status(repo, "main")
        assert status == "success"
        assert error is None

    def test_failure_with_error(self):
        repo = _mock_repo()
        run = _mock_workflow_run(status="completed", conclusion="failure")
        # Mock a failed job with a failed step
        step = MagicMock()
        step.conclusion = "failure"
        step.name = "Run tests"
        job = MagicMock()
        job.conclusion = "failure"
        job.name = "build"
        job.steps = [step]
        run.jobs.return_value = [job]

        runs = MagicMock()
        runs.totalCount = 1
        runs.__getitem__ = MagicMock(return_value=run)
        repo.get_workflow_runs.return_value = runs

        status, error = get_run_status(repo, "main")
        assert status == "failure"
        assert error == "build: Run tests"

    def test_in_progress(self):
        repo = _mock_repo()
        run = _mock_workflow_run(status="in_progress", conclusion=None)
        runs = MagicMock()
        runs.totalCount = 1
        runs.__getitem__ = MagicMock(return_value=run)
        repo.get_workflow_runs.return_value = runs

        status, error = get_run_status(repo, "main")
        assert status == "in_progress"
        assert error is None

    def test_queued(self):
        repo = _mock_repo()
        run = _mock_workflow_run(status="queued", conclusion=None)
        runs = MagicMock()
        runs.totalCount = 1
        runs.__getitem__ = MagicMock(return_value=run)
        repo.get_workflow_runs.return_value = runs

        status, error = get_run_status(repo, "main")
        assert status == "in_progress"

    def test_no_runs(self):
        repo = _mock_repo()
        runs = MagicMock()
        runs.totalCount = 0
        repo.get_workflow_runs.return_value = runs

        status, error = get_run_status(repo, "main")
        assert status == "unknown"
        assert error is None

    def test_exception(self):
        from github.GithubException import GithubException

        repo = _mock_repo()
        repo.get_workflow_runs.side_effect = GithubException(500, "error", None)

        status, error = get_run_status(repo, "main")
        assert status == "unknown"
        assert error is None


# ---------------------------------------------------------------------------
# _get_failed_step
# ---------------------------------------------------------------------------


class TestGetFailedStep:
    def test_failed_job_and_step(self):
        step = MagicMock()
        step.conclusion = "failure"
        step.name = "Run tests"
        job = MagicMock()
        job.conclusion = "failure"
        job.name = "build"
        job.steps = [step]
        run = MagicMock()
        run.jobs.return_value = [job]

        assert _get_failed_step(run) == "build: Run tests"

    def test_failed_job_no_failed_step(self):
        step = MagicMock()
        step.conclusion = "success"
        step.name = "Setup"
        job = MagicMock()
        job.conclusion = "failure"
        job.name = "deploy"
        job.steps = [step]
        run = MagicMock()
        run.jobs.return_value = [job]

        assert _get_failed_step(run) == "deploy"

    def test_no_failed_jobs(self):
        job = MagicMock()
        job.conclusion = "success"
        run = MagicMock()
        run.jobs.return_value = [job]

        assert _get_failed_step(run) is None

    def test_api_error(self):
        from github.GithubException import GithubException

        run = MagicMock()
        run.jobs.side_effect = GithubException(500, "error", None)

        assert _get_failed_step(run) is None


# ---------------------------------------------------------------------------
# fetch_repo_status
# ---------------------------------------------------------------------------


class TestFetchRepoStatus:
    @patch("gh_secrets_and_vars_async.tui_dashboard.has_dev_branch", return_value=False)
    @patch(
        "gh_secrets_and_vars_async.tui_dashboard.get_run_status",
        return_value=("success", None),
    )
    def test_library_success(self, mock_run, mock_dev):
        repo = _mock_repo(open_issues_count=7)
        repo.get_pulls.return_value = _mock_pulls(total=2, drafts=0)

        status = fetch_repo_status(repo)

        assert status.name == "myrepo"
        assert status.is_service is False
        assert status.main_status == "success"
        assert status.main_error is None
        assert status.dev_status is None
        assert status.dev_error is None
        assert status.open_issues == 5  # 7 - 2 PRs
        assert status.open_prs == 2
        assert status.draft_prs == 0

    @patch("gh_secrets_and_vars_async.tui_dashboard.has_dev_branch", return_value=True)
    @patch(
        "gh_secrets_and_vars_async.tui_dashboard.get_run_status",
        side_effect=[("success", None), ("failure", "build: Run tests")],
    )
    def test_service_mixed(self, mock_run, mock_dev):
        repo = _mock_repo(open_issues_count=10)
        repo.get_pulls.return_value = _mock_pulls(total=3, drafts=1)

        status = fetch_repo_status(repo)

        assert status.is_service is True
        assert status.main_status == "success"
        assert status.dev_status == "failure"
        assert status.dev_error == "build: Run tests"
        assert status.open_issues == 7  # 10 - 3 PRs
        assert status.open_prs == 3
        assert status.draft_prs == 1

    @patch("gh_secrets_and_vars_async.tui_dashboard.has_dev_branch", return_value=False)
    @patch(
        "gh_secrets_and_vars_async.tui_dashboard.get_run_status",
        return_value=("unknown", None),
    )
    def test_no_runs(self, mock_run, mock_dev):
        repo = _mock_repo(open_issues_count=0)
        repo.get_pulls.return_value = _mock_pulls(total=0, drafts=0)

        status = fetch_repo_status(repo)

        assert status.main_status == "unknown"
        assert status.open_issues == 0
        assert status.open_prs == 0

    @patch(
        "gh_secrets_and_vars_async.tui_dashboard.has_dev_branch",
        side_effect=RuntimeError("network"),
    )
    def test_error_returns_previous(self, mock_dev):
        repo = _mock_repo()
        previous = RepoStatus("myrepo", "org/myrepo", False, "success", None, None, None, 3, 1, 0)

        status = fetch_repo_status(repo, previous=previous)
        assert status is previous

    @patch(
        "gh_secrets_and_vars_async.tui_dashboard.has_dev_branch",
        side_effect=RuntimeError("network"),
    )
    def test_error_returns_degraded_without_previous(self, mock_dev):
        repo = _mock_repo()

        status = fetch_repo_status(repo)
        assert status.main_status == "unknown"
        assert status.main_error == "fetch error"


# ---------------------------------------------------------------------------
# Layout registry
# ---------------------------------------------------------------------------


class TestLayoutRegistry:
    def test_available_layouts(self):
        names = available_layouts()
        assert "default" in names
        assert "compact" in names
        assert "cyber" in names

    def test_get_layout(self):
        layout = get_layout("default")
        assert layout.name == "default"

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError):
            get_layout("nonexistent")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class TestCache:
    def test_save_and_load(self, tmp_path):
        statuses = [
            RepoStatus("r1", "o/r1", False, "success", None, None, None, 1, 0, 0),
            RepoStatus("r2", "o/r2", True, "failure", "err", "success", None, 3, 2, 1),
        ]
        cache_file = tmp_path / "cache.json"
        with patch("gh_secrets_and_vars_async.tui_dashboard.CACHE_FILE", cache_file):
            with patch("gh_secrets_and_vars_async.tui_dashboard.CACHE_DIR", tmp_path):
                save_cache(statuses)
                loaded = load_cache()

        assert len(loaded) == 2
        assert loaded["o/r1"].main_status == "success"
        assert loaded["o/r2"].dev_error is None
        assert loaded["o/r2"].main_error == "err"

    def test_load_missing_file(self, tmp_path):
        cache_file = tmp_path / "nonexistent.json"
        with patch("gh_secrets_and_vars_async.tui_dashboard.CACHE_FILE", cache_file):
            assert load_cache() == {}

    def test_load_corrupt_file(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("not json")
        with patch("gh_secrets_and_vars_async.tui_dashboard.CACHE_FILE", cache_file):
            assert load_cache() == {}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRendering:
    """Test that each registered layout can render without crashing."""

    _statuses = [
        RepoStatus("r1", "o/r1", False, "success", None, None, None, 1, 0, 0),
        RepoStatus("r2", "o/r2", True, "failure", "err", "success", None, 3, 2, 1),
        RepoStatus("r3", "o/r3", False, "unknown", None, None, None, 0, 0, 0),
    ]

    @pytest.mark.parametrize("name", ["default", "compact", "cyber"])
    def test_build_repo_panel(self, name):
        layout = get_layout(name)
        for s in self._statuses:
            result = layout.build_repo_panel(s)
            assert result is not None

    @pytest.mark.parametrize("name", ["default", "compact", "cyber"])
    def test_build_dashboard(self, name):
        layout = get_layout(name)
        result = layout.build_dashboard(self._statuses, 600)
        assert result is not None

    @pytest.mark.parametrize("name", ["default", "compact", "cyber"])
    def test_build_dashboard_cached(self, name):
        layout = get_layout(name)
        result = layout.build_dashboard(self._statuses, 600, from_cache=True)
        assert result is not None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestTuiCLI:
    def test_tui_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["tui", "--help"])
        assert result.exit_code == 0
        assert "--all" in result.output
        assert "--interactive" in result.output
        assert "--refresh-seconds" in result.output
        assert "--org" in result.output
        assert "--layout" in result.output

    @patch("gh_secrets_and_vars_async.tui_cmd.run_dashboard", side_effect=KeyboardInterrupt)
    @patch("gh_secrets_and_vars_async.common.get_github_repo")
    @patch("gh_secrets_and_vars_async.tui_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.tui_cmd.get_github_client")
    def test_tui_default_single_repo(self, mock_client, mock_env, mock_repo, mock_dash):
        mock_env.return_value = ("myrepo", "myaccount", "tok")
        mock_repo.return_value = _mock_repo()

        runner = CliRunner()
        result = runner.invoke(main, ["tui"])
        assert result.exit_code == 0

    @patch("gh_secrets_and_vars_async.tui_cmd.run_dashboard", side_effect=KeyboardInterrupt)
    @patch("gh_secrets_and_vars_async.tui_cmd.list_repos")
    @patch("gh_secrets_and_vars_async.tui_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.tui_cmd.get_github_client")
    def test_tui_all_flag(self, mock_client, mock_env, mock_list, mock_dash):
        mock_env.return_value = ("myrepo", "myaccount", "tok")
        mock_list.return_value = [_mock_repo()]

        runner = CliRunner()
        result = runner.invoke(main, ["tui", "--all"])
        assert result.exit_code == 0
        mock_list.assert_called_once()

    def test_tui_missing_env(self):
        runner = CliRunner()
        with (
            patch(
                "gh_secrets_and_vars_async.tui_cmd.load_env_config",
                return_value=("", "", ""),
            ),
            patch("gh_secrets_and_vars_async.tui_cmd.get_github_client"),
        ):
            result = runner.invoke(main, ["tui"])
            assert result.exit_code != 0

    @patch("gh_secrets_and_vars_async.tui_cmd.run_dashboard", side_effect=KeyboardInterrupt)
    @patch("gh_secrets_and_vars_async.tui_cmd.select_repos_interactive")
    @patch("gh_secrets_and_vars_async.tui_cmd.list_repos")
    @patch("gh_secrets_and_vars_async.tui_cmd.select_org_interactive", return_value="myorg")
    @patch("gh_secrets_and_vars_async.tui_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.tui_cmd.get_github_client")
    def test_tui_interactive(
        self, mock_client, mock_env, mock_org, mock_list, mock_select, mock_dash
    ):
        mock_env.return_value = ("", "", "tok")
        mock_list.return_value = [_mock_repo()]
        mock_select.return_value = [_mock_repo()]

        runner = CliRunner()
        result = runner.invoke(main, ["tui", "-i"])
        assert result.exit_code == 0
        mock_org.assert_called_once()
        mock_list.assert_called_once()
        mock_select.assert_called_once()

    @patch("gh_secrets_and_vars_async.tui_cmd.run_dashboard", side_effect=KeyboardInterrupt)
    @patch("gh_secrets_and_vars_async.tui_cmd.list_repos")
    @patch("gh_secrets_and_vars_async.tui_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.tui_cmd.get_github_client")
    def test_tui_all_with_org(self, mock_client, mock_env, mock_list, mock_dash):
        mock_env.return_value = ("", "", "tok")
        mock_list.return_value = [_mock_repo()]

        runner = CliRunner()
        result = runner.invoke(main, ["tui", "--all", "--org", "myorg"])
        assert result.exit_code == 0
        mock_list.assert_called_once()

    @patch("gh_secrets_and_vars_async.tui_cmd.list_repos", return_value=[])
    @patch("gh_secrets_and_vars_async.tui_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.tui_cmd.get_github_client")
    def test_tui_all_no_repos(self, mock_client, mock_env, mock_list):
        mock_env.return_value = ("", "myaccount", "tok")

        runner = CliRunner()
        result = runner.invoke(main, ["tui", "--all"])
        assert result.exit_code != 0
        assert "No repositories found" in result.output


# ---------------------------------------------------------------------------
# list_repos
# ---------------------------------------------------------------------------


class TestListRepos:
    def test_list_repos_org(self):
        g = MagicMock()
        repo1 = _mock_repo(name="r1", archived=False)
        repo2 = _mock_repo(name="r2", archived=True)
        g.get_organization.return_value.get_repos.return_value = [repo1, repo2]

        result = list_repos(g, "myorg")
        assert len(result) == 1
        assert result[0].name == "r1"

    def test_list_repos_user_fallback(self):
        from github.GithubException import UnknownObjectException

        g = MagicMock()
        g.get_organization.return_value.get_repos.side_effect = UnknownObjectException(
            404, "nope", None
        )
        repo = _mock_repo(name="userrepo", archived=False)
        g.get_user.return_value.get_repos.return_value = [repo]

        result = list_repos(g, "myuser")
        assert len(result) == 1
        assert result[0].name == "userrepo"


# ---------------------------------------------------------------------------
# select_org_interactive
# ---------------------------------------------------------------------------


class TestSelectOrgInteractive:
    def test_no_orgs_returns_login(self):
        g = MagicMock()
        g.get_user.return_value.login = "myuser"
        g.get_user.return_value.get_orgs.return_value = []

        assert select_org_interactive(g) == "myuser"

    @patch("gh_secrets_and_vars_async.tui_cmd.click.prompt", return_value=1)
    def test_selects_org(self, mock_prompt):
        g = MagicMock()
        g.get_user.return_value.login = "myuser"
        org = MagicMock()
        org.login = "myorg"
        g.get_user.return_value.get_orgs.return_value = [org]

        assert select_org_interactive(g) == "myorg"

    @patch("gh_secrets_and_vars_async.tui_cmd.click.prompt", return_value=2)
    def test_selects_personal(self, mock_prompt):
        g = MagicMock()
        g.get_user.return_value.login = "myuser"
        org = MagicMock()
        org.login = "myorg"
        g.get_user.return_value.get_orgs.return_value = [org]

        assert select_org_interactive(g) == "myuser"


# ---------------------------------------------------------------------------
# select_repos_interactive
# ---------------------------------------------------------------------------


class TestSelectReposInteractive:
    def test_empty_repos_raises(self):
        with pytest.raises(click.ClickException, match="No repositories found"):
            select_repos_interactive([])

    @patch("gh_secrets_and_vars_async.tui_cmd.click.prompt", return_value="1,3")
    def test_selects_multiple(self, mock_prompt):
        repos = [_mock_repo(name=f"r{i}") for i in range(1, 4)]
        result = select_repos_interactive(repos)
        assert len(result) == 2
        assert result[0].name == "r1"
        assert result[1].name == "r3"

    @patch("gh_secrets_and_vars_async.tui_cmd.click.prompt", side_effect=["bad", "1"])
    def test_retries_on_invalid(self, mock_prompt):
        repos = [_mock_repo(name="r1")]
        result = select_repos_interactive(repos)
        assert len(result) == 1
        assert mock_prompt.call_count == 2


# ---------------------------------------------------------------------------
# _warn_rate_limit
# ---------------------------------------------------------------------------


class TestWarnRateLimit:
    def test_no_warning_under_threshold(self, capsys):
        _warn_rate_limit(5, 600)
        captured = capsys.readouterr()
        assert "Warning" not in captured.out

    def test_warns_over_threshold(self, capsys):
        _warn_rate_limit(100, 30)
        captured = capsys.readouterr()
        assert "Warning" in captured.out or "API calls" in captured.out
