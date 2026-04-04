---
name: ai-standardize-release
description: Deploy or validate semantic-release configuration. Handles Python (python-semantic-release) and Node (JS semantic-release) repos with correct Renovate prefix alignment.
argument-hint: "[--validate] [--generate] [--fix]"
---

Deploy or validate semantic-release configuration for this repository: $ARGUMENTS

Ensures semantic-release is configured correctly and aligned with the Renovate commit prefix scheme.

## Usage Examples

- `/ai-standardize-release` — Full run: detect, generate if missing, validate if present
- `/ai-standardize-release --validate` — Only check existing config for issues
- `/ai-standardize-release --generate` — Generate config (overwrites existing)
- `/ai-standardize-release --fix` — Auto-fix detected issues

## 1. Detect Ecosystem and Repo Type

**Ecosystem:**
- Python: `[tool.semantic_release]` in `pyproject.toml`
- Node: `.releaserc.json`, `.releaserc.yml`, `release.config.js`, or `"release"` in `package.json`

**Repo type:** check for `dev`/`develop`/`staging` branch on remote. If found: IaC. Otherwise: library.

## 2. Generate Config (if missing or --generate)

### Templates

Read the appropriate template from this skill directory:

- **Python repos**: Read `python-template.toml` from `${CLAUDE_SKILL_DIR}`. Adapt:
  - Replace `{project-name}` with project name from `[project] name` in pyproject.toml
  - Replace `{package_name}` with the Python package name (under `src/`)
  - **IaC repos**: set `build_command = ""`, `dist_glob_patterns = []`, `assets = []`
  - **Libraries**: keep `build_command = "uv lock && uv build"`, `dist_glob_patterns = ["dist/*"]`
  - Verify `version_variables` path exists

- **Node repos**: Read `node-template.releaserc.json` from `${CLAUDE_SKILL_DIR}`. Adapt:
  - Verify `semantic-release` is in devDependencies
  - Required plugins: `@semantic-release/commit-analyzer`, `release-notes-generator`, `changelog`, `git`

## 3. Validate Existing Config

### Python (pyproject.toml)

1. **exclude_commit_patterns complete**: must exclude `chore`, `ci`, `refactor`, `style`, `test`, `build` (except `build(deps):`)
2. **Commit message has `[skip ci]`**: prevents infinite CI loops on version bump commits
3. **Branch config**: libraries and IaC should only have `branches.main` (no `branches.dev` with `prerelease = false` — that causes full releases on dev pushes)
4. **Tag format**: should use project-name prefix (`{name}-v{version}`) for multi-repo compatibility
5. **Build command**: `uv lock && uv build` for libraries, `""` for IaC
6. **Publish config**: `dist_glob_patterns = ["dist/*"]` for libraries, `[]` for IaC
7. **Version sources exist**: verify files in `version_toml` and `version_variables` actually exist
8. **Commit parser**: `angular` or `conventional` (both acceptable, recommend `angular`)

### Node (.releaserc.json)

1. **releaseRules present**: `chore`/`ci` must map to `false`, `fix` scope `deps` to `patch`
2. **Plugins complete**: commit-analyzer, release-notes-generator, changelog, git
3. **Git plugin message has `[skip ci]`**

## 4. Renovate Alignment Check

Cross-reference with Renovate config (if exists):

| Renovate Prefix | Expected Behavior | Check |
|---|---|---|
| `fix(deps):` | Triggers patch release | Must NOT be excluded |
| `chore(deps):` | No release | Must be excluded |
| `chore(deps-dev):` | No release | Must be excluded |
| `ci(deps):` | No release | Must be excluded |

If no Renovate config, suggest `/ai-standardize-renovate`.

## Error Handling

- **No pyproject.toml or package.json**: abort
- **Both Python and Node configs**: warn, ask which is primary
- **No semantic-release in dependencies**: suggest installing before generating
- **Version file not found**: warn about broken version_variables path

## Final Output

```
=== Semantic-Release Standardization Report ===
Ecosystem: Python | Repo type: Library (main-only)
Action: [Generated | Validated | Fixed]

Issues:
  [PASS] exclude_commit_patterns present and complete
  [PASS] Commit message includes [skip ci]
  [WARN] tag_format uses bare v{version} -- recommend project-name prefix

Renovate alignment:
  [PASS] fix(deps): not excluded | [PASS] chore(deps): excluded | [PASS] ci(deps): excluded

Next steps: /ai-standardize-renovate | /ai-standardize-repo
```
