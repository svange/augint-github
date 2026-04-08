from unittest.mock import MagicMock, PropertyMock, patch

import click
from click.testing import CliRunner

from gh_secrets_and_vars_async.status import (
    extract_all_workflow_jobs,
    extract_pipeline_job_names,
)
from gh_secrets_and_vars_async.wizard import (
    WizardState,
    build_rulesets,
    execute_wizard_state,
    show_plan,
    step_branch_protection,
    step_repo_settings,
    step_repo_type,
    step_secrets_push,
    step_workflow_and_checks,
)

# ---------------------------------------------------------------------------
# extract_pipeline_job_names enhancements
# ---------------------------------------------------------------------------


class TestExtractPipelineJobNames:
    def test_extracts_explicit_names(self, tmp_path):
        wf = tmp_path / "ci.yaml"
        wf.write_text("jobs:\n  lint:\n    name: Code quality\n  test:\n    name: Unit tests\n")
        assert extract_pipeline_job_names(wf) == {"Code quality", "Unit tests"}

    def test_falls_back_to_job_key(self, tmp_path):
        wf = tmp_path / "ci.yaml"
        wf.write_text(
            "jobs:\n  build:\n    runs-on: ubuntu-latest\n  deploy:\n    runs-on: ubuntu-latest\n"
        )
        assert extract_pipeline_job_names(wf) == {"build", "deploy"}

    def test_mixed_named_and_unnamed(self, tmp_path):
        wf = tmp_path / "ci.yaml"
        wf.write_text(
            "jobs:\n  lint:\n    name: Code quality\n  build:\n    runs-on: ubuntu-latest\n"
        )
        assert extract_pipeline_job_names(wf) == {"Code quality", "build"}

    def test_nonexistent_file(self, tmp_path):
        assert extract_pipeline_job_names(tmp_path / "nope.yaml") == set()

    def test_no_jobs_section(self, tmp_path):
        wf = tmp_path / "ci.yaml"
        wf.write_text("name: Simple\non:\n  push:\n")
        assert extract_pipeline_job_names(wf) == set()


# ---------------------------------------------------------------------------
# extract_all_workflow_jobs
# ---------------------------------------------------------------------------


class TestExtractAllWorkflowJobs:
    def test_scans_multiple_files(self, tmp_path):
        (tmp_path / "ci.yaml").write_text("jobs:\n  lint:\n    name: Code quality\n")
        (tmp_path / "security.yml").write_text("jobs:\n  scan:\n    name: Security scanning\n")
        result = extract_all_workflow_jobs(tmp_path)
        assert "ci.yaml" in result
        assert "security.yml" in result
        assert "Code quality" in result["ci.yaml"]
        assert "Security scanning" in result["security.yml"]

    def test_empty_directory(self, tmp_path):
        assert extract_all_workflow_jobs(tmp_path) == {}

    def test_nonexistent_directory(self, tmp_path):
        assert extract_all_workflow_jobs(tmp_path / "nope") == {}

    def test_skips_empty_workflows(self, tmp_path):
        (tmp_path / "empty.yaml").write_text("name: Nothing\non:\n  push:\n")
        assert extract_all_workflow_jobs(tmp_path) == {}


# ---------------------------------------------------------------------------
# build_rulesets
# ---------------------------------------------------------------------------


class TestBuildRulesets:
    def test_single_branch(self):
        state = WizardState(
            repo_type="library",
            branch_patterns=["~DEFAULT_BRANCH"],
            selected_checks=["Code quality", "Unit tests"],
        )
        rulesets = build_rulesets(state)
        assert len(rulesets) == 1
        rs = rulesets[0]
        assert rs["name"] == "Library Production gate"
        assert rs["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
        checks = rs["rules"][2]["parameters"]["required_status_checks"]
        assert [c["context"] for c in checks] == ["Code quality", "Unit tests"]

    def test_multiple_branches(self):
        state = WizardState(
            repo_type="service",
            branch_patterns=["~DEFAULT_BRANCH", "refs/heads/dev"],
            selected_checks=["Unit tests"],
        )
        rulesets = build_rulesets(state)
        assert len(rulesets) == 2
        names = {r["name"] for r in rulesets}
        assert "Service Production gate" in names
        assert "Service Dev gate" in names

    def test_empty_checks(self):
        state = WizardState(
            repo_type="library",
            branch_patterns=["~DEFAULT_BRANCH"],
            selected_checks=[],
        )
        rulesets = build_rulesets(state)
        checks = rulesets[0]["rules"][2]["parameters"]["required_status_checks"]
        assert checks == []

    def test_bypass_actors_present(self):
        state = WizardState(
            repo_type="library",
            branch_patterns=["~DEFAULT_BRANCH"],
            selected_checks=["Unit tests"],
        )
        rulesets = build_rulesets(state)
        bypass = rulesets[0]["bypass_actors"]
        assert len(bypass) == 2
        assert bypass[0]["actor_type"] == "DeployKey"


# ---------------------------------------------------------------------------
# show_plan (smoke test — just ensure no exceptions)
# ---------------------------------------------------------------------------


class TestShowPlan:
    def test_default_rulesets(self, capsys):
        state = WizardState(
            repo_type="library",
            branch_patterns=["~DEFAULT_BRANCH"],
            use_default_rulesets=True,
        )
        show_plan(state)

    def test_custom_rulesets(self, capsys):
        state = WizardState(
            repo_type="service",
            branch_patterns=["~DEFAULT_BRANCH", "refs/heads/dev"],
            selected_checks=["Code quality", "Unit tests"],
            use_default_rulesets=False,
        )
        show_plan(state)


# ---------------------------------------------------------------------------
# Wizard step functions (interactive — use CliRunner input)
# ---------------------------------------------------------------------------


def _wrap(step_fn, *args, **kwargs):
    """Wrap a wizard step in a Click command so CliRunner can feed input."""

    @click.command()
    def cmd():
        step_fn(*args, **kwargs)

    return cmd


class TestStepRepoType:
    def test_accepts_detected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pyproject.toml").write_text('[build-system]\nbuild-backend = "uv"')
        state = WizardState()
        runner = CliRunner()
        result = runner.invoke(_wrap(step_repo_type, state), input="y\n")
        assert result.exit_code == 0
        assert state.repo_type == "library"

    def test_overrides_detected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pyproject.toml").write_text('[build-system]\nbuild-backend = "uv"')
        state = WizardState()
        runner = CliRunner()
        result = runner.invoke(_wrap(step_repo_type, state), input="n\nservice\n")
        assert result.exit_code == 0
        assert state.repo_type == "service"

    def test_prompts_when_unknown(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state = WizardState()
        runner = CliRunner()
        result = runner.invoke(_wrap(step_repo_type, state), input="library\n")
        assert result.exit_code == 0
        assert state.repo_type == "library"


class TestStepRepoSettings:
    def test_enables_automerge(self):
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=False)
        state = WizardState()
        runner = CliRunner()
        with patch("gh_secrets_and_vars_async.wizard.has_dev_branch", return_value=False):
            result = runner.invoke(_wrap(step_repo_settings, repo, state), input="y\ny\n")
        assert result.exit_code == 0
        assert state.auto_merge is True
        assert state.delete_branch_on_merge is True

    def test_dev_branch_disables_delete(self):
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=True)
        state = WizardState()
        runner = CliRunner()
        with patch("gh_secrets_and_vars_async.wizard.has_dev_branch", return_value=True):
            result = runner.invoke(_wrap(step_repo_settings, repo, state), input="y\n")
        assert result.exit_code == 0
        assert state.delete_branch_on_merge is False


class TestStepWorkflowAndChecks:
    def test_workflow_found_select_checks(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yaml").write_text(
            "jobs:\n"
            "  lint:\n"
            "    name: Code quality\n"
            "  test:\n"
            "    name: Unit tests\n"
            "  scan:\n"
            "    name: Security scanning\n"
        )
        state = WizardState()
        runner = CliRunner()
        # Select items 1 and 2 (sorted: Code quality, Security scanning, Unit tests)
        result = runner.invoke(_wrap(step_workflow_and_checks, state), input="1,2\n")
        assert result.exit_code == 0
        assert state.use_default_rulesets is False
        assert len(state.selected_checks) == 2

    def test_no_workflows_generate(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state = WizardState()
        runner = CliRunner()
        # Answer: yes generate, python
        result = runner.invoke(_wrap(step_workflow_and_checks, state), input="y\npython\n")
        assert result.exit_code == 0
        assert state.generate_workflow is True
        assert state.use_default_rulesets is True

    def test_no_workflows_decline(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state = WizardState()
        runner = CliRunner()
        result = runner.invoke(_wrap(step_workflow_and_checks, state), input="n\n")
        assert result.exit_code == 0
        assert state.generate_workflow is False
        assert state.use_default_rulesets is True

    def test_skip_selection(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yaml").write_text("jobs:\n  lint:\n    name: Code quality\n")
        state = WizardState()
        runner = CliRunner()
        result = runner.invoke(_wrap(step_workflow_and_checks, state), input="skip\n")
        assert result.exit_code == 0
        assert state.use_default_rulesets is True


class TestStepBranchProtection:
    def test_default_branch_only(self):
        repo = MagicMock()
        state = WizardState()
        runner = CliRunner()
        with patch("gh_secrets_and_vars_async.wizard.has_dev_branch", return_value=False):
            result = runner.invoke(_wrap(step_branch_protection, repo, state), input="1\n")
        assert result.exit_code == 0
        assert state.branch_patterns == ["~DEFAULT_BRANCH"]

    def test_with_dev_branch(self):
        repo = MagicMock()
        state = WizardState()
        runner = CliRunner()
        with patch("gh_secrets_and_vars_async.wizard.has_dev_branch", return_value=True):
            result = runner.invoke(_wrap(step_branch_protection, repo, state), input="1,2\n")
        assert result.exit_code == 0
        assert "~DEFAULT_BRANCH" in state.branch_patterns
        assert "refs/heads/dev" in state.branch_patterns


class TestStepSecretsPush:
    def test_yes(self):
        state = WizardState()
        runner = CliRunner()
        result = runner.invoke(_wrap(step_secrets_push, state), input="y\n")
        assert result.exit_code == 0
        assert state.push_secrets is True

    def test_no(self):
        state = WizardState()
        runner = CliRunner()
        result = runner.invoke(_wrap(step_secrets_push, state), input="n\n")
        assert result.exit_code == 0
        assert state.push_secrets is False


# ---------------------------------------------------------------------------
# execute_wizard_state
# ---------------------------------------------------------------------------


class TestExecuteWizardState:
    @patch("gh_secrets_and_vars_async.wizard.apply_custom_rulesets")
    @patch("gh_secrets_and_vars_async.wizard.set_repo_settings")
    def test_custom_rulesets_path(self, mock_settings, mock_apply):
        repo = MagicMock()
        mock_apply.return_value = [{"name": "test"}]
        state = WizardState(
            repo_type="library",
            branch_patterns=["~DEFAULT_BRANCH"],
            selected_checks=["Unit tests"],
            use_default_rulesets=False,
            delete_branch_on_merge=True,
        )
        execute_wizard_state(repo, state, dry_run=True)
        mock_settings.assert_called_once()
        mock_apply.assert_called_once()

    @patch("gh_secrets_and_vars_async.wizard.apply_template")
    @patch("gh_secrets_and_vars_async.wizard.set_repo_settings")
    def test_default_rulesets_path(self, mock_settings, mock_template):
        repo = MagicMock()
        mock_template.return_value = [{"name": "test"}]
        state = WizardState(
            repo_type="library",
            branch_patterns=["~DEFAULT_BRANCH"],
            use_default_rulesets=True,
            delete_branch_on_merge=True,
        )
        execute_wizard_state(repo, state, dry_run=True)
        mock_template.assert_called_once()

    @patch("gh_secrets_and_vars_async.wizard.perform_update")
    @patch("gh_secrets_and_vars_async.wizard.apply_template")
    @patch("gh_secrets_and_vars_async.wizard.set_repo_settings")
    def test_secrets_push(self, mock_settings, mock_template, mock_push):
        repo = MagicMock()
        mock_template.return_value = []
        mock_push.return_value = {"SECRETS": ["a"], "VARIABLES": []}
        state = WizardState(
            repo_type="library",
            branch_patterns=["~DEFAULT_BRANCH"],
            use_default_rulesets=True,
            push_secrets=True,
            delete_branch_on_merge=True,
        )
        with patch(
            "gh_secrets_and_vars_async.wizard.load_env_config",
            return_value=("repo", "account", "token"),
        ):
            execute_wizard_state(repo, state, dry_run=True)
        mock_push.assert_called_once()


# ---------------------------------------------------------------------------
# init_command: batch vs wizard routing
# ---------------------------------------------------------------------------


class TestInitBatchFallback:
    """CliRunner does not have a TTY, so init_command should use batch mode by default."""

    @patch("gh_secrets_and_vars_async.init_cmd.perform_update")
    @patch("gh_secrets_and_vars_async.init_cmd.apply_template")
    @patch("gh_secrets_and_vars_async.init_cmd.set_repo_settings")
    @patch("gh_secrets_and_vars_async.init_cmd.has_dev_branch")
    @patch("gh_secrets_and_vars_async.init_cmd.get_github_repo")
    @patch("gh_secrets_and_vars_async.init_cmd.load_env_config")
    @patch("gh_secrets_and_vars_async.init_cmd.ensure_env_file")
    def test_batch_flag_uses_batch(
        self,
        mock_ensure,
        mock_env,
        mock_get_repo,
        mock_has_dev,
        mock_settings,
        mock_rulesets,
        mock_push,
    ):
        from gh_secrets_and_vars_async.init_cmd import init_command

        mock_ensure.return_value = ".env"
        mock_env.return_value = ("repo", "account", "token")
        repo = MagicMock()
        mock_get_repo.return_value = repo
        mock_has_dev.return_value = False
        mock_rulesets.return_value = [{"name": "Library"}]
        mock_push.return_value = {"SECRETS": [], "VARIABLES": []}

        runner = CliRunner()
        result = runner.invoke(
            init_command,
            ["--batch", "--type", "library", "--no-push", "--no-workflow", "--dry-run"],
        )
        assert result.exit_code == 0
        mock_settings.assert_called_once()
        mock_rulesets.assert_called_once()
