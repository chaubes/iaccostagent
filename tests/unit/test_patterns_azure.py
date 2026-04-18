"""Unit tests for Azure-specific cost pattern rules."""

from pathlib import Path

from iaccostagent.models.schemas import CloudProvider, CostPatternType, TerraformResource
from iaccostagent.parsers.hcl import HCLParser
from iaccostagent.patterns.rules import detect_patterns


def _mk(resource_type: str, name: str, **attrs: object) -> TerraformResource:
    return TerraformResource(
        resource_type=resource_type,
        resource_name=name,
        address=f"{resource_type}.{name}",
        provider=CloudProvider.AZURE,
        attributes=dict(attrs),
    )


class TestOversizedAzureVM:
    def test_flags_d32_v5(self) -> None:
        r = _mk("azurerm_linux_virtual_machine", "x", size="Standard_D32s_v5")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.OVERSIZED_INSTANCE for p in patterns)

    def test_flags_m_series(self) -> None:
        r = _mk("azurerm_linux_virtual_machine", "x", size="Standard_M128s")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.OVERSIZED_INSTANCE for p in patterns)

    def test_does_not_flag_small(self) -> None:
        r = _mk("azurerm_linux_virtual_machine", "x", size="Standard_B1s")
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.OVERSIZED_INSTANCE for p in patterns)


class TestOlderGenAzureVM:
    def test_flags_d2_no_suffix(self) -> None:
        r = _mk("azurerm_linux_virtual_machine", "x", size="Standard_D2")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.OLDER_GENERATION_INSTANCE for p in patterns)

    def test_does_not_flag_d2_v5(self) -> None:
        r = _mk("azurerm_linux_virtual_machine", "x", size="Standard_D2s_v5")
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.OLDER_GENERATION_INSTANCE for p in patterns)

    def test_flags_basic_a(self) -> None:
        r = _mk("azurerm_virtual_machine", "x", vm_size="Basic_A2")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.OLDER_GENERATION_INSTANCE for p in patterns)


class TestAzureDiskTier:
    def test_flags_standard_lrs(self) -> None:
        r = _mk("azurerm_managed_disk", "x", storage_account_type="Standard_LRS", disk_size_gb=500)
        patterns = detect_patterns([r])
        p = next(pp for pp in patterns if pp.pattern_type == CostPatternType.SUBOPTIMAL_DISK_TIER)
        assert p.estimated_savings_monthly is not None
        assert p.estimated_savings_monthly > 0

    def test_does_not_flag_premium(self) -> None:
        r = _mk("azurerm_managed_disk", "x", storage_account_type="Premium_LRS", disk_size_gb=500)
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.SUBOPTIMAL_DISK_TIER for p in patterns)


class TestAzureUnusedPublicIP:
    def test_flags_standard_static(self) -> None:
        r = _mk("azurerm_public_ip", "x", sku="Standard", allocation_method="Static")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.UNUSED_PUBLIC_IP for p in patterns)

    def test_does_not_flag_basic_dynamic(self) -> None:
        r = _mk("azurerm_public_ip", "x", sku="Basic", allocation_method="Dynamic")
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.UNUSED_PUBLIC_IP for p in patterns)


class TestAzureOlderDatabase:
    def test_flags_postgresql_single_server(self) -> None:
        r = _mk("azurerm_postgresql_server", "legacy")
        patterns = detect_patterns([r])
        assert any(p.pattern_type == CostPatternType.OLDER_GENERATION_DATABASE for p in patterns)

    def test_does_not_flag_flexible_server(self) -> None:
        r = _mk("azurerm_postgresql_flexible_server", "modern")
        patterns = detect_patterns([r])
        assert not any(p.pattern_type == CostPatternType.OLDER_GENERATION_DATABASE for p in patterns)


class TestAzureNatGatewaySprawl:
    def test_flags_three_azure_nats(self) -> None:
        nats = [_mk("azurerm_nat_gateway", f"nat_{i}") for i in range(3)]
        patterns = detect_patterns(nats)
        assert any(p.pattern_type == CostPatternType.EXPENSIVE_NAT_GATEWAY for p in patterns)

    def test_does_not_flag_two(self) -> None:
        nats = [_mk("azurerm_nat_gateway", f"nat_{i}") for i in range(2)]
        patterns = detect_patterns(nats)
        assert not any(p.pattern_type == CostPatternType.EXPENSIVE_NAT_GATEWAY for p in patterns)


class TestAzureFixtures:
    def test_azure_web_app_has_no_findings(self, terraform_fixtures_dir: Path) -> None:
        resources = HCLParser().parse(str(terraform_fixtures_dir / "azure_web_app"))
        patterns = detect_patterns(resources)
        assert patterns == []

    def test_azure_overprovisioned_triggers_multiple(self, terraform_fixtures_dir: Path) -> None:
        resources = HCLParser().parse(str(terraform_fixtures_dir / "azure_overprovisioned"))
        patterns = detect_patterns(resources)
        types = {p.pattern_type for p in patterns}
        assert CostPatternType.OVERSIZED_INSTANCE in types
        assert CostPatternType.OLDER_GENERATION_INSTANCE in types
        assert CostPatternType.SUBOPTIMAL_DISK_TIER in types
        assert CostPatternType.UNUSED_PUBLIC_IP in types
        assert CostPatternType.OLDER_GENERATION_DATABASE in types
        assert CostPatternType.EXPENSIVE_NAT_GATEWAY in types
