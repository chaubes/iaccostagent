"""Unit tests for the Terraform plan JSON parser."""

from pathlib import Path

import pytest

from iaccostagent.models.schemas import CloudProvider
from iaccostagent.parsers.plan_json import PlanJSONParser


class TestPlanJSONParser:
    def setup_method(self) -> None:
        self.parser = PlanJSONParser()

    def test_can_parse_valid_plan(self, plan_json_path: Path) -> None:
        assert self.parser.can_parse(str(plan_json_path)) is True

    def test_parses_root_and_child_module_resources(self, plan_json_path: Path) -> None:
        resources = self.parser.parse(str(plan_json_path))
        addresses = {r.address for r in resources}
        # Root module: aws_instance.web, aws_db_instance.database
        # Child module: module.networking.aws_nat_gateway.main
        # Data source (data.aws_ami.latest) should be excluded.
        assert "aws_instance.web" in addresses
        assert "aws_db_instance.database" in addresses
        assert "module.networking.aws_nat_gateway.main" in addresses
        assert not any("data.aws_ami" in a for a in addresses)

    def test_extracts_attribute_values(self, plan_json_path: Path) -> None:
        resources = self.parser.parse(str(plan_json_path))
        web = next(r for r in resources if r.address == "aws_instance.web")
        assert web.attributes["instance_type"] == "t3.large"

    def test_provider_inferred_correctly(self, plan_json_path: Path) -> None:
        resources = self.parser.parse(str(plan_json_path))
        assert all(r.provider == CloudProvider.AWS for r in resources)

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            self.parser.parse("/nonexistent.json")
