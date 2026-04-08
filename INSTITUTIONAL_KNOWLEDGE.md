# Institutional Notes: Library Repos

These notes extend the shared institutional notes for library-style repositories.
Merge them lightly and only when they add net-new guidance.

## Release and Branch Policy

- Libraries normally branch from and target `main`.
- Use merge commits on `main`.
- Let semantic-release determine versions from conventional commits.
- Do not create manual release tags.

## Development Flow

- Standard flow: pick issue -> prepare branch -> develop -> submit -> monitor.
- Validate locally before opening the PR.
- Keep release-triggering commit semantics intentional.

## `ai-tools` Usage

- Use `ai-tools repo ...` for normal repo workflows (status, issues, branch prep, submit, CI).
- Use `ai-tools standardize detect/audit/fix/verify` for standards alignment.
- Do not use workspace-only `ai-tools mono ...` commands for single-repo library work.
