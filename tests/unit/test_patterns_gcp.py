"""Unit tests for GCP-specific cost pattern rules."""

from pathlib import Path

from iaccostagent.models.schemas import CloudProvider, CostPatternType, TerraformResource
from iaccostagent.parsers.hcl import HCLParser
from iaccostagent.patterns.rules import detect_patterns


def _mk(resource_type: str, name: str, **attrs: object) -> TerraformResource:
    return TerraformResource(
        resource_type=resource_type,
        resource_name=name,
        address=f"{resource_type}.{name}",
        provider=CloudProvider.GCP,
        attributes=dict(attrs),
    )


class TestOversizedGCPInstance:
    def test_flags_n2_standard_96(self) -> None:
        r = _mk("google_compute_instance", "whale", machine_type="n2-standard-96")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.OVERSIZED_INSTANCE for p in patterns)

    def test_flags_m1_ultramem(self) -> None:
        r = _mk("google_compute_instance", "mem", machine_type="m1-ultramem-160")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.OVERSIZED_INSTANCE for p in patterns)

    def test_does_not_flag_e2_small(self) -> None:
        r = _mk("google_compute_instance", "small", machine_type="e2-small")
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.OVERSIZED_INSTANCE for p in patterns)


class TestOlderGenGCPInstance:
    def test_flags_n1_standard(self) -> None:
        r = _mk("google_compute_instance", "legacy", machine_type="n1-standard-4")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.OLDER_GENERATION_INSTANCE for p in patterns)

    def test_flags_g1_small(self) -> None:
        r = _mk("google_compute_instance", "tiny", machine_type="g1-small")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.OLDER_GENERATION_INSTANCE for p in patterns)

    def test_does_not_flag_e2(self) -> None:
        r = _mk("google_compute_instance", "modern", machine_type="e2-standard-4")
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.OLDER_GENERATION_INSTANCE for p in patterns)


class TestGCPDiskTier:
    def test_flags_pd_standard(self) -> None:
        r = _mk("google_compute_disk", "logs", type="pd-standard", size=500)
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.SUBOPTIMAL_DISK_TIER for p in patterns)

    def test_does_not_flag_pd_balanced(self) -> None:
        r = _mk("google_compute_disk", "data", type="pd-balanced", size=500)
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.SUBOPTIMAL_DISK_TIER for p in patterns)

    def test_does_not_flag_pd_ssd(self) -> None:
        r = _mk("google_compute_disk", "fast", type="pd-ssd", size=500)
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.SUBOPTIMAL_DISK_TIER for p in patterns)


class TestGCPStaticIP:
    def test_flags_unassigned_static_address(self) -> None:
        r = _mk("google_compute_address", "idle", address_type="EXTERNAL")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.UNUSED_PUBLIC_IP for p in patterns)

    def test_does_not_flag_gce_endpoint(self) -> None:
        r = _mk("google_compute_address", "gke", purpose="GCE_ENDPOINT")
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.UNUSED_PUBLIC_IP for p in patterns)


class TestGCPNatSprawl:
    def test_flags_three_gcp_nats(self) -> None:
        nats = [_mk("google_compute_router_nat", f"nat_{i}") for i in range(3)]
        patterns = detect_patterns(nats)
        assert any(p.pattern_type == CostPatternType.EXPENSIVE_NAT_GATEWAY for p in patterns)


class TestGCPFixtures:
    def test_gcp_web_app_has_no_findings(self, terraform_fixtures_dir: Path) -> None:
        resources = HCLParser().parse(str(terraform_fixtures_dir / "gcp_web_app"))
        patterns = detect_patterns(resources)
        assert patterns == []

    def test_gcp_cost_traps_triggers_multiple(self, terraform_fixtures_dir: Path) -> None:
        resources = HCLParser().parse(str(terraform_fixtures_dir / "gcp_cost_traps"))
        patterns = detect_patterns(resources)
        types = {p.pattern_type for p in patterns}
        assert CostPatternType.OVERSIZED_INSTANCE in types
        assert CostPatternType.OLDER_GENERATION_INSTANCE in types
        assert CostPatternType.SUBOPTIMAL_DISK_TIER in types
        assert CostPatternType.UNUSED_PUBLIC_IP in types
        assert CostPatternType.EXPENSIVE_NAT_GATEWAY in types
