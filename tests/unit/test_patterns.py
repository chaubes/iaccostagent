"""Unit tests for the cost pattern rule engine."""

from iaccostagent.models.schemas import CloudProvider, CostPatternType, TerraformResource
from iaccostagent.parsers.hcl import HCLParser
from iaccostagent.patterns.rules import detect_patterns


def _mk(resource_type: str, name: str, **attrs: object) -> TerraformResource:
    return TerraformResource(
        resource_type=resource_type,
        resource_name=name,
        address=f"{resource_type}.{name}",
        provider=CloudProvider.AWS,
        attributes=dict(attrs),
    )


class TestOversizedInstance:
    def test_flags_m5_4xlarge(self) -> None:
        r = _mk("aws_instance", "app", instance_type="m5.4xlarge")
        patterns = detect_patterns([r])
        types = {p.pattern_type for p in patterns}
        assert CostPatternType.OVERSIZED_INSTANCE in types

    def test_does_not_flag_small(self) -> None:
        r = _mk("aws_instance", "web", instance_type="t3.small")
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.OVERSIZED_INSTANCE for p in patterns)


class TestOlderGeneration:
    def test_flags_m4(self) -> None:
        r = _mk("aws_instance", "legacy", instance_type="m4.large")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.OLDER_GENERATION_INSTANCE for p in patterns)

    def test_flags_db_m4(self) -> None:
        r = _mk("aws_db_instance", "legacy_db", instance_class="db.m4.large")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.OLDER_GENERATION_DATABASE for p in patterns)


class TestMissingGp3:
    def test_flags_gp2_and_estimates_savings(self) -> None:
        r = _mk("aws_ebs_volume", "data", type="gp2", size=500)
        patterns = detect_patterns([r])
        gp3 = next(p for p in patterns if p.pattern_type == CostPatternType.MISSING_GP3_STORAGE)
        # $0.02/GB * 500GB = $10
        assert gp3.estimated_savings_monthly == 10.0

    def test_gp3_not_flagged(self) -> None:
        r = _mk("aws_ebs_volume", "data", type="gp3", size=500)
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.MISSING_GP3_STORAGE for p in patterns)


class TestNatGateway:
    def test_flags_three_or_more(self) -> None:
        nats = [_mk("aws_nat_gateway", f"nat_{i}") for i in range(3)]
        patterns = detect_patterns(nats)
        nat = next(p for p in patterns if p.pattern_type == CostPatternType.EXPENSIVE_NAT_GATEWAY)
        # (3 - 1) * 32 = 64
        assert nat.estimated_savings_monthly == 64.0

    def test_does_not_flag_two(self) -> None:
        nats = [_mk("aws_nat_gateway", f"nat_{i}") for i in range(2)]
        patterns = detect_patterns(nats)
        assert not any(p.pattern_type == CostPatternType.EXPENSIVE_NAT_GATEWAY for p in patterns)


class TestUnusedEip:
    def test_flags_eip_without_association(self) -> None:
        r = _mk("aws_eip", "idle", domain="vpc")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.UNUSED_PUBLIC_IP for p in patterns)

    def test_does_not_flag_attached_eip(self) -> None:
        r = _mk("aws_eip", "attached", domain="vpc", instance="i-123")
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.UNUSED_PUBLIC_IP for p in patterns)


class TestAgainstFixtures:
    def test_overprovisioned_fixture_triggers_multiple_patterns(self, terraform_fixtures_dir):
        resources = HCLParser().parse(str(terraform_fixtures_dir / "overprovisioned"))
        patterns = detect_patterns(resources)
        types = {p.pattern_type for p in patterns}
        assert CostPatternType.OVERSIZED_INSTANCE in types
        assert CostPatternType.MISSING_GP3_STORAGE in types
        assert CostPatternType.EXPENSIVE_NAT_GATEWAY in types

    def test_well_optimized_fixture_has_no_findings(self, terraform_fixtures_dir):
        resources = HCLParser().parse(str(terraform_fixtures_dir / "well_optimized"))
        patterns = detect_patterns(resources)
        assert patterns == []

    def test_cost_traps_fixture_flags_legacy_instance_and_eip(self, terraform_fixtures_dir):
        resources = HCLParser().parse(str(terraform_fixtures_dir / "cost_traps"))
        patterns = detect_patterns(resources)
        types = {p.pattern_type for p in patterns}
        assert CostPatternType.OLDER_GENERATION_INSTANCE in types
        assert CostPatternType.UNUSED_PUBLIC_IP in types
        assert CostPatternType.MISSING_GP3_STORAGE in types
        assert CostPatternType.EXPENSIVE_NAT_GATEWAY in types
