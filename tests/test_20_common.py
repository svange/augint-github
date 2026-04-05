import pytest

from gh_secrets_and_vars_async.common import load_template


class TestLoadTemplate:
    def test_load_ruleset_iac_dev(self):
        template = load_template("rulesets", "iac_dev")
        assert isinstance(template, dict)
        assert template["name"] == "IaC Dev gate"
        assert template["target"] == "branch"
        assert template["enforcement"] == "active"
        assert any(r["type"] == "required_status_checks" for r in template["rules"])

    def test_load_ruleset_iac_production(self):
        template = load_template("rulesets", "iac_production")
        assert template["name"] == "IaC Production gate"
        checks = None
        for rule in template["rules"]:
            if rule["type"] == "required_status_checks":
                checks = rule["parameters"]["required_status_checks"]
        assert checks is not None
        check_names = [c["context"] for c in checks]
        assert "Pre-commit checks" in check_names
        assert "Security scanning" in check_names
        assert "Unit tests" in check_names
        assert "License compliance" in check_names

    def test_load_ruleset_publishable_library(self):
        template = load_template("rulesets", "publishable_library")
        assert template["name"] == "Publishable library"
        checks = None
        for rule in template["rules"]:
            if rule["type"] == "required_status_checks":
                checks = rule["parameters"]["required_status_checks"]
        check_names = [c["context"] for c in checks]
        assert "License compliance" in check_names
        assert "Pre-commit checks" in check_names

    def test_load_workflow_library(self):
        content = load_template("workflows", "library_pipeline")
        assert isinstance(content, str)
        assert "Pre-commit checks" in content
        assert "License compliance" in content

    def test_load_workflow_iac(self):
        content = load_template("workflows", "iac_pipeline")
        assert isinstance(content, str)
        assert "Build validation" in content
        assert "Integration tests" in content
        assert "Smoke tests" in content

    def test_load_nonexistent_template(self):
        with pytest.raises((FileNotFoundError, TypeError, ModuleNotFoundError)):
            load_template("rulesets", "nonexistent")

    def test_all_rulesets_have_bypass_actors(self):
        for name in ["iac_dev", "iac_production", "publishable_library"]:
            template = load_template("rulesets", name)
            bypass = template.get("bypass_actors", [])
            actor_types = [b["actor_type"] for b in bypass]
            assert "RepositoryRole" in actor_types, f"{name} missing Maintain bypass"
            assert "DeployKey" in actor_types, f"{name} missing DeployKey bypass"

    def test_all_rulesets_have_deletion_protection(self):
        for name in ["iac_dev", "iac_production", "publishable_library"]:
            template = load_template("rulesets", name)
            rule_types = [r["type"] for r in template["rules"]]
            assert "deletion" in rule_types
            assert "non_fast_forward" in rule_types
