---
name: ai-fix-repo-standards
description: "Audit and fix GitHub repository standards (rulesets, pipelines, auto-merge) using ai-gh. Use when repos drift from standard config, or saying 'fix repo standards'."
argument-hint: "[--dry-run] [--status-only]"
---

Audit and remediate GitHub repository standards using ai-gh: $ARGUMENTS

> **Workflow automation:** This skill is part of an automated workflow. It makes autonomous decisions for safe, reversible fixes (enabling auto-merge, applying rulesets). For destructive operations (regenerating pipelines), it shows a diff and asks for confirmation.

Detects repo type (IaC vs library), runs `ai-gh status` to identify mismatches in rulesets, pipelines, and settings, then applies targeted fixes for each failure. Re-verifies after fixes and reports results.

## Usage Examples

```bash
/ai-fix-repo-standards                # Full audit + fix cycle
/ai-fix-repo-standards --status-only  # Audit only, no fixes
/ai-fix-repo-standards --dry-run      # Show what would be fixed without applying
```

## Prerequisites

The `ai-gh` CLI (from `augint-github`) must be installed and a `.env` file must exist in the repo root with:

```
GH_REPO=repository-name
GH_ACCOUNT=github-account-or-org
GH_TOKEN=personal-access-token
```

Check prerequisites before proceeding:

```bash
# Verify ai-gh is available
command -v ai-gh >/dev/null 2>&1 || { echo "ERROR: ai-gh not found. Install augint-github first."; exit 1; }

# Verify .env exists with required keys
if [ ! -f ".env" ]; then
    echo "ERROR: No .env file found. Create one with GH_REPO, GH_ACCOUNT, GH_TOKEN."
    exit 1
fi
for key in GH_REPO GH_ACCOUNT GH_TOKEN; do
    grep -q "^${key}=" .env || echo "WARNING: $key not found in .env"
done
```

If prerequisites fail, stop and tell the user what is missing.

## 1. Detect Repo Type

Auto-detect whether this is an IaC or library repo. The `ai-gh` CLI does this internally, but we need the type for targeted fixes.

```bash
# Check for IaC indicators
REPO_TYPE="library"
for indicator in template.yaml template.yml samconfig.toml cdk.json main.tf; do
    if [ -f "$indicator" ]; then
        REPO_TYPE="iac"
        break
    fi
done

# Check pipeline content as fallback
if [ -f ".github/workflows/pipeline.yaml" ]; then
    if grep -qiE "sam|cdk|terraform" .github/workflows/pipeline.yaml 2>/dev/null; then
        REPO_TYPE="iac"
    fi
fi

# Check for dev branch (IaC repos typically have one)
DEV_BRANCH=""
for candidate in dev develop staging; do
    if git show-ref --verify --quiet "refs/remotes/origin/$candidate" 2>/dev/null; then
        DEV_BRANCH=$candidate
        break
    fi
done
[ -n "$DEV_BRANCH" ] && REPO_TYPE="iac"
```

Report: "Detected repo type: **$REPO_TYPE**"

## 2. Run Audit

Run `ai-gh status` to get the full audit report:

```bash
ai-gh status --type $REPO_TYPE --verbose
```

Capture the output. The status command reports checks in a table with PASS/FAIL/WARN status:

- **Auto-merge**: whether auto-merge is enabled on the repo
- **Rulesets**: whether rulesets match the expected template (iac or library)
- **Pipeline file**: whether `.github/workflows/pipeline.yaml` exists
- **Status checks alignment**: whether ruleset-required checks match actual pipeline job names

If `$ARGUMENTS` contains `--status-only`, display the audit results and stop here. Do not apply any fixes.

## 3. Parse Failures and Plan Fixes

For each FAIL or WARN result, determine the remediation action:

| Failure | Remediation Command | Risk Level |
|---------|---------------------|------------|
| Auto-merge disabled | `ai-gh config --auto-merge` | Safe (reversible) |
| Missing rulesets | `ai-gh rulesets --apply $REPO_TYPE` | Safe (additive) |
| Ruleset drift (wrong checks, enforcement, bypass) | `ai-gh rulesets --apply $REPO_TYPE` | Medium (overwrites rulesets) |
| Pipeline file missing | `ai-gh workflow --type $REPO_TYPE` | Medium (creates new file) |
| Status check mismatch (pipeline vs ruleset) | Regenerate pipeline and/or reapply rulesets | High (overwrites pipeline) |

If `$ARGUMENTS` contains `--dry-run`, show the planned fixes in a table and stop. Do not execute any commands.

```
=== Planned Fixes ===

| # | Issue | Action | Risk |
|---|-------|--------|------|
| 1 | Auto-merge disabled | ai-gh config --auto-merge | Safe |
| 2 | Missing rulesets | ai-gh rulesets --apply library | Safe |
| 3 | Pipeline missing | ai-gh workflow --type library | Medium |
```

## 4. Apply Fixes

Apply fixes in order from safest to most impactful:

### Step 1: Enable auto-merge (if failed)

```bash
ai-gh config --auto-merge
```

This is always safe and reversible. Apply without confirmation.

### Step 2: Apply rulesets (if missing or drifted)

```bash
ai-gh rulesets --apply $REPO_TYPE
```

This overwrites existing rulesets to match the template. Apply without confirmation for missing rulesets. For drifted rulesets, show the current vs expected state and apply (ruleset templates are the source of truth).

### Step 3: Generate pipeline (if missing)

```bash
# If pipeline.yaml does not exist at all
ai-gh workflow --type $REPO_TYPE
```

If the pipeline file already exists but has a status check mismatch, this is more complex:

```bash
# Preview what would change
ai-gh workflow --type $REPO_TYPE --dry-run > /tmp/new-pipeline.yaml
diff .github/workflows/pipeline.yaml /tmp/new-pipeline.yaml
```

**If the pipeline exists and needs updating**: Show the diff to the user and ask for confirmation before overwriting. The user may have custom pipeline steps that should be preserved.

```bash
# Only after user confirms
ai-gh workflow --type $REPO_TYPE --force
```

### Step 4: Resolve status check mismatches

If rulesets require checks that don't exist in the pipeline (or vice versa), this was likely fixed by steps 2-3 above. If mismatches remain after applying rulesets and pipeline:

1. Show the specific mismatch (which checks are in rulesets but not pipeline, and vice versa)
2. Flag for manual attention -- the user needs to either:
   - Add the missing pipeline jobs, or
   - Remove the extra ruleset checks
3. Do NOT auto-fix complex mismatches -- they often indicate intentional customization

## 5. Re-verify

Run the audit again to confirm fixes took effect:

```bash
ai-gh status --type $REPO_TYPE --verbose
```

## 6. Report Results

```
=== Remediation Report ===

Repo: $GH_ACCOUNT/$GH_REPO
Type: $REPO_TYPE

| Check | Before | After | Action Taken |
|-------|--------|-------|-------------|
| Auto-merge | FAIL | PASS | Enabled via ai-gh config |
| Rulesets | FAIL | PASS | Applied $REPO_TYPE template |
| Pipeline | PASS | PASS | No change needed |
| Status checks | WARN | WARN | Manual attention needed |

Fixed: X of Y issues
Remaining: Z issues requiring manual intervention

Manual action needed:
  - Status check "build-validation" is in rulesets but has no matching pipeline job.
    This is expected for IaC repos -- add a build-validation step to your pipeline
    or remove it from the ruleset if not needed.
```

If all checks pass, end with: "All checks passing. Repository is in compliance."

If issues remain, list each one with a brief explanation of why it could not be auto-fixed and what the user should do.

## Error Handling

- **ai-gh not installed**: Abort with install instructions (`pip install augint-github` or `uv add augint-github`)
- **Missing .env**: Abort with template showing required keys
- **GitHub API errors (401/403)**: Token is invalid or lacks permissions. Tell user to check GH_TOKEN has `repo` and `admin:org` scopes.
- **Rate limiting**: Wait and retry once. If still failing, report and suggest trying later.
- **Partial failure**: If some fixes succeed and others fail, report what worked and what did not. Do not roll back successful fixes.
- **Unknown repo type**: Default to library. Warn the user to verify with `--type iac` if this is an IaC repo.
