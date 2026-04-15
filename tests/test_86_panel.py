"""Tests for the panel dashboard command and app."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from textual import events

from gh_secrets_and_vars_async.cli import main
from gh_secrets_and_vars_async.health import RepoHealth, Severity
from gh_secrets_and_vars_async.health._models import HealthCheckResult
from gh_secrets_and_vars_async.panel_app import (
    FILTER_MODES,
    SORT_MODES,
    DashboardApp,
    DrillDownScreen,
    HelpScreen,
    MainScreen,
    RepoGrid,
    RepoTeamInfo,
    _apply_filter,
    _apply_sort,
    _build_repo_card_regions,
    _repo_at_position,
)
from gh_secrets_and_vars_async.panel_themes import get_theme_spec
from gh_secrets_and_vars_async.tui_dashboard import RepoStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status(
    name="myrepo",
    full_name="org/myrepo",
    main_status="success",
    open_issues=0,
    open_prs=0,
):
    return RepoStatus(
        name=name,
        full_name=full_name,
        is_service=False,
        main_status=main_status,
        main_error=None,
        dev_status=None,
        dev_error=None,
        open_issues=open_issues,
        open_prs=open_prs,
        draft_prs=0,
    )


def _health(name="myrepo", full_name="org/myrepo", checks=None):
    return RepoHealth(
        status=_status(name=name, full_name=full_name),
        checks=checks or [],
    )


def _mock_repo(name="myrepo", full_name="org/myrepo"):
    repo = MagicMock()
    repo.name = name
    repo.full_name = full_name
    repo.default_branch = "main"
    repo.open_issues_count = 0
    repo.archived = False
    return repo


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestPanelCLI:
    def test_panel_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["panel", "--help"])
        assert result.exit_code == 0
        assert "--all" in result.output
        assert "--theme" in result.output
        assert "--stale-days" in result.output
        assert "--refresh-seconds" in result.output
        assert "--env-auth" in result.output

    def test_panel_bad_theme(self):
        runner = CliRunner()
        with (
            patch(
                "gh_secrets_and_vars_async.panel_cmd.load_env_config",
                return_value=("repo", "account", "tok"),
            ),
            patch("gh_secrets_and_vars_async.panel_cmd.get_github_client"),
        ):
            result = runner.invoke(main, ["panel", "--theme", "nonexistent"])
            assert result.exit_code != 0
            assert "Unknown theme" in result.output

    def test_panel_missing_env(self):
        runner = CliRunner()
        with (
            patch(
                "gh_secrets_and_vars_async.panel_cmd.load_env_config",
                return_value=("", "", ""),
            ),
            patch("gh_secrets_and_vars_async.panel_cmd.get_github_client"),
        ):
            result = runner.invoke(main, ["panel"])
            assert result.exit_code != 0

    @patch("gh_secrets_and_vars_async.panel_app.run_panel", side_effect=KeyboardInterrupt)
    @patch("gh_secrets_and_vars_async.common.get_github_repo")
    @patch("gh_secrets_and_vars_async.panel_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.panel_cmd.get_github_client")
    def test_panel_single_repo(self, mock_client, mock_env, mock_repo, mock_panel):
        mock_env.return_value = ("myrepo", "myaccount", "tok")
        mock_repo.return_value = _mock_repo()

        runner = CliRunner()
        result = runner.invoke(main, ["panel"])
        assert result.exit_code == 0

    @patch("gh_secrets_and_vars_async.panel_app.run_panel", side_effect=KeyboardInterrupt)
    @patch("gh_secrets_and_vars_async.panel_cmd.list_repos")
    @patch("gh_secrets_and_vars_async.panel_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.panel_cmd.get_github_client")
    def test_panel_all_flag(self, mock_client, mock_env, mock_list, mock_panel):
        mock_env.return_value = ("", "myaccount", "tok")
        mock_list.return_value = [_mock_repo()]

        runner = CliRunner()
        result = runner.invoke(main, ["panel", "--all"])
        assert result.exit_code == 0
        mock_list.assert_called_once()

    @patch("gh_secrets_and_vars_async.panel_app.run_panel", side_effect=KeyboardInterrupt)
    @patch("gh_secrets_and_vars_async.panel_cmd.list_repos")
    @patch("gh_secrets_and_vars_async.panel_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.panel_cmd.get_github_client")
    def test_panel_env_auth_uses_dotenv_mode(self, mock_client, mock_env, mock_list, mock_panel):
        mock_env.return_value = ("", "myaccount", "tok")
        mock_list.return_value = [_mock_repo()]

        runner = CliRunner()
        result = runner.invoke(main, ["panel", "--all", "--env-auth"])
        assert result.exit_code == 0
        mock_client.assert_called_once_with(auth_source="dotenv")

    @patch("gh_secrets_and_vars_async.panel_app.run_panel", side_effect=KeyboardInterrupt)
    @patch("gh_secrets_and_vars_async.panel_cmd.list_repos")
    @patch("gh_secrets_and_vars_async.panel_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.panel_cmd.get_github_client")
    def test_panel_stale_days_passed(self, mock_client, mock_env, mock_list, mock_panel):
        mock_env.return_value = ("", "myaccount", "tok")
        mock_list.return_value = [_mock_repo()]

        runner = CliRunner()
        result = runner.invoke(main, ["panel", "--all", "--stale-days", "7"])
        assert result.exit_code == 0
        call_kwargs = mock_panel.call_args
        assert call_kwargs[1]["health_config"]["stale_pr_days"] == 7


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


class TestApplySort:
    def test_health_sort(self):
        good = _health(name="good")
        bad = _health(
            name="bad",
            checks=[HealthCheckResult("ci", Severity.CRITICAL, "broken")],
        )
        result = _apply_sort([good, bad], "health")
        assert result[0].status.name == "bad"

    def test_alpha_sort(self):
        z = _health(name="zebra", full_name="org/zebra")
        a = _health(name="alpha", full_name="org/alpha")
        result = _apply_sort([z, a], "alpha")
        assert result[0].status.name == "alpha"
        assert result[1].status.name == "zebra"

    def test_problem_sort(self):
        crit = _health(
            name="crit",
            checks=[HealthCheckResult("ci", Severity.CRITICAL, "broken")],
        )
        high = _health(
            name="high",
            checks=[HealthCheckResult("ren", Severity.HIGH, "missing")],
        )
        ok = _health(name="ok")
        result = _apply_sort([ok, high, crit], "problem")
        assert result[0].status.name == "crit"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class TestApplyFilter:
    def test_all_returns_everything(self):
        healths = [_health(name="a"), _health(name="b")]
        assert len(_apply_filter(healths, "all")) == 2

    def test_broken_ci_filter(self):
        broken = _health(
            name="broken",
            checks=[HealthCheckResult("broken_ci", Severity.CRITICAL, "fail")],
        )
        ok = _health(
            name="ok",
            checks=[HealthCheckResult("broken_ci", Severity.OK, "pass")],
        )
        result = _apply_filter([broken, ok], "broken-ci")
        assert len(result) == 1
        assert result[0].status.name == "broken"

    def test_no_renovate_filter(self):
        missing = _health(
            name="missing",
            checks=[HealthCheckResult("renovate_enabled", Severity.HIGH, "missing")],
        )
        has_it = _health(
            name="has_it",
            checks=[HealthCheckResult("renovate_enabled", Severity.OK, "ok")],
        )
        result = _apply_filter([missing, has_it], "no-renovate")
        assert len(result) == 1
        assert result[0].status.name == "missing"

    def test_stale_prs_filter(self):
        stale = _health(
            name="stale",
            checks=[HealthCheckResult("stale_prs", Severity.MEDIUM, "3 stale")],
        )
        fresh = _health(
            name="fresh",
            checks=[HealthCheckResult("stale_prs", Severity.OK, "none")],
        )
        result = _apply_filter([stale, fresh], "stale-prs")
        assert len(result) == 1

    def test_issues_filter(self):
        many = _health(
            name="many",
            checks=[HealthCheckResult("open_issues", Severity.LOW, "15")],
        )
        few = _health(
            name="few",
            checks=[HealthCheckResult("open_issues", Severity.OK, "2")],
        )
        result = _apply_filter([many, few], "issues")
        assert len(result) == 1

    def test_team_filter_matches_any_team(self):
        multi = _health(name="multi", full_name="org/multi")
        single = _health(name="single", full_name="org/single")
        repo_teams = {
            "org/multi": RepoTeamInfo(primary="platform", all=("platform", "security")),
            "org/single": RepoTeamInfo(primary="docs", all=("docs",)),
        }
        result = _apply_filter([multi, single], "team:security", repo_teams)
        assert len(result) == 1
        assert result[0].status.name == "multi"


# ---------------------------------------------------------------------------
# App instantiation (no real terminal)
# ---------------------------------------------------------------------------


class TestDashboardAppBasic:
    def test_can_instantiate(self):
        from gh_secrets_and_vars_async.panel_app import DashboardApp

        app = DashboardApp(
            repos=[_mock_repo()],
            refresh_seconds=600,
            initial_theme="default",
            org_name="testorg",
        )
        assert app._org_name == "testorg"
        assert app._refresh_seconds == 600

    def test_sort_modes_list(self):
        assert "health" in SORT_MODES
        assert "alpha" in SORT_MODES
        assert "problem" in SORT_MODES

    def test_filter_modes_list(self):
        assert "all" in FILTER_MODES
        assert "broken-ci" in FILTER_MODES
        assert "no-renovate" in FILTER_MODES
        assert "stale-prs" in FILTER_MODES
        assert "issues" in FILTER_MODES


# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------


class TestThemes:
    def test_themes_defined(self):
        from gh_secrets_and_vars_async.panel_themes import THEME_NAMES, THEMES

        assert len(THEMES) == 4
        assert "default" in THEME_NAMES
        assert "cyber" in THEME_NAMES
        assert "minimal" in THEME_NAMES
        assert "matrix" in THEME_NAMES

    def test_theme_objects_valid(self):
        from gh_secrets_and_vars_async.panel_themes import THEMES

        for theme in THEMES:
            assert theme.name
            assert theme.primary


# ---------------------------------------------------------------------------
# Textual headless app tests
# ---------------------------------------------------------------------------


def _build_app(healths=None):
    """Create a DashboardApp with pre-loaded health data (no API calls)."""
    app = DashboardApp(
        repos=[],
        refresh_seconds=9999,
        initial_theme="default",
        org_name="testorg",
    )
    if healths is not None:
        app._healths = healths
        app._health_by_name = {h.status.full_name: h for h in healths}
        app._last_refresh = "12:00:00 UTC"
    return app


def _team_map():
    return {
        "org/broken-repo": RepoTeamInfo(primary="platform", all=("platform",)),
        "org/healthy-repo": RepoTeamInfo(primary="docs", all=("docs",)),
        "org/mid-repo": RepoTeamInfo(primary="platform", all=("platform", "ops")),
    }


def _team_labels():
    return {
        "unassigned": "Unassigned",
        "platform": "Platform",
        "docs": "Docs",
        "ops": "Operations",
    }


def _sample_healths():
    """Create sample health data for testing."""
    return [
        RepoHealth(
            status=_status(name="broken-repo", full_name="org/broken-repo", main_status="failure"),
            checks=[
                HealthCheckResult("broken_ci", Severity.CRITICAL, "main failing", "https://a"),
                HealthCheckResult("stale_prs", Severity.OK, "No stale PRs"),
            ],
        ),
        RepoHealth(
            status=_status(name="healthy-repo", full_name="org/healthy-repo"),
            checks=[
                HealthCheckResult("broken_ci", Severity.OK, "CI passing"),
                HealthCheckResult("renovate_enabled", Severity.OK, "configured"),
                HealthCheckResult("stale_prs", Severity.OK, "No stale PRs"),
            ],
        ),
        RepoHealth(
            status=_status(name="mid-repo", full_name="org/mid-repo", open_issues=12, open_prs=3),
            checks=[
                HealthCheckResult("broken_ci", Severity.OK, "CI passing"),
                HealthCheckResult("renovate_enabled", Severity.HIGH, "No Renovate config"),
                HealthCheckResult("stale_prs", Severity.MEDIUM, "2 stale PRs, oldest 8d"),
                HealthCheckResult("open_issues", Severity.LOW, "12 open issues"),
            ],
        ),
    ]


def _click_event(widget, x: int, y: int, button: int) -> events.Click:
    return events.Click(
        widget=widget,
        x=x,
        y=y,
        delta_x=0,
        delta_y=0,
        button=button,
        shift=False,
        meta=False,
        ctrl=False,
    )


def _mouse_down_event(widget, x: int, y: int, button: int) -> events.MouseDown:
    return events.MouseDown(
        widget=widget,
        x=x,
        y=y,
        delta_x=0,
        delta_y=0,
        button=button,
        shift=False,
        meta=False,
        ctrl=False,
    )


class TestTextualApp:
    def test_repo_card_regions_track_wrapped_cards(self):
        healths = _sample_healths()
        regions = _build_repo_card_regions(
            healths,
            "org/broken-repo",
            get_theme_spec("default"),
            _team_map(),
            _team_labels(),
            "all",
            available_width=90,
        )

        broken = next(region for region in regions if region.full_name == "org/broken-repo")
        mid = next(region for region in regions if region.full_name == "org/mid-repo")
        healthy = next(region for region in regions if region.full_name == "org/healthy-repo")

        assert broken.y == mid.y
        assert healthy.y > broken.y
        assert _repo_at_position(regions, broken.x + 1, broken.y + 1) == "org/broken-repo"
        assert _repo_at_position(regions, mid.x + 1, mid.y + 1) == "org/mid-repo"
        assert _repo_at_position(regions, healthy.x + 1, healthy.y + 1) == "org/healthy-repo"
        assert _repo_at_position(regions, broken.x + broken.width, broken.y + 1) is None

    def test_app_mount_and_main_screen(self):
        app = _build_app(_sample_healths())

        async def run():
            async with app.run_test():
                assert isinstance(app.screen, MainScreen)
                grid = app.screen.query_one("#repo-grid")
                assert grid is not None

        asyncio.run(run())

    def test_table_populated(self):
        healths = _sample_healths()
        app = _build_app(healths)

        async def run():
            async with app.run_test():
                screen = app.screen
                assert isinstance(screen, MainScreen)
                screen.update_table(healths, "health", "all")
                assert screen.visible_repo_count == 3

        asyncio.run(run())

    def test_sort_cycle(self):
        healths = _sample_healths()
        app = _build_app(healths)

        async def run():
            async with app.run_test() as pilot:
                assert app.sort_mode == "health"
                screen = app.screen
                assert isinstance(screen, MainScreen)
                screen.update_table(healths, "health", "all")
                await pilot.press("s")
                assert app.sort_mode == "alpha"
                await pilot.press("s")
                assert app.sort_mode == "problem"
                await pilot.press("s")
                assert app.sort_mode == "health"

        asyncio.run(run())

    def test_filter_cycle(self):
        healths = _sample_healths()
        app = _build_app(healths)
        app._repo_teams = _team_map()
        app._team_labels.update(_team_labels())

        async def run():
            async with app.run_test() as pilot:
                assert app.filter_mode == "all"
                screen = app.screen
                assert isinstance(screen, MainScreen)
                screen.update_table(healths, "health", "all")
                await pilot.press("f")
                assert app.filter_mode == "broken-ci"
                await pilot.press("f")
                assert app.filter_mode == "no-renovate"
                for _ in range(3):
                    await pilot.press("f")
                assert app.filter_mode == "team:docs"

        asyncio.run(run())

    def test_help_screen(self):
        app = _build_app(_sample_healths())

        async def run():
            async with app.run_test() as pilot:
                await pilot.press("question_mark")
                assert isinstance(app.screen, HelpScreen)
                await pilot.press("escape")
                assert isinstance(app.screen, MainScreen)

        asyncio.run(run())

    def test_theme_cycle(self):
        app = _build_app(_sample_healths())

        async def run():
            async with app.run_test() as pilot:
                assert app.theme == "default"
                await pilot.press("t")
                assert app.theme == "cyber"
                await pilot.press("t")
                assert app.theme == "minimal"
                await pilot.press("t")
                assert app.theme == "matrix"
                await pilot.press("t")
                assert app.theme == "default"

        asyncio.run(run())

    def test_available_team_filters(self):
        app = _build_app(_sample_healths())
        app._repo_teams = _team_map()
        app._team_labels.update(_team_labels())

        filters = app.available_filter_modes()
        assert "team:docs" in filters
        assert "team:platform" in filters
        assert "team:ops" in filters

    def test_panel_navigation_changes_selection(self):
        healths = _sample_healths()
        app = _build_app(healths)

        async def run():
            async with app.run_test() as pilot:
                screen = app.screen
                assert isinstance(screen, MainScreen)
                screen.update_table(healths, "health", "all")
                first = app._selected_repo_full_name
                await pilot.press("right")
                assert app._selected_repo_full_name != first

        asyncio.run(run())

    def test_left_click_opens_detail(self):
        app = _build_app(_sample_healths())
        app._repo_teams = _team_map()
        app._team_labels.update(_team_labels())

        async def run():
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, MainScreen)
                grid = screen.query_one(RepoGrid)
                target = next(
                    region for region in grid._card_regions if region.full_name == "org/mid-repo"
                )
                await pilot.click(grid, offset=(target.x + 1, target.y + 1))
                await pilot.pause()
                assert isinstance(app.screen, DrillDownScreen)
                assert app.screen.health.status.full_name == "org/mid-repo"

        asyncio.run(run())

    def test_middle_click_opens_actions_tab(self):
        app = _build_app(_sample_healths())
        app._repo_teams = _team_map()
        app._team_labels.update(_team_labels())

        async def run():
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, MainScreen)
                grid = screen.query_one(RepoGrid)
                target = next(
                    region for region in grid._card_regions if region.full_name == "org/mid-repo"
                )
                with patch(
                    "gh_secrets_and_vars_async.panel_app.webbrowser.open_new_tab"
                ) as mock_open:
                    grid.on_click(_click_event(grid, target.x + 1, target.y + 1, button=2))
                assert app._selected_repo_full_name == "org/mid-repo"
                mock_open.assert_called_once_with("https://github.com/org/mid-repo/actions")

        asyncio.run(run())

    def test_drill_down_and_back(self):
        healths = _sample_healths()
        app = _build_app(healths)

        async def run():
            async with app.run_test() as pilot:
                screen = app.screen
                assert isinstance(screen, MainScreen)
                # Set health data and populate table
                app._health_by_name = {h.status.full_name: h for h in healths}
                screen.update_table(healths, "health", "all")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, DrillDownScreen)
                await pilot.press("escape")
                await pilot.pause()
                assert isinstance(app.screen, MainScreen)

        asyncio.run(run())

    def test_right_click_goes_back_from_drill_down(self):
        healths = _sample_healths()
        app = _build_app(healths)

        async def run():
            async with app.run_test() as pilot:
                screen = app.screen
                assert isinstance(screen, MainScreen)
                app._health_by_name = {h.status.full_name: h for h in healths}
                screen.update_table(healths, "health", "all")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                detail = app.screen
                assert isinstance(detail, DrillDownScreen)
                detail.on_mouse_down(_mouse_down_event(detail, 1, 1, button=3))
                await pilot.pause()
                assert isinstance(app.screen, MainScreen)

        asyncio.run(run())

    def test_status_bar_update(self):
        healths = _sample_healths()
        app = _build_app(healths)

        async def run():
            async with app.run_test():
                screen = app.screen
                assert isinstance(screen, MainScreen)
                screen.update_status_bar("testorg", "12:00:00 UTC", "health", "all", 3)

        asyncio.run(run())

    def test_drill_down_content(self):
        healths = _sample_healths()
        app = _build_app(healths)

        async def run():
            async with app.run_test() as pilot:
                screen = app.screen
                assert isinstance(screen, MainScreen)
                app._health_by_name = {h.status.full_name: h for h in healths}
                screen.update_table(healths, "health", "all")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.pause()
                assert isinstance(app.screen, DrillDownScreen)
                assert app.screen.health is not None

        asyncio.run(run())

    def test_quit(self):
        app = _build_app(_sample_healths())

        async def run():
            async with app.run_test() as pilot:
                await pilot.press("q")

        asyncio.run(run())
