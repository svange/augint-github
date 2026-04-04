---
name: ai-standardize-repo
description: Umbrella skill that enumerates all standardization tasks, shows repo status, and runs individual or all ai-standardize-* skills.
argument-hint: "[--all] [--status] [renovate|release|pipeline|precommit|dotfiles]"
---

Run repository standardization checks and fixes: $ARGUMENTS

Entry point for standardizing repository configuration. Shows what is configured, what is missing, and can run individual or all `ai-standardize-*` skills.

## Usage Examples

```bash
/ai-standardize-repo              # Show standardization status checklist
/ai-standardize-repo --status     # Same as above (explicit)
/ai-standardize-repo --all        # Run all standardization skills sequentially
/ai-standardize-repo renovate     # Run only ai-standardize-renovate
/ai-standardize-repo release      # Run only ai-standardize-release
/ai-standardize-repo pipeline     # Run only ai-standardize-pipeline
/ai-standardize-repo precommit    # Run only ai-standardize-precommit
/ai-standardize-repo dotfiles     # Run only ai-standardize-dotfiles
```

## 1. Available Standardization Skills

| Skill | Description | Key Config Files |
|-------|-------------|-----------------|
| `ai-standardize-renovate` | Renovate dependency update configuration | `renovate.json5` |
| `ai-standardize-release` | Semantic-release versioning configuration | `pyproject.toml` / `.releaserc.json` |
| `ai-standardize-pipeline` | CI/CD security scans, coverage, type checking | `.github/workflows/*.yml` |
| `ai-standardize-precommit` | Pre-commit hooks for formatting, linting, secrets | `.pre-commit-config.yaml` |
| `ai-standardize-dotfiles` | Editor config, gitignore, tool settings | `.editorconfig`, `.gitignore`, `pyproject.toml` |

## 2. Detect Repo Context

```bash
# Repo type
git fetch --all --prune 2>/dev/null
DEV_BRANCH=""
for candidate in dev develop staging; do
    if git show-ref --verify --quiet "refs/remotes/origin/$candidate" 2>/dev/null; then
        DEV_BRANCH=$candidate
        break
    fi
done
REPO_TYPE="Library (main-only)"
[ -n "$DEV_BRANCH" ] && REPO_TYPE="IaC ($DEV_BRANCH+main)"

# Ecosystem
ECOSYSTEM=""
[ -f "pyproject.toml" ] && ECOSYSTEM="${ECOSYSTEM}Python "
[ -f "package.json" ] && ECOSYSTEM="${ECOSYSTEM}Node "
[ -z "$ECOSYSTEM" ] && ECOSYSTEM="Unknown"
```

### Canary checks (existence + key content validation)

Run these checks to determine a three-level status for each area: **MISSING** (no config file), **DRIFT** (config exists but fails canary checks), or **OK** (config exists and passes all canary checks). Count errors (E) and warnings (W) separately.

```bash
# ── Dotfiles ──
DOTFILES_E=0; DOTFILES_W=0; DOTFILES_ISSUES=""
DOTFILES_STATUS="MISSING"
if [ -f ".editorconfig" ]; then
    DOTFILES_STATUS="OK"
    grep -q "root = true" .editorconfig 2>/dev/null || { DOTFILES_E=$((DOTFILES_E+1)); DOTFILES_ISSUES="${DOTFILES_ISSUES} .editorconfig missing root=true;"; }
fi
if [ -f ".gitignore" ]; then
    grep -q '\.env' .gitignore 2>/dev/null || { DOTFILES_E=$((DOTFILES_E+1)); DOTFILES_ISSUES="${DOTFILES_ISSUES} .gitignore not protecting .env;"; }
else
    DOTFILES_E=$((DOTFILES_E+1)); DOTFILES_ISSUES="${DOTFILES_ISSUES} .gitignore missing;"
fi
if [ -f "pyproject.toml" ]; then
    grep -q '\[tool.ruff\]' pyproject.toml 2>/dev/null || { DOTFILES_W=$((DOTFILES_W+1)); DOTFILES_ISSUES="${DOTFILES_ISSUES} no [tool.ruff];"; }
    grep -q 'line-length' pyproject.toml 2>/dev/null || { DOTFILES_W=$((DOTFILES_W+1)); DOTFILES_ISSUES="${DOTFILES_ISSUES} ruff line-length not set;"; }
    grep -q '\[tool.mypy\]' pyproject.toml 2>/dev/null || { DOTFILES_W=$((DOTFILES_W+1)); DOTFILES_ISSUES="${DOTFILES_ISSUES} no [tool.mypy];"; }
fi
[ "$DOTFILES_STATUS" != "MISSING" ] && [ $DOTFILES_E -gt 0 -o $DOTFILES_W -gt 0 ] && DOTFILES_STATUS="DRIFT"

# ── Pre-commit ──
PRECOMMIT_E=0; PRECOMMIT_W=0; PRECOMMIT_ISSUES=""
PRECOMMIT_STATUS="MISSING"
if [ -f ".pre-commit-config.yaml" ]; then
    PRECOMMIT_STATUS="OK"
    for hook in ruff-format ruff-check mypy uv-lock-check; do
        grep -q "$hook" .pre-commit-config.yaml 2>/dev/null || { PRECOMMIT_E=$((PRECOMMIT_E+1)); PRECOMMIT_ISSUES="${PRECOMMIT_ISSUES} missing $hook;"; }
    done
    # Check --no-sync on uv run entries
    if grep -q "uv run" .pre-commit-config.yaml 2>/dev/null; then
        grep "uv run" .pre-commit-config.yaml 2>/dev/null | grep -qv "\-\-no-sync" && { PRECOMMIT_W=$((PRECOMMIT_W+1)); PRECOMMIT_ISSUES="${PRECOMMIT_ISSUES} uv run missing --no-sync;"; }
    fi
elif [ -d ".husky" ]; then
    PRECOMMIT_STATUS="OK"
    # Node -- minimal canary: just confirm husky exists
fi
[ "$PRECOMMIT_STATUS" != "MISSING" ] && [ $PRECOMMIT_E -gt 0 -o $PRECOMMIT_W -gt 0 ] && PRECOMMIT_STATUS="DRIFT"

# ── CI/CD Pipeline ──
PIPELINE_E=0; PIPELINE_W=0; PIPELINE_ISSUES=""
PIPELINE_STATUS="MISSING"
if [ -d ".github/workflows" ]; then
    WF_COUNT=$(ls .github/workflows/*.yml .github/workflows/*.yaml 2>/dev/null | wc -l)
    PIPELINE_STATUS="OK"
    for tool in bandit pip-audit semgrep pip-licenses; do
        grep -rlq "$tool" .github/workflows/ 2>/dev/null || { PIPELINE_E=$((PIPELINE_E+1)); PIPELINE_ISSUES="${PIPELINE_ISSUES} missing $tool;"; }
    done
    grep -rlq "cov-fail-under" .github/workflows/ 2>/dev/null || { PIPELINE_E=$((PIPELINE_E+1)); PIPELINE_ISSUES="${PIPELINE_ISSUES} no coverage enforcement;"; }
    grep -rlq "mypy" .github/workflows/ 2>/dev/null || { PIPELINE_E=$((PIPELINE_E+1)); PIPELINE_ISSUES="${PIPELINE_ISSUES} no type checking;"; }
fi
[ "$PIPELINE_STATUS" != "MISSING" ] && [ $PIPELINE_E -gt 0 -o $PIPELINE_W -gt 0 ] && PIPELINE_STATUS="DRIFT"

# ── Renovate ──
RENOVATE_E=0; RENOVATE_W=0; RENOVATE_ISSUES=""
RENOVATE_STATUS="MISSING"
RENOVATE_FILE=""
for f in renovate.json5 renovate.json .renovaterc .renovaterc.json; do
    if [ -f "$f" ]; then
        RENOVATE_FILE="$f"
        RENOVATE_STATUS="OK"
        grep -q "vulnerabilityAlerts" "$f" 2>/dev/null || { RENOVATE_E=$((RENOVATE_E+1)); RENOVATE_ISSUES="${RENOVATE_ISSUES} missing vulnerabilityAlerts;"; }
        grep -q "baseBranches" "$f" 2>/dev/null && { RENOVATE_W=$((RENOVATE_W+1)); RENOVATE_ISSUES="${RENOVATE_ISSUES} deprecated baseBranches (use baseBranchPatterns);"; }
        break
    fi
done
[ "$RENOVATE_STATUS" != "MISSING" ] && [ $RENOVATE_E -gt 0 -o $RENOVATE_W -gt 0 ] && RENOVATE_STATUS="DRIFT"

# ── Semantic-release ──
RELEASE_E=0; RELEASE_W=0; RELEASE_ISSUES=""
RELEASE_STATUS="MISSING"
RELEASE_FILE=""
if [ -f "pyproject.toml" ] && grep -q "semantic_release" pyproject.toml 2>/dev/null; then
    RELEASE_STATUS="OK"
    RELEASE_FILE="pyproject.toml"
    grep -q "exclude_commit_patterns" pyproject.toml 2>/dev/null || { RELEASE_E=$((RELEASE_E+1)); RELEASE_ISSUES="${RELEASE_ISSUES} missing exclude_commit_patterns;"; }
    grep -q "skip ci" pyproject.toml 2>/dev/null || { RELEASE_E=$((RELEASE_E+1)); RELEASE_ISSUES="${RELEASE_ISSUES} missing [skip ci] in commit message;"; }
    grep -q "tag_format" pyproject.toml 2>/dev/null || { RELEASE_W=$((RELEASE_W+1)); RELEASE_ISSUES="${RELEASE_ISSUES} tag_format not set;"; }
fi
for f in .releaserc.json .releaserc.yml .releaserc.js release.config.js release.config.cjs; do
    if [ -f "$f" ]; then
        RELEASE_STATUS="OK"
        RELEASE_FILE="$f"
        break
    fi
done
if [ "$RELEASE_STATUS" = "MISSING" ] && [ -f "package.json" ] && grep -q '"release"' package.json 2>/dev/null; then
    RELEASE_STATUS="OK"
    RELEASE_FILE="package.json"
fi
[ "$RELEASE_STATUS" != "MISSING" ] && [ $RELEASE_E -gt 0 -o $RELEASE_W -gt 0 ] && RELEASE_STATUS="DRIFT"
```

## 3. Display Status Checklist

For each area, display its three-level status using the canary check results from Step 2:

- **`[  OK   ]`** -- config present and passes all canary checks
- **`[ DRIFT ]`** -- config present but has issues (show `{E}E {W}W` counts and brief issue list)
- **`[MISSING]`** -- config file not found

```
=== Repository Standardization Status ===

Repo type: {REPO_TYPE}
Ecosystem: {ECOSYSTEM}

  Status    | Area             | Detail
  ----------+------------------+-------------------------------------------
  [{status}] | Dotfiles         | {detail or issue summary}
  [{status}] | Pre-commit       | {detail or issue summary}
  [{status}] | CI/CD pipeline   | {detail or issue summary}
  [{status}] | Renovate         | {detail or issue summary}
  [{status}] | Semantic-release | {detail or issue summary}

Legend: OK = passes canary checks, DRIFT = issues found, MISSING = no config
```

For the **Detail** column:
- **OK**: list what was found (e.g., `.editorconfig, .gitignore, ruff, mypy`)
- **DRIFT**: show `{E}E {W}W` counts and the specific issues (e.g., `2E 0W -- missing ruff-format, mypy hooks`)
- **MISSING**: say `no config found`

Then show next steps, prioritizing DRIFT and MISSING areas first:

```
Next steps:
  /ai-standardize-repo {area}       # {STATUS} -- {action hint}
  ...
  /ai-standardize-repo --all        # Run all checks and fixes
```

Action hints by status:
- **MISSING** -> `generate config`
- **DRIFT** -> `run to diagnose and fix`
- **OK** -> `validate in detail` (only show if user might want deeper checks)

## 4. Run Skills

### If `$ARGUMENTS` contains `--all`:

Run each standardization skill in sequence (order matters -- later skills may reference earlier ones):

1. `/ai-standardize-dotfiles` -- foundational config files
2. `/ai-standardize-precommit` -- developer quality gates
3. `/ai-standardize-pipeline` -- CI/CD checks
4. `/ai-standardize-renovate` -- dependency management
5. `/ai-standardize-release` -- versioning (depends on renovate prefix scheme)

Report results from each, then show the combined summary.

### If `$ARGUMENTS` contains a skill name:

Map shorthand to full skill:
- `renovate` -> execute `/ai-standardize-renovate`
- `release` -> execute `/ai-standardize-release`
- `pipeline` -> execute `/ai-standardize-pipeline`
- `precommit` -> execute `/ai-standardize-precommit`
- `dotfiles` -> execute `/ai-standardize-dotfiles`

If the name does not match any known skill, show the available skills table from Step 1.

### If `$ARGUMENTS` is empty or `--status`:

Just show the status checklist from Step 3. Do not run any validation or generation.

## 5. Combined Summary (after --all)

```
=== Standardization Summary ===

Repo type: IaC (dev+main)
Ecosystem: Python

| Skill | Action | Issues | Fixed | Remaining |
|-------|--------|--------|-------|-----------|
| Dotfiles | Generated | 1 | 1 | 0 |
| Pre-commit | Fixed | 3 | 3 | 0 |
| Pipeline | Validated | 2 | 0 | 2 |
| Renovate | Validated | 1 | 1 | 0 |
| Release | Validated | 0 | 0 | 0 |

Remaining issues:
  [FAIL] Pipeline: Semgrep SAST scanning missing
  [FAIL] Pipeline: License compliance checking missing

Overall: 2 issues remaining. Add missing CI jobs manually or re-run individual skills with --fix.
```

## Error Handling

- **Not a git repo**: Abort with error
- **Unknown skill name**: Show available skills table
- **No ecosystem detected**: Warn, suggest checking if this is the correct directory
- **Skill fails mid-run during --all**: Report the failure, continue with remaining skills, include failure in summary
