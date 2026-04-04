---
name: ai-standardize-renovate
description: Deploy or validate Renovate dependency update configuration. Detects repo type (library vs IaC), package ecosystem, and generates or fixes renovate.json5.
argument-hint: "[--validate] [--generate] [--fix]"
---

Deploy or validate Renovate configuration for this repository: $ARGUMENTS

Detects whether this is a library (main-only) or IaC repo (dev/main), identifies the package ecosystem, and generates or validates a standardized `renovate.json5`.

## Usage Examples

- `/ai-standardize-renovate` — Full run: detect, generate if missing, validate if present
- `/ai-standardize-renovate --validate` — Only check existing config for issues
- `/ai-standardize-renovate --generate` — Generate config (overwrites existing)
- `/ai-standardize-renovate --fix` — Auto-fix detected issues

## 1. Detect Repo Type

```bash
git fetch --all --prune 2>/dev/null
DEV_BRANCH=""
for candidate in dev develop staging; do
    git show-ref --verify --quiet "refs/remotes/origin/$candidate" 2>/dev/null && DEV_BRANCH=$candidate && break
done
```

If `DEV_BRANCH` set: **IaC repo**. Otherwise: **Library repo**.

## 2. Detect Ecosystem

```bash
[ -f "pyproject.toml" ] && echo "pep621"
[ -f "package.json" ] && echo "npm"
[ -f ".pre-commit-config.yaml" ] && echo "pre-commit"
# github-actions always included
```

## 3. Check for Existing Config

```bash
for f in renovate.json5 renovate.json .renovaterc .renovaterc.json; do
    [ -f "$f" ] && echo "Found: $f" && break
done
```

## 4. Generate renovate.json5

### Commit Prefix Scheme

| Update Type | Library Prefix | IaC Prefix | Automerge? | Release? |
|---|---|---|---|---|
| Vulnerability alert | `fix(deps):` | `fix(deps):` | Yes, bypass schedule | Patch |
| Prod dep patch | `chore(deps):` | `fix(deps):` | Yes | Lib: No, IaC: Patch |
| Prod dep minor | `chore(deps):` | `fix(deps):` | No | Lib: No, IaC: Patch |
| Prod dep major | `chore(deps):` | `fix(deps):` | No (dashboard) | Lib: No, IaC: Patch |
| Dev dep patch/minor | `chore(deps-dev):` | `chore(deps-dev):` | Yes, grouped | No |
| Dev dep major | `chore(deps-dev):` | `chore(deps-dev):` | No | No |
| GH Actions minor/patch | `ci(deps):` | `ci(deps):` | Yes, grouped | No |
| GH Actions major | `ci(deps):` | `ci(deps):` | No | No |
| Pre-commit hooks | `ci(deps):` | `ci(deps):` | Yes | No |
| semantic-release | `chore(deps-dev):` | `chore(deps-dev):` | Never | No |
| Lock file maintenance | `chore(deps):` | `chore(deps):` | Yes | No |

### Templates

Read the appropriate template from this skill directory and adapt it:

- **Library**: Read `library-template.json5` from `${CLAUDE_SKILL_DIR}`
- **IaC**: Read `iac-template.json5` from `${CLAUDE_SKILL_DIR}`

Adapt before writing:
- **enabledManagers**: only include detected managers from Step 2
- **For npm repos**: change `matchManagers` from `pep621` to `npm`, change `matchDepTypes` from `project.dependencies` to `dependencies` and from `project.optional-dependencies`/`dependency-groups` to `devDependencies`, change `python-semantic-release` to `semantic-release`
- **For IaC**: set `baseBranchPatterns` to the detected `DEV_BRANCH`

## 5. Validate Existing Config

Read existing config and check for:

1. **Deprecated options**: `baseBranches` should be `baseBranchPatterns`; `matchDepGroups` should be `matchCategories`
2. **Invalid managers**: `uv` is not valid (use `pep621`); `pip_requirements` is redundant with `pep621`
3. **Missing commit prefixes**: every `packageRules` entry needs `commitMessagePrefix`
4. **Wrong prefix for repo type**: library prod deps should use `chore(deps):`, IaC should use `fix(deps):`
5. **Missing vulnerability config**: must have `vulnerabilityAlerts` with `fix(deps):`, `at any time`, `automerge: true`
6. **Missing safety guards**: major prod deps need `dependencyDashboardApproval`, semantic-release needs `automerge: false`, GH Actions major should not automerge
7. **Missing platform config**: `platformAutomerge: true`, `rangeStrategy: auto`
8. **IaC-specific**: must have `baseBranchPatterns` targeting dev; should NOT use `automergeStrategy: squash`

## 6. Cross-Validate Semantic-Release

For Python repos: verify `exclude_commit_patterns` in pyproject.toml excludes `chore` and `ci` but NOT `fix`.

For Node repos: verify `releaseRules` in `.releaserc.json` map `chore`/`ci` to `false` and `fix` scope `deps` to `patch`.

If misaligned, suggest `/ai-standardize-release`.

## Error Handling

- **Not a git repo**: abort
- **No package manager detected**: warn, generate with only `github-actions`
- **Cannot determine repo type**: default to library (safer)
- **Config is `.json` not `.json5`**: offer to convert for comment support

## Final Output

```
=== Renovate Standardization Report ===
Repo type: Library (main-only) | Ecosystem: pep621 + github-actions + pre-commit
Action: [Generated | Validated | Fixed]

Issues:
  [PASS] Vulnerability alerts configured with fix(deps):
  [FAIL] Deprecated baseBranches (should be baseBranchPatterns)

Semantic-release alignment:
  [PASS] exclude_commit_patterns correctly excludes chore and ci

Next steps: /ai-standardize-release | /ai-standardize-repo
```
