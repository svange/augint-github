---
name: ai-promote
description: Promote staging (dev) to production (main) by creating an automerge PR. Use when dev/staging is ready for release, or saying 'release to production'.
argument-hint: "[--dry-run]"
---

Promote the configured staging branch to the production branch: $ARGUMENTS

Primary command:
- `uv run ai-tools repo promote --json $ARGUMENTS`

Report:
- source and target branches
- commits included in promotion
- promotion PR link and automerge state
- blockers that must be resolved before release

Transitional fallback:
- If `uv run ai-tools repo promote` is unavailable, state the tool gap clearly.
- Stop unless the user explicitly asks for a manual promotion flow.
