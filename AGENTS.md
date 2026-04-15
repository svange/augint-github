# Repository Guidelines

## Project Structure & Module Organization
`src/gh_secrets_and_vars_async/` contains the Python package and Click-based CLI. Command entrypoints live in focused modules such as `*_cmd.py`, while `health/` holds repo-health models and registry code. `tests/` contains the pytest suite; keep reusable fixtures and sample inputs under `tests/resources/`. `rulesets/` stores JSON ruleset examples, `ci-resources/` holds report templates and CSS used in CI, and `dist/` is generated build output.

## Build, Test, and Development Commands
Use `uv` for all local workflows.

- `uv sync --all-extras`: install runtime, TUI, and developer dependencies.
- `uv run ai-gh --help`: inspect the CLI entrypoint locally.
- `uv run pytest`: run the full test suite.
- `uv run pytest --cov=src --cov-report=term-missing`: run tests with coverage output.
- `uv run ruff format src tests && uv run ruff check --fix src tests`: format and lint Python code.
- `uv run mypy src`: run static type checks.
- `uv run pre-commit run --all-files`: execute the same hooks CI runs first.
- `uv build`: create wheel and sdist artifacts in `dist/`.

## Coding Style & Naming Conventions
Target Python 3.12. Use 4-space indentation in Python, 2 spaces in YAML/JSON/TOML, and keep lines within Ruff’s 100-character limit. Prefer `snake_case` for modules, functions, and variables; follow the existing `test_XX_<area>.py` and `*_cmd.py` naming patterns. Let `ruff format` handle formatting and `ruff check` manage import ordering. MyPy is configured strictly on `src/`, so new public code should be fully typed.

## Testing Guidelines
Tests use `pytest`, `pytest-cov`, and `click.testing.CliRunner` for CLI behavior. Name test functions `test_*` and group new coverage by feature area. Reuse existing markers from `pyproject.toml` such as `end_to_end`, `no_infra`, and `skip_ci`. CI currently enforces a 50% overall coverage floor; avoid regressions and add tests for every behavior change.

## Commit & Pull Request Guidelines
Follow Conventional Commits, matching history like `feat: ...`, `fix: ...`, and release-generated `chore(release): ...`. Keep commits scoped and include `uv.lock` when dependency metadata changes. Pull requests should complete `.github/pull_request_template.md`: describe the change, expected behavior, local test steps, and documentation updates. Include terminal captures for `tui` or `panel` UI changes and link related issues when relevant.

## Security & Configuration Tips
Do not commit `.env`; pre-commit explicitly blocks it. Set `GH_TOKEN` for local GitHub API work, or rely on the documented `gh auth token` fallback.
