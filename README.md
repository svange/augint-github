# Augmenting Integrations GitHub Tools

![ci status](https://github.com/svange/augint-github/actions/workflows/pipeline.yaml/badge.svg?branch=main)
![PyPI - Version](https://img.shields.io/pypi/v/augint-github)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg?style=flat-square)](https://conventionalcommits.org)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?style=flat-square&logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Made with GH Actions](https://img.shields.io/badge/CI-GitHub_Actions-blue?logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![semantic-release](https://img.shields.io/badge/%20%20%F0%9F%93%A6%F0%9F%93%80-semantic--release-e10079.svg)](https://github.com/semantic-release/semantic-release)

GitHub repository management CLI: push `.env` secrets and variables to GitHub Actions, enforce repo standards (rulesets, merge strategy, auto-merge), and bootstrap new repositories.

> Looking for the interactive health dashboard? It moved to [augint-tools](https://github.com/svange/augint-tools) -- run `ai-tools dashboard` there.

## Reports

| Report | Link |
|--------|------|
| API Documentation | [docs](https://svange.github.io/augint-github/) |
| Test Coverage | [coverage](https://svange.github.io/augint-github/coverage/) |
| Unit Test Results | [tests](https://svange.github.io/augint-github/tests/) |
| Security Scan | [security](https://svange.github.io/augint-github/security/) |
| License Compliance | [compliance](https://svange.github.io/augint-github/compliance/) |

## Installation

```bash
pip install augint-github
```

## Quick Start

```bash
# Push .env secrets and variables to a GitHub repository
ai-gh-push
```

## Commands

### `ai-gh sync` / `ai-gh-push`

Push `.env` secrets and variables to GitHub Actions.

```bash
ai-gh sync           # Sync current repo
ai-gh-push           # Shortcut entry point
```

### `ai-gh init`

Bootstrap a GitHub repository with settings and secrets.

### `ai-gh config`

Check or set repository configuration (merge strategy, auto-merge, etc.).

### `ai-gh rulesets`

View, apply, or delete branch rulesets on a GitHub repository.

### `ai-gh status`

Show repository configuration: auto-merge, non-default branches, and settings.

### `ai-gh chezmoi`

Back up `.env` to chezmoi and sync secrets to GitHub.

## Environment

- **Auth default**: `gh auth token` / GitHub CLI keyring session when available
- **`GH_TOKEN`**: optional explicit override in the current shell, or `.env` fallback
- **Python**: 3.12+
- **Package manager**: [uv](https://docs.astral.sh/uv/)

## Development

```bash
uv sync --all-extras                         # Install all dependencies
uv run pytest                                # Run tests
uv run pytest --cov=src --cov-fail-under=80  # Tests with coverage
uv run ruff check src/                       # Lint
uv run mypy src/                             # Type check
uv run pre-commit run --all-files            # All pre-commit hooks
```
