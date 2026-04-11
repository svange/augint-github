import json
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from gh_secrets_and_vars_async.rulesets import (
    _canonical_ruleset,
    apply_ruleset_spec,
    create_ruleset,
    display_rulesets,
    find_replaceable_ruleset,
    get_rulesets,
    rulesets_command,
    rulesets_match,
    validate_ruleset_spec,
)


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.url = "https://api.github.com/repos/testowner/testrepo"
    repo.owner.type = "Organization"
    return repo


@pytest.fixture
def sample_spec():
    """A valid caller-supplied ruleset spec."""
    return {
        "name": "Library gate",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {"context": "Code quality"},
                        {"context": "Unit tests"},
                    ],
                },
            },
        ],
        "bypass_actors": [
            {"actor_type": "DeployKey", "bypass_mode": "always"},
            {"actor_id": 4, "actor_type": "RepositoryRole", "bypass_mode": "always"},
        ],
    }


@pytest.fixture
def sample_existing_ruleset(sample_spec):
    """Same as sample_spec but with the metadata fields GitHub adds on read."""
    existing = dict(sample_spec)
    existing["id"] = 42
    existing["source_type"] = "Repository"
    existing["source"] = "testowner/testrepo"
    return existing


# ---------------------------------------------------------------------------
# get_rulesets / create_ruleset / display_rulesets
# ---------------------------------------------------------------------------


class TestGetRulesets:
    def test_fetches_summary_then_detail(self, mock_repo):
        summaries = [{"id": 123, "name": "Test"}]
        detail = {"id": 123, "name": "Test", "target": "branch"}
        mock_repo._requester.requestJsonAndCheck.side_effect = [
            ({}, summaries),
            ({}, detail),
        ]
        result = get_rulesets(mock_repo)
        assert len(result) == 1
        assert result[0]["target"] == "branch"
        assert mock_repo._requester.requestJsonAndCheck.call_count == 2


class TestCreateRuleset:
    def test_posts_and_strips_metadata(self, mock_repo):
        spec = {
            "id": 999,
            "source_type": "Repository",
            "source": "old/repo",
            "name": "x",
            "target": "branch",
            "rules": [],
        }
        mock_repo._requester.requestJsonAndCheck.return_value = ({}, {"id": 1, "name": "x"})
        create_ruleset(mock_repo, spec)
        payload = mock_repo._requester.requestJsonAndCheck.call_args[1]["input"]
        assert "id" not in payload
        assert "source_type" not in payload
        assert "source" not in payload
        assert payload["name"] == "x"

    def test_dry_run_does_not_call_api(self, mock_repo):
        spec = {"name": "x", "target": "branch", "rules": []}
        result = create_ruleset(mock_repo, spec, dry_run=True)
        assert result["name"] == "x"
        mock_repo._requester.requestJsonAndCheck.assert_not_called()


class TestDisplayRulesets:
    def test_display_empty(self, capsys):
        display_rulesets([])

    def test_display_with_data(self, sample_existing_ruleset, capsys):
        display_rulesets([sample_existing_ruleset])


# ---------------------------------------------------------------------------
# validate_ruleset_spec
# ---------------------------------------------------------------------------


class TestValidateRulesetSpec:
    def test_accepts_valid_spec(self, sample_spec):
        validate_ruleset_spec(sample_spec)  # does not raise

    def test_rejects_non_dict(self):
        with pytest.raises(click.ClickException, match="JSON object"):
            validate_ruleset_spec("not a dict")

    def test_rejects_missing_name(self, sample_spec):
        del sample_spec["name"]
        with pytest.raises(click.ClickException, match="name"):
            validate_ruleset_spec(sample_spec)

    def test_rejects_empty_name(self, sample_spec):
        sample_spec["name"] = ""
        with pytest.raises(click.ClickException, match="non-empty"):
            validate_ruleset_spec(sample_spec)

    def test_rejects_non_string_name(self, sample_spec):
        sample_spec["name"] = 123
        with pytest.raises(click.ClickException, match="non-empty"):
            validate_ruleset_spec(sample_spec)

    def test_rejects_non_branch_target(self, sample_spec):
        sample_spec["target"] = "repository"
        with pytest.raises(click.ClickException, match="target"):
            validate_ruleset_spec(sample_spec)

    def test_rejects_tag_target(self, sample_spec):
        sample_spec["target"] = "tag"
        with pytest.raises(click.ClickException, match="target"):
            validate_ruleset_spec(sample_spec)

    def test_rejects_missing_rules(self, sample_spec):
        del sample_spec["rules"]
        with pytest.raises(click.ClickException, match="rules"):
            validate_ruleset_spec(sample_spec)

    def test_rejects_non_list_rules(self, sample_spec):
        sample_spec["rules"] = "not a list"
        with pytest.raises(click.ClickException, match="list"):
            validate_ruleset_spec(sample_spec)

    def test_rejects_empty_dict(self):
        with pytest.raises(click.ClickException):
            validate_ruleset_spec({})


# ---------------------------------------------------------------------------
# find_replaceable_ruleset -- the T0-1 safety filter
# ---------------------------------------------------------------------------


class TestFindReplaceableRuleset:
    """Regression tests for T0-1 (data-loss bug).

    find_replaceable_ruleset must never return a ruleset that is:
    - org-scope (target == "repository")
    - tag-scope (target == "tag")
    - org-inherited (source_type != "Repository")
    - name mismatch

    A previous bug deleted all rulesets on apply, which would have wiped
    shared org-scope base rulesets (e.g. "Base Repo Rules" on ai-lls-*).
    """

    @patch("gh_secrets_and_vars_async.rulesets.get_rulesets")
    def test_returns_matching_repo_scope_branch_ruleset(self, mock_get, mock_repo):
        mock_get.return_value = [
            {
                "id": 1,
                "name": "IaC",
                "target": "branch",
                "source_type": "Repository",
            },
        ]
        result = find_replaceable_ruleset(mock_repo, "IaC")
        assert result is not None
        assert result["id"] == 1

    @patch("gh_secrets_and_vars_async.rulesets.get_rulesets")
    def test_skips_repository_target(self, mock_get, mock_repo):
        """Never touch a repository-scope ruleset even with matching name."""
        mock_get.return_value = [
            {
                "id": 14891896,
                "name": "IaC",  # pretend-malicious: matching name, wrong scope
                "target": "repository",
                "source_type": "Organization",
            },
        ]
        assert find_replaceable_ruleset(mock_repo, "IaC") is None

    @patch("gh_secrets_and_vars_async.rulesets.get_rulesets")
    def test_skips_tag_target(self, mock_get, mock_repo):
        mock_get.return_value = [
            {"id": 2, "name": "IaC", "target": "tag", "source_type": "Repository"},
        ]
        assert find_replaceable_ruleset(mock_repo, "IaC") is None

    @patch("gh_secrets_and_vars_async.rulesets.get_rulesets")
    def test_skips_org_inherited_branch_ruleset(self, mock_get, mock_repo):
        """Even branch-scope, if source_type is Organization, leave it alone."""
        mock_get.return_value = [
            {
                "id": 3,
                "name": "IaC",
                "target": "branch",
                "source_type": "Organization",
            },
        ]
        assert find_replaceable_ruleset(mock_repo, "IaC") is None

    @patch("gh_secrets_and_vars_async.rulesets.get_rulesets")
    def test_skips_name_mismatch(self, mock_get, mock_repo):
        mock_get.return_value = [
            {
                "id": 4,
                "name": "Different name",
                "target": "branch",
                "source_type": "Repository",
            },
        ]
        assert find_replaceable_ruleset(mock_repo, "IaC") is None

    @patch("gh_secrets_and_vars_async.rulesets.get_rulesets")
    def test_t0_1_regression_mixed_repo(self, mock_get, mock_repo):
        """Concrete T0-1 scenario: a repo with (a) org-scope base rules,
        (b) an org-inherited branch ruleset, (c) a repo-scope branch ruleset
        with a different name, (d) a repo-scope branch ruleset with the
        matching name. find_replaceable_ruleset must return only (d).
        """
        mock_get.return_value = [
            {
                "id": 14891896,
                "name": "Base Repo Rules",
                "target": "repository",
                "source_type": "Organization",
            },
            {
                "id": 14891897,
                "name": "Org default",
                "target": "branch",
                "source_type": "Organization",
            },
            {
                "id": 14891898,
                "name": "Legacy gate",
                "target": "branch",
                "source_type": "Repository",
            },
            {
                "id": 14891899,
                "name": "IaC",
                "target": "branch",
                "source_type": "Repository",
            },
        ]
        result = find_replaceable_ruleset(mock_repo, "IaC")
        assert result is not None
        assert result["id"] == 14891899
        assert result["name"] == "IaC"

    @patch("gh_secrets_and_vars_async.rulesets.get_rulesets")
    def test_returns_none_when_no_match(self, mock_get, mock_repo):
        mock_get.return_value = []
        assert find_replaceable_ruleset(mock_repo, "anything") is None


# ---------------------------------------------------------------------------
# rulesets_match / _canonical_ruleset
# ---------------------------------------------------------------------------


class TestRulesetsMatch:
    def test_identical_specs_match(self, sample_spec):
        assert rulesets_match(sample_spec, sample_spec) is True

    def test_existing_with_metadata_matches_spec(self, sample_spec, sample_existing_ruleset):
        assert rulesets_match(sample_existing_ruleset, sample_spec) is True

    def test_drifted_enforcement_does_not_match(self, sample_spec):
        drifted = dict(sample_spec)
        drifted["enforcement"] = "disabled"
        assert rulesets_match(drifted, sample_spec) is False

    def test_added_status_check_does_not_match(self, sample_spec):
        drifted = json.loads(json.dumps(sample_spec))
        for rule in drifted["rules"]:
            if rule["type"] == "required_status_checks":
                rule["parameters"]["required_status_checks"].append({"context": "New check"})
        assert rulesets_match(drifted, sample_spec) is False

    def test_reordered_status_checks_match(self, sample_spec):
        reordered = json.loads(json.dumps(sample_spec))
        for rule in reordered["rules"]:
            if rule["type"] == "required_status_checks":
                rule["parameters"]["required_status_checks"].reverse()
        assert rulesets_match(reordered, sample_spec) is True

    def test_reordered_rules_match(self, sample_spec):
        reordered = json.loads(json.dumps(sample_spec))
        reordered["rules"].reverse()
        assert rulesets_match(reordered, sample_spec) is True

    def test_reordered_bypass_actors_match(self, sample_spec):
        reordered = json.loads(json.dumps(sample_spec))
        reordered["bypass_actors"].reverse()
        assert rulesets_match(reordered, sample_spec) is True

    def test_canonical_strips_id_and_source(self, sample_existing_ruleset):
        canon = _canonical_ruleset(sample_existing_ruleset)
        assert "id" not in canon
        assert "source" not in canon
        assert "source_type" not in canon


# ---------------------------------------------------------------------------
# apply_ruleset_spec
# ---------------------------------------------------------------------------


class TestApplyRulesetSpec:
    @patch("gh_secrets_and_vars_async.rulesets.find_replaceable_ruleset")
    def test_creates_when_no_existing(self, mock_find, mock_repo, sample_spec):
        mock_find.return_value = None
        mock_repo._requester.requestJsonAndCheck.return_value = (
            {},
            {"id": 100, "name": sample_spec["name"]},
        )
        result = apply_ruleset_spec(mock_repo, sample_spec)
        assert result is not None
        assert result["id"] == 100
        # One POST, no DELETE
        calls = mock_repo._requester.requestJsonAndCheck.call_args_list
        assert len(calls) == 1
        assert calls[0][0][0] == "POST"

    @patch("gh_secrets_and_vars_async.rulesets.find_replaceable_ruleset")
    def test_noop_when_existing_matches(
        self, mock_find, mock_repo, sample_spec, sample_existing_ruleset
    ):
        mock_find.return_value = sample_existing_ruleset
        result = apply_ruleset_spec(mock_repo, sample_spec)
        assert result is sample_existing_ruleset
        # No DELETE, no POST
        mock_repo._requester.requestJsonAndCheck.assert_not_called()

    @patch("gh_secrets_and_vars_async.rulesets.find_replaceable_ruleset")
    def test_replaces_when_drifted(
        self, mock_find, mock_repo, sample_spec, sample_existing_ruleset
    ):
        drifted = json.loads(json.dumps(sample_existing_ruleset))
        drifted["enforcement"] = "disabled"
        mock_find.return_value = drifted
        mock_repo._requester.requestJsonAndCheck.side_effect = [
            ({}, None),  # DELETE
            ({}, {"id": 101, "name": sample_spec["name"]}),  # POST
        ]
        result = apply_ruleset_spec(mock_repo, sample_spec)
        assert result is not None
        assert result["id"] == 101
        calls = mock_repo._requester.requestJsonAndCheck.call_args_list
        assert calls[0][0][0] == "DELETE"
        assert calls[0][0][1].endswith(f"/rulesets/{drifted['id']}")
        assert calls[1][0][0] == "POST"

    @patch("gh_secrets_and_vars_async.rulesets.find_replaceable_ruleset")
    def test_dry_run_does_not_mutate(
        self, mock_find, mock_repo, sample_spec, sample_existing_ruleset
    ):
        drifted = json.loads(json.dumps(sample_existing_ruleset))
        drifted["enforcement"] = "disabled"
        mock_find.return_value = drifted
        result = apply_ruleset_spec(mock_repo, sample_spec, dry_run=True)
        assert result is not None
        mock_repo._requester.requestJsonAndCheck.assert_not_called()

    def test_invalid_spec_raises_before_api(self, mock_repo):
        with pytest.raises(click.ClickException):
            apply_ruleset_spec(mock_repo, {"name": "bad"})
        mock_repo._requester.requestJsonAndCheck.assert_not_called()

    @patch("gh_secrets_and_vars_async.rulesets.get_rulesets")
    def test_t0_1_regression_preserves_org_scope(self, mock_get, mock_repo, sample_spec):
        """Full end-to-end T0-1 regression: repo has an org-scope base
        ruleset with the SAME name that a caller wants to apply. apply must
        not touch the org-scope one, and must create a new repo-scope one.
        """
        sample_spec["name"] = "Base Repo Rules"
        mock_get.return_value = [
            {
                "id": 14891896,
                "name": "Base Repo Rules",
                "target": "repository",
                "source_type": "Organization",
                "enforcement": "active",
                "rules": [],
            },
        ]
        mock_repo._requester.requestJsonAndCheck.side_effect = [
            ({}, {"id": 999, "name": "Base Repo Rules"}),  # POST only
        ]
        result = apply_ruleset_spec(mock_repo, sample_spec)
        assert result is not None
        assert result["id"] == 999
        # Crucial: the org-scope ruleset (id 14891896) must NOT be deleted.
        delete_calls = [
            c
            for c in mock_repo._requester.requestJsonAndCheck.call_args_list
            if c[0][0] == "DELETE"
        ]
        assert delete_calls == []


# ---------------------------------------------------------------------------
# CLI: rulesets view / rulesets apply
# ---------------------------------------------------------------------------


class TestRulesetsCLI:
    @patch("gh_secrets_and_vars_async.rulesets.get_rulesets")
    @patch("gh_secrets_and_vars_async.rulesets.get_github_repo")
    @patch("gh_secrets_and_vars_async.rulesets.load_env_config")
    def test_view_default(self, mock_env, mock_get_repo, mock_rulesets):
        mock_env.return_value = ("repo", "account", "token")
        mock_get_repo.return_value = MagicMock()
        mock_rulesets.return_value = []

        runner = CliRunner()
        result = runner.invoke(rulesets_command, ["view"])
        assert result.exit_code == 0

    @patch("gh_secrets_and_vars_async.rulesets.load_env_config")
    def test_view_missing_env(self, mock_env):
        mock_env.return_value = ("", "", "")
        runner = CliRunner()
        result = runner.invoke(rulesets_command, ["view"])
        assert result.exit_code != 0

    @patch("gh_secrets_and_vars_async.rulesets.apply_ruleset_spec")
    @patch("gh_secrets_and_vars_async.rulesets.get_github_repo")
    @patch("gh_secrets_and_vars_async.rulesets.load_env_config")
    def test_apply_reads_and_applies_spec(
        self, mock_env, mock_get_repo, mock_apply, tmp_path, sample_spec
    ):
        mock_env.return_value = ("repo", "account", "token")
        mock_get_repo.return_value = MagicMock()
        mock_apply.return_value = {"id": 1, "name": sample_spec["name"]}

        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(sample_spec))

        runner = CliRunner()
        result = runner.invoke(rulesets_command, ["apply", str(spec_path)])
        assert result.exit_code == 0
        mock_apply.assert_called_once()
        call_spec = mock_apply.call_args[0][1]
        assert call_spec["name"] == sample_spec["name"]

    @patch("gh_secrets_and_vars_async.rulesets.apply_ruleset_spec")
    @patch("gh_secrets_and_vars_async.rulesets.get_github_repo")
    @patch("gh_secrets_and_vars_async.rulesets.load_env_config")
    def test_apply_dry_run(self, mock_env, mock_get_repo, mock_apply, tmp_path, sample_spec):
        mock_env.return_value = ("repo", "account", "token")
        mock_get_repo.return_value = MagicMock()
        mock_apply.return_value = None

        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(sample_spec))

        runner = CliRunner()
        result = runner.invoke(rulesets_command, ["apply", str(spec_path), "-d"])
        assert result.exit_code == 0
        assert mock_apply.call_args[1]["dry_run"] is True

    def test_apply_missing_file(self):
        runner = CliRunner()
        result = runner.invoke(rulesets_command, ["apply", "/nonexistent/spec.json"])
        assert result.exit_code != 0

    def test_apply_invalid_json(self, tmp_path):
        spec_path = tmp_path / "bad.json"
        spec_path.write_text("{not valid json")
        runner = CliRunner()
        result = runner.invoke(rulesets_command, ["apply", str(spec_path)])
        assert result.exit_code != 0
        assert "json" in result.output.lower() or "valid" in result.output.lower()

    def test_apply_invalid_spec_fields(self, tmp_path):
        spec_path = tmp_path / "bad.json"
        spec_path.write_text(json.dumps({"name": "x"}))  # missing target/rules
        runner = CliRunner()
        result = runner.invoke(rulesets_command, ["apply", str(spec_path)])
        assert result.exit_code != 0

    def test_rulesets_help_lists_subcommands(self):
        runner = CliRunner()
        result = runner.invoke(rulesets_command, ["--help"])
        assert result.exit_code == 0
        assert "view" in result.output
        assert "apply" in result.output
