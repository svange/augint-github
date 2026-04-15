# TUI V2 -- Implemented as `ai-gh panel`

The interactive Textual dashboard described in this document has been implemented as `ai-gh panel`. See the [README](README.md#ai-gh-panel----interactive-health-dashboard) for usage.

## Architecture

```
src/gh_secrets_and_vars_async/
    health/
        __init__.py          # Public API: FetchContext, run_health_checks, run_all_health_checks
        _models.py           # Severity, HealthCheckResult, RepoHealth
        _registry.py         # HealthCheck protocol + registry
        checks/
            broken_ci.py     # CRITICAL: failing CI on main/dev
            renovate.py      # HIGH: missing renovate config
            renovate_prs.py  # HIGH: renovate PRs piling up
            repo_standards.py# MEDIUM: stub for future config audits
            stale_prs.py     # MEDIUM: PRs older than threshold
            open_issues.py   # LOW: many open issues
    panel_app.py             # Textual app (DashboardApp, MainScreen, DrillDownScreen, HelpScreen)
    panel_cmd.py             # Click command registration
    panel_themes.py          # Three themes: default, cyber, minimal
```

## Key Design Decisions

- **Separate from V1**: `panel` is a new command, not a `--v2` flag on `tui`. V1 (`ai-gh tui`) is preserved for non-TTY/passive use.
- **RepoHealth wraps RepoStatus**: Does not extend the existing dataclass, preserving backward compatibility.
- **Health check protocol + registry**: Checks self-register on import, making the system extensible.
- **Shared PR fetch (FetchContext)**: Pre-fetches open PRs once per repo and shares across checks to minimize API calls.
- **Resilient to development**: Workers use `exit_on_error=False`, graduated error notifications, and graceful cache fallback so the panel stays alive during code changes.
- **Optional dependency**: `textual` is gated under `[tui]` extras with a clean import error at CLI level.
