from unittest.mock import MagicMock, PropertyMock, patch

from click.testing import CliRunner

from gh_secrets_and_vars_async.status import (
    FAIL,
    PASS,
    WARN,
    _expected_check_names,
    check_auto_merge,
    check_pipeline_file,
    check_pipeline_stages,
    check_rulesets,
    extract_pipeline_job_names,
    status_command,
)


class TestExpectedCheckNames:
    def test_library_checks(self):
        names = _expected_check_names("library")
        assert "Code quality" in names
        assert "Security scanning" in names
        assert "Unit tests" in names
        assert "License compliance" in names

    def test_service_checks(self):
        names = _expected_check_names("service")
        assert "Code quality" in names
        assert "Security scanning" in names
        assert "Unit tests" in names
        assert "License compliance" in names

    def test_library_and_service_have_same_gates(self):
        assert _expected_check_names("library") == _expected_check_names("service")


class TestExtractPipelineJobNames:
    def test_extracts_names(self, tmp_path):
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "name: CI/CD Pipeline\n"
            "jobs:\n"
            "  code-quality:\n"
            "    name: Code quality\n"
            "    runs-on: ubuntu-latest\n"
            "  unit-tests:\n"
            "    name: Unit tests\n"
        )
        names = extract_pipeline_job_names(pipeline)
        assert names == {"Code quality", "Unit tests"}

    def test_nonexistent_file(self, tmp_path):
        names = extract_pipeline_job_names(tmp_path / "missing.yaml")
        assert names == set()

    def test_no_jobs_section(self, tmp_path):
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text("name: Simple\non:\n  push:\n")
        names = extract_pipeline_job_names(pipeline)
        assert names == set()


class TestCheckAutoMerge:
    def test_enabled(self):
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=True)
        status, msg = check_auto_merge(repo)
        assert status == PASS

    def test_disabled(self):
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=False)
        status, msg = check_auto_merge(repo)
        assert status == FAIL


class TestCheckRulesets:
    @patch("gh_secrets_and_vars_async.status.get_rulesets")
    def test_matching_library(self, mock_get):
        repo = MagicMock()
        mock_get.return_value = [
            {
                "name": "Library",
                "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
                "rules": [
                    {"type": "deletion"},
                    {"type": "non_fast_forward"},
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "required_status_checks": [
                                {"context": "Code quality"},
                                {"context": "Security scanning"},
                                {"context": "Unit tests"},
                                {"context": "License compliance"},
                            ]
                        },
                    },
                ],
            }
        ]
        results = check_rulesets(repo, "library")
        statuses = [s for s, _ in results]
        assert PASS in statuses
        assert FAIL not in statuses

    @patch("gh_secrets_and_vars_async.status.get_rulesets")
    def test_missing_ruleset(self, mock_get):
        repo = MagicMock()
        mock_get.return_value = []
        results = check_rulesets(repo, "library")
        assert any(s == FAIL and "Missing ruleset" in m for s, m in results)

    @patch("gh_secrets_and_vars_async.status.get_rulesets")
    def test_extra_ruleset(self, mock_get):
        repo = MagicMock()
        mock_get.return_value = [{"name": "Unknown ruleset", "conditions": {}, "rules": []}]
        results = check_rulesets(repo, "library")
        assert any(s == WARN and "Extra ruleset" in m for s, m in results)

    @patch("gh_secrets_and_vars_async.status.get_rulesets")
    def test_missing_status_check(self, mock_get):
        repo = MagicMock()
        mock_get.return_value = [
            {
                "name": "Library",
                "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
                "rules": [
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "required_status_checks": [
                                {"context": "Unit tests"},
                            ]
                        },
                    }
                ],
            }
        ]
        results = check_rulesets(repo, "library")
        assert any(s == FAIL and "missing status check" in m for s, m in results)


class TestCheckPipelineFile:
    def test_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "pipeline.yaml").write_text("name: CI")
        status, msg = check_pipeline_file()
        assert status == PASS

    def test_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        status, msg = check_pipeline_file()
        assert status == FAIL


class TestCheckPipelineStages:
    def test_all_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "pipeline.yaml").write_text(
            "jobs:\n"
            "  a:\n"
            "    name: Code quality\n"
            "  b:\n"
            "    name: Security scanning\n"
            "  c:\n"
            "    name: Unit tests\n"
            "  d:\n"
            "    name: License compliance\n"
        )
        results = check_pipeline_stages("library")
        assert any(s == PASS for s, _ in results)

    def test_missing_stage(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "pipeline.yaml").write_text("jobs:\n  a:\n    name: Unit tests\n")
        results = check_pipeline_stages("library")
        assert any(s == FAIL and "Missing pipeline stage" in m for s, m in results)

    def test_all_present_service(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "pipeline.yaml").write_text(
            "jobs:\n"
            "  a:\n"
            "    name: Code quality\n"
            "  b:\n"
            "    name: Security scanning\n"
            "  c:\n"
            "    name: Unit tests\n"
            "  d:\n"
            "    name: License compliance\n"
        )
        results = check_pipeline_stages("service")
        assert any(s == PASS for s, _ in results)
        assert not any(s == FAIL for s, _ in results)

    def test_no_pipeline(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        results = check_pipeline_stages("library")
        assert any(s == FAIL for s, _ in results)


class TestStatusCommandCLI:
    @patch("gh_secrets_and_vars_async.status.get_rulesets")
    @patch("gh_secrets_and_vars_async.status.get_github_repo")
    @patch("gh_secrets_and_vars_async.status.load_env_config")
    def test_runs(self, mock_env, mock_get_repo, mock_rulesets, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_env.return_value = ("repo", "account", "token")
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=True)
        mock_get_repo.return_value = repo
        mock_rulesets.return_value = []

        runner = CliRunner()
        result = runner.invoke(status_command, ["--type", "library", "--verbose"])
        assert result.exit_code == 0

    @patch("gh_secrets_and_vars_async.status.get_rulesets")
    @patch("gh_secrets_and_vars_async.status.get_github_repo")
    @patch("gh_secrets_and_vars_async.status.load_env_config")
    def test_iac_backward_compat(
        self, mock_env, mock_get_repo, mock_rulesets, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_env.return_value = ("repo", "account", "token")
        repo = MagicMock()
        type(repo).allow_auto_merge = PropertyMock(return_value=True)
        mock_get_repo.return_value = repo
        mock_rulesets.return_value = []

        runner = CliRunner()
        result = runner.invoke(status_command, ["--type", "iac", "--verbose"])
        assert result.exit_code == 0

    @patch("gh_secrets_and_vars_async.status.load_env_config")
    def test_missing_env(self, mock_env):
        mock_env.return_value = ("", "", "")
        runner = CliRunner()
        result = runner.invoke(status_command, [])
        assert result.exit_code != 0
