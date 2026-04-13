from unittest.mock import MagicMock

import pytest

from gh_secrets_and_vars_async.rulesets import (
    display_rulesets,
    get_rulesets,
)


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.url = "https://api.github.com/repos/testowner/testrepo"
    repo.owner.type = "Organization"
    return repo


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


class TestDisplayRulesets:
    def test_display_empty(self, capsys):
        display_rulesets([])

    def test_display_with_data(self, capsys):
        ruleset = {
            "id": 42,
            "name": "Library gate",
            "target": "branch",
            "source_type": "Repository",
            "enforcement": "active",
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
            "rules": [
                {"type": "deletion"},
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "required_status_checks": [
                            {"context": "Code quality"},
                        ],
                    },
                },
            ],
            "bypass_actors": [
                {"actor_type": "DeployKey", "bypass_mode": "always"},
            ],
        }
        display_rulesets([ruleset])
