from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from gh_secrets_and_vars_async.rulesets import (
    apply_template,
    create_ruleset,
    delete_all_rulesets,
    display_rulesets,
    get_rulesets,
    rulesets_command,
)


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.url = "https://api.github.com/repos/testowner/testrepo"
    repo.owner.type = "Organization"
    return repo


@pytest.fixture
def sample_rulesets():
    return [
        {
            "id": 123,
            "name": "Test ruleset",
            "enforcement": "active",
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
            "rules": [
                {"type": "deletion"},
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "required_status_checks": [
                            {"context": "Unit tests"},
                        ]
                    },
                },
            ],
            "bypass_actors": [],
        }
    ]


class TestGetRulesets:
    def test_get_rulesets(self, mock_repo, sample_rulesets):
        # List endpoint returns summaries, then detail endpoint returns full data
        summaries = [{"id": 123, "name": "Test ruleset"}]
        mock_repo._requester.requestJsonAndCheck.side_effect = [
            ({}, summaries),  # GET /rulesets (list)
            ({}, sample_rulesets[0]),  # GET /rulesets/123 (detail)
        ]
        result = get_rulesets(mock_repo)
        assert len(result) == 1
        assert result[0]["name"] == "Test ruleset"
        assert mock_repo._requester.requestJsonAndCheck.call_count == 2


class TestDeleteAllRulesets:
    def test_delete_all(self, mock_repo, sample_rulesets):
        mock_repo._requester.requestJsonAndCheck.side_effect = [
            ({}, [{"id": 123, "name": "Test ruleset"}]),  # GET list
            ({}, sample_rulesets[0]),  # GET detail
            ({}, None),  # DELETE ruleset 123
        ]
        count = delete_all_rulesets(mock_repo)
        assert count == 1

    def test_delete_all_dry_run(self, mock_repo, sample_rulesets):
        mock_repo._requester.requestJsonAndCheck.side_effect = [
            ({}, [{"id": 123, "name": "Test ruleset"}]),  # GET list
            ({}, sample_rulesets[0]),  # GET detail
        ]
        count = delete_all_rulesets(mock_repo, dry_run=True)
        assert count == 1
        # GET list + GET detail, no DELETE
        assert mock_repo._requester.requestJsonAndCheck.call_count == 2

    def test_delete_all_empty(self, mock_repo):
        mock_repo._requester.requestJsonAndCheck.return_value = ({}, [])
        count = delete_all_rulesets(mock_repo)
        assert count == 0


class TestCreateRuleset:
    def test_create(self, mock_repo):
        template = {"name": "test", "target": "branch", "rules": []}
        mock_repo._requester.requestJsonAndCheck.return_value = (
            {},
            {"id": 456, "name": "test"},
        )
        result = create_ruleset(mock_repo, template)
        assert result["id"] == 456

    def test_create_strips_metadata(self, mock_repo):
        template = {
            "id": 999,
            "source_type": "Repository",
            "source": "old/repo",
            "name": "test",
            "rules": [],
        }
        mock_repo._requester.requestJsonAndCheck.return_value = ({}, {"id": 1, "name": "test"})
        create_ruleset(mock_repo, template)
        call_args = mock_repo._requester.requestJsonAndCheck.call_args
        payload = call_args[1]["input"]
        assert "id" not in payload
        assert "source_type" not in payload
        assert "source" not in payload

    def test_create_dry_run(self, mock_repo):
        template = {"name": "test", "rules": []}
        result = create_ruleset(mock_repo, template, dry_run=True)
        assert result["name"] == "test"
        mock_repo._requester.requestJsonAndCheck.assert_not_called()


class TestApplyTemplate:
    def test_apply_library(self, mock_repo):
        mock_repo._requester.requestJsonAndCheck.side_effect = [
            ({}, []),  # GET list (delete_all -> get_rulesets, empty)
            ({}, {"id": 1, "name": "Publishable library"}),  # POST
        ]
        results = apply_template(mock_repo, "library")
        assert len(results) == 1

    def test_apply_iac(self, mock_repo):
        mock_repo._requester.requestJsonAndCheck.side_effect = [
            ({}, []),  # GET list (delete_all, empty)
            ({}, {"id": 1, "name": "IaC Dev gate"}),  # POST dev
            ({}, {"id": 2, "name": "IaC Production gate"}),  # POST prod
        ]
        results = apply_template(mock_repo, "iac")
        assert len(results) == 2

    def test_apply_unknown_template(self, mock_repo):
        mock_repo._requester.requestJsonAndCheck.return_value = ({}, [])
        with pytest.raises(click.exceptions.BadParameter):
            apply_template(mock_repo, "unknown")

    def test_apply_deletes_existing_first(self, mock_repo):
        mock_repo._requester.requestJsonAndCheck.side_effect = [
            ({}, [{"id": 99, "name": "old"}]),  # GET list
            ({}, {"id": 99, "name": "old"}),  # GET detail
            ({}, None),  # DELETE 99
            ({}, {"id": 1, "name": "Publishable library"}),  # POST
        ]
        results = apply_template(mock_repo, "library")
        assert len(results) == 1
        calls = mock_repo._requester.requestJsonAndCheck.call_args_list
        assert calls[2][0] == ("DELETE", f"{mock_repo.url}/rulesets/99")


class TestDisplayRulesets:
    def test_display_empty(self, capsys):
        display_rulesets([])

    def test_display_with_data(self, sample_rulesets, capsys):
        display_rulesets(sample_rulesets)


class TestRulesetsCommandCLI:
    @patch("gh_secrets_and_vars_async.rulesets.get_github_repo")
    @patch("gh_secrets_and_vars_async.rulesets.load_env_config")
    def test_view_default(self, mock_env, mock_get_repo):
        mock_env.return_value = ("repo", "account", "token")
        mock_repo = MagicMock()
        mock_repo.url = "https://api.github.com/repos/account/repo"
        mock_repo._requester.requestJsonAndCheck.return_value = ({}, [])
        mock_get_repo.return_value = mock_repo

        runner = CliRunner()
        result = runner.invoke(rulesets_command, [])
        assert result.exit_code == 0

    @patch("gh_secrets_and_vars_async.rulesets.get_github_repo")
    @patch("gh_secrets_and_vars_async.rulesets.load_env_config")
    def test_apply_dry_run(self, mock_env, mock_get_repo):
        mock_env.return_value = ("repo", "account", "token")
        mock_repo = MagicMock()
        mock_repo.url = "https://api.github.com/repos/account/repo"
        mock_repo._requester.requestJsonAndCheck.return_value = ({}, [])
        mock_get_repo.return_value = mock_repo

        runner = CliRunner()
        result = runner.invoke(rulesets_command, ["--apply", "library", "--dry-run"])
        assert result.exit_code == 0

    @patch("gh_secrets_and_vars_async.rulesets.load_env_config")
    def test_missing_env(self, mock_env):
        mock_env.return_value = ("", "", "")
        runner = CliRunner()
        result = runner.invoke(rulesets_command, [])
        assert result.exit_code != 0
