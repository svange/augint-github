from click.testing import CliRunner

from gh_secrets_and_vars_async.workflow import workflow_command


class TestWorkflowCommand:
    def test_dry_run_library(self):
        runner = CliRunner()
        result = runner.invoke(workflow_command, ["--type", "library", "--dry-run"])
        assert result.exit_code == 0
        assert "Code quality" in result.output
        assert "License compliance" in result.output

    def test_dry_run_service(self):
        runner = CliRunner()
        result = runner.invoke(workflow_command, ["--type", "service", "--dry-run"])
        assert result.exit_code == 0
        assert "Code quality" in result.output
        assert "Integration tests" in result.output
        assert "Smoke tests" in result.output

    def test_dry_run_iac_backward_compat(self):
        runner = CliRunner()
        result = runner.invoke(workflow_command, ["--type", "iac", "--dry-run"])
        assert result.exit_code == 0
        assert "Code quality" in result.output
        assert "Integration tests" in result.output

    def test_dry_run_lang_typescript(self):
        runner = CliRunner()
        result = runner.invoke(
            workflow_command, ["--type", "library", "--lang", "typescript", "--dry-run"]
        )
        assert result.exit_code == 0
        assert "Code quality" in result.output
        assert "pnpm" in result.output

    def test_dry_run_lang_default_is_python(self):
        runner = CliRunner()
        result = runner.invoke(workflow_command, ["--type", "library", "--dry-run"])
        assert result.exit_code == 0
        assert "uv sync" in result.output

    def test_write_to_output(self, tmp_path):
        output = tmp_path / "pipeline.yaml"
        runner = CliRunner()
        result = runner.invoke(workflow_command, ["--type", "library", "--output", str(output)])
        assert result.exit_code == 0
        assert output.exists()
        content = output.read_text()
        assert "Code quality" in content

    def test_type_required(self):
        runner = CliRunner()
        result = runner.invoke(workflow_command, [])
        assert result.exit_code != 0

    def test_existing_pipeline_writes_example(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        workflows_dir = tmp_path / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)
        (workflows_dir / "pipeline.yaml").write_text("existing")

        runner = CliRunner()
        result = runner.invoke(workflow_command, ["--type", "library"])
        assert result.exit_code == 0
        assert (workflows_dir / "example-pipeline.yaml").exists()
        assert (workflows_dir / "pipeline.yaml").read_text() == "existing"

    def test_force_overwrites(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        workflows_dir = tmp_path / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)
        (workflows_dir / "pipeline.yaml").write_text("existing")

        runner = CliRunner()
        result = runner.invoke(workflow_command, ["--type", "library", "--force"])
        assert result.exit_code == 0
        content = (workflows_dir / "pipeline.yaml").read_text()
        assert "Code quality" in content

    def test_creates_directories(self, tmp_path):
        output = tmp_path / "new" / "dir" / "pipeline.yaml"
        runner = CliRunner()
        result = runner.invoke(workflow_command, ["--type", "service", "--output", str(output)])
        assert result.exit_code == 0
        assert output.exists()
