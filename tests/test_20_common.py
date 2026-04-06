import pytest

from gh_secrets_and_vars_async.common import load_template, normalize_type


class TestLoadTemplate:
    def test_load_ruleset_service_dev(self):
        template = load_template("rulesets", "service_dev")
        assert isinstance(template, dict)
        assert template["name"] == "Service Dev gate"
        assert template["target"] == "branch"
        assert template["enforcement"] == "active"
        assert any(r["type"] == "required_status_checks" for r in template["rules"])

    def test_load_ruleset_service_production(self):
        template = load_template("rulesets", "service_production")
        assert template["name"] == "Service Production gate"
        checks = None
        for rule in template["rules"]:
            if rule["type"] == "required_status_checks":
                checks = rule["parameters"]["required_status_checks"]
        assert checks is not None
        check_names = [c["context"] for c in checks]
        assert "Code quality" in check_names
        assert "Security scanning" in check_names
        assert "Unit tests" in check_names
        assert "License compliance" in check_names

    def test_load_ruleset_library(self):
        template = load_template("rulesets", "library")
        assert template["name"] == "Library"
        checks = None
        for rule in template["rules"]:
            if rule["type"] == "required_status_checks":
                checks = rule["parameters"]["required_status_checks"]
        check_names = [c["context"] for c in checks]
        assert "License compliance" in check_names
        assert "Code quality" in check_names

    def test_load_workflow_library(self):
        content = load_template("workflows", "py_library_pipeline")
        assert isinstance(content, str)
        assert "Code quality" in content
        assert "License compliance" in content

    def test_load_workflow_service(self):
        content = load_template("workflows", "py_service_pipeline")
        assert isinstance(content, str)
        assert "License compliance" in content
        assert "Integration tests" in content
        assert "Smoke tests" in content

    def test_load_workflow_ts_library(self):
        content = load_template("workflows", "ts_library_pipeline")
        assert isinstance(content, str)
        assert "Code quality" in content
        assert "pnpm" in content

    def test_load_workflow_ts_service(self):
        content = load_template("workflows", "ts_service_pipeline")
        assert isinstance(content, str)
        assert "Code quality" in content
        assert "Integration tests" in content
        assert "pnpm" in content

    def test_load_nonexistent_template(self):
        with pytest.raises((FileNotFoundError, TypeError, ModuleNotFoundError)):
            load_template("rulesets", "nonexistent")

    def test_all_rulesets_have_bypass_actors(self):
        for name in ["service_dev", "service_production", "library"]:
            template = load_template("rulesets", name)
            bypass = template.get("bypass_actors", [])
            actor_types = [b["actor_type"] for b in bypass]
            assert "RepositoryRole" in actor_types, f"{name} missing Maintain bypass"
            assert "DeployKey" in actor_types, f"{name} missing DeployKey bypass"

    def test_all_rulesets_have_deletion_protection(self):
        for name in ["service_dev", "service_production", "library"]:
            template = load_template("rulesets", name)
            rule_types = [r["type"] for r in template["rules"]]
            assert "deletion" in rule_types
            assert "non_fast_forward" in rule_types

    def test_all_rulesets_have_four_universal_gates(self):
        expected = {"Code quality", "Security scanning", "Unit tests", "License compliance"}
        for name in ["service_dev", "service_production", "library"]:
            template = load_template("rulesets", name)
            for rule in template["rules"]:
                if rule["type"] == "required_status_checks":
                    check_names = {
                        c["context"] for c in rule["parameters"]["required_status_checks"]
                    }
                    assert check_names == expected, f"{name} has wrong checks: {check_names}"


class TestNormalizeType:
    def test_iac_maps_to_service(self):
        assert normalize_type("iac") == "service"

    def test_service_unchanged(self):
        assert normalize_type("service") == "service"

    def test_library_unchanged(self):
        assert normalize_type("library") == "library"
