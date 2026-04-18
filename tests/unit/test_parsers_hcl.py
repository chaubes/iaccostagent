"""Unit tests for the HCL/Terraform file parser."""

from pathlib import Path

import pytest

from iaccostagent.models.schemas import CloudProvider
from iaccostagent.parsers.hcl import HCLParser


class TestHCLParserBasics:
    def setup_method(self) -> None:
        self.parser = HCLParser()

    def test_can_parse_tf_file(self, terraform_fixtures_dir: Path) -> None:
        main_tf = terraform_fixtures_dir / "simple_web_app" / "main.tf"
        assert self.parser.can_parse(str(main_tf)) is True

    def test_can_parse_directory_with_tf(self, terraform_fixtures_dir: Path) -> None:
        assert self.parser.can_parse(str(terraform_fixtures_dir / "simple_web_app")) is True

    def test_cannot_parse_json(self, plan_json_path: Path) -> None:
        assert self.parser.can_parse(str(plan_json_path)) is False

    def test_parse_missing_path_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            self.parser.parse("/nonexistent/path")


class TestHCLParserSimpleWebApp:
    def setup_method(self) -> None:
        self.parser = HCLParser()

    def test_parses_all_four_resources(self, terraform_fixtures_dir: Path) -> None:
        resources = self.parser.parse(str(terraform_fixtures_dir / "simple_web_app"))
        addresses = {r.address for r in resources}
        assert addresses == {
            "aws_instance.web",
            "aws_db_instance.database",
            "aws_s3_bucket.assets",
            "aws_lb.app",
        }

    def test_infers_aws_provider(self, terraform_fixtures_dir: Path) -> None:
        resources = self.parser.parse(str(terraform_fixtures_dir / "simple_web_app"))
        assert all(r.provider == CloudProvider.AWS for r in resources)

    def test_flattens_single_element_attribute_lists(self, terraform_fixtures_dir: Path) -> None:
        resources = self.parser.parse(str(terraform_fixtures_dir / "simple_web_app"))
        web = next(r for r in resources if r.address == "aws_instance.web")
        assert web.attributes["instance_type"] == "t3.large"


class TestHCLParserOverprovisioned:
    def setup_method(self) -> None:
        self.parser = HCLParser()

    def test_detects_three_nat_gateways(self, terraform_fixtures_dir: Path) -> None:
        resources = self.parser.parse(str(terraform_fixtures_dir / "overprovisioned"))
        nats = [r for r in resources if r.resource_type == "aws_nat_gateway"]
        assert len(nats) == 3

    def test_detects_gp2_volume(self, terraform_fixtures_dir: Path) -> None:
        resources = self.parser.parse(str(terraform_fixtures_dir / "overprovisioned"))
        volumes = [r for r in resources if r.resource_type == "aws_ebs_volume"]
        # The fixture uses `count = 10` on aws_ebs_volume.data — the parser expands it.
        assert len(volumes) == 10
        assert {v.address for v in volumes} == {f"aws_ebs_volume.data[{i}]" for i in range(10)}
        assert all(v.attributes.get("type") == "gp2" for v in volumes)


class TestHCLParserMultiEnvironment:
    def setup_method(self) -> None:
        self.parser = HCLParser()

    def test_combines_all_tf_files_in_dir(self, terraform_fixtures_dir: Path) -> None:
        resources = self.parser.parse(str(terraform_fixtures_dir / "multi_environment"))
        addresses = {r.address for r in resources}
        assert {
            "aws_instance.dev_api",
            "aws_instance.staging_api",
            "aws_instance.prod_api",
        }.issubset(addresses)


class TestCountForEachExpansion:
    """count / for_each should expand into one TerraformResource per instance."""

    def setup_method(self) -> None:
        self.parser = HCLParser()

    def test_count_expands_to_n_instances(self, tmp_path) -> None:
        (tmp_path / "main.tf").write_text(
            """
resource "aws_instance" "web" {
  count         = 3
  instance_type = "t3.micro"
  ami           = "ami-123"
}
"""
        )
        resources = self.parser.parse(str(tmp_path))
        assert len(resources) == 3
        assert [r.address for r in resources] == [
            "aws_instance.web[0]",
            "aws_instance.web[1]",
            "aws_instance.web[2]",
        ]
        # All instances share the same attributes, minus the `count` meta-arg.
        assert all(r.attributes.get("instance_type") == "t3.micro" for r in resources)
        assert all("count" not in r.attributes for r in resources)

    def test_count_zero_emits_no_instances(self, tmp_path) -> None:
        (tmp_path / "main.tf").write_text(
            """
resource "aws_instance" "disabled" {
  count         = 0
  instance_type = "t3.micro"
}
"""
        )
        assert self.parser.parse(str(tmp_path)) == []

    def test_overprovisioned_fixture_reports_15_billable_resources(self, terraform_fixtures_dir) -> None:
        """Matches Infracost: 5 instances + 3 NAT gateways + 1 DB + 10 volumes + 0 RG = 19."""
        resources = self.parser.parse(str(terraform_fixtures_dir / "overprovisioned"))
        # 5 aws_instance + 1 aws_db_instance + 3 aws_nat_gateway + 10 aws_ebs_volume
        assert len(resources) == 19
        instance_addrs = [r.address for r in resources if r.resource_type == "aws_instance"]
        assert sorted(instance_addrs) == [f"aws_instance.app[{i}]" for i in range(5)]

    def test_variable_count_falls_back_to_single_instance(self, tmp_path) -> None:
        """`count = var.replicas` can't be evaluated — emit one instance with a warning."""
        (tmp_path / "main.tf").write_text(
            """
variable "replicas" { default = 3 }
resource "aws_instance" "web" {
  count         = var.replicas
  instance_type = "t3.micro"
}
"""
        )
        resources = self.parser.parse(str(tmp_path))
        # We can't evaluate the variable at parse time, so we emit one resource.
        # Users needing accurate count should pass a plan JSON instead.
        instances = [r for r in resources if r.resource_type == "aws_instance"]
        assert len(instances) == 1
        assert instances[0].address == "aws_instance.web"
