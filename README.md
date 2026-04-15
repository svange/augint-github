# Augmenting Integrations GitHub Tools

![ci status](https://github.com/svange/augint-github/actions/workflows/pipeline.yaml/badge.svg?branch=main)
![PyPI - Version](https://img.shields.io/pypi/v/augint-github)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg?style=flat-square)](https://conventionalcommits.org)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?style=flat-square&logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Made with GH Actions](https://img.shields.io/badge/CI-GitHub_Actions-blue?logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![semantic-release](https://img.shields.io/badge/%20%20%F0%9F%93%A6%F0%9F%93%80-semantic--release-e10079.svg)](https://github.com/semantic-release/semantic-release)

GitHub repository management CLI: push secrets, enforce repo standards, and surface health problems across your multi-repo ecosystem.

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

# For the interactive health panel (optional)
pip install 'augint-github[tui]'
```

## Quick Start

```bash
# Push .env secrets and variables to a GitHub repository
ai-gh-push

# Launch the interactive health dashboard
ai-gh panel --all --org myorg
```

## Commands

### `ai-gh panel` -- Interactive Health Dashboard

An interactive TUI that ranks your repositories by health, showing you the most important thing to work on next. Built with [Textual](https://github.com/Textualize/textual).

```bash
ai-gh panel --all                          # All repos for the authenticated user
ai-gh panel --all --org myorg              # All repos in an organization
ai-gh panel -i                             # Interactively select repos
ai-gh panel --all --theme cyber            # Neon green/cyan theme
ai-gh panel --all --stale-days 3           # Flag PRs stale after 3 days
ai-gh panel --all --refresh-seconds 120    # Refresh every 2 minutes
ai-gh panel --all --env-auth               # Force GH_TOKEN from .env
```

By default, `panel` uses `gh auth token` / your GitHub CLI keyring session when available.
Use `--env-auth` to force `GH_TOKEN` from `.env`.

**Health checks** (in priority order):

| Check | Severity | What it detects |
|-------|----------|-----------------|
| Broken CI | Critical | Failing workflows on main/dev branches |
| Renovate not configured | High | Missing `renovate.json5` or equivalent config |
| Renovate PRs piling up | High | 3+ open PRs from `renovate[bot]` |
| Repo standards | Medium | Stub -- placeholder for future config audits |
| Stale PRs | Medium | Open PRs older than `--stale-days` (default 5) |
| Many open issues | Low | More than 10 open issues |

**Keybindings**:

| Key | Action |
|-----|--------|
| `j` / `k` | Navigate up/down |
| `Enter` | Drill down into repo health details |
| `Escape` | Back to main view |
| `s` | Cycle sort mode (worst-first, alphabetical, by-problem-type) |
| `f` | Cycle filter (all, critical, high, medium, low) |
| `o` | Open repo in browser |
| `t` | Cycle theme (default, cyber, minimal) |
| `r` | Force refresh |
| `?` | Help screen |
| `q` | Quit |

**Themes**: `default` (muted blues), `cyber` (neon green/cyan/magenta), `minimal` (monochrome).

### `ai-gh tui` -- Live Status Dashboard

A passive Rich Live display showing pipeline status, issues, and PRs across repos. Auto-refreshes without keyboard interaction.

```bash
ai-gh tui --all --org myorg
ai-gh tui -i                     # Interactive repo selection
ai-gh tui --all --env-auth       # Force GH_TOKEN from .env
```

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
