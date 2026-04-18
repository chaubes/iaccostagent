"""
Backend parity tests — do the reference native backends agree with Infracost?

These tests run Infracost + the matching native backend against every AWS /
Azure fixture and compare per-resource monthly costs for the overlapping
resource addresses. Parity isn't perfect (Infracost sometimes includes
default usage like EBS root volumes that native backends don't model) so
we compare within a tolerance.

Requirements:
- Infracost CLI installed and INFRACOST_API_KEY set
- HTTPS egress to public pricing APIs
  (https://pricing.us-east-1.amazonaws.com, https://prices.azure.com)

Tests skip gracefully when requirements aren't met, so `pytest tests/integration`
stays green in environments without Infracost.
"""

import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from iaccostagent.backends.infracost import InfracostBackend
from iaccostagent.backends.registry import get_backend
from iaccostagent.models.schemas import CostEstimate

FIXTURES = Path(__file__).parent.parent / "fixtures" / "terraform"

# Per-resource tolerance. List prices from the three sources should be
# identical in theory, but Infracost sometimes bundles defaults the native
# backends don't model. 15% catches real divergence while absorbing known
# modeling differences.
PARITY_TOLERANCE_PCT = 15.0

# Ignore resources with costs below this floor — percentage comparisons on
# very small dollar amounts amplify rounding noise.
MIN_COST_FOR_PARITY = 1.0  # USD / month


# ── AWS fixtures the aws-pricing backend covers meaningfully ──
# aws-pricing handles aws_instance + aws_ebs_volume. Fixtures in this list
# must contain at least one of those.
AWS_FIXTURES = [
    ("simple_web_app", "us-east-1"),
    ("overprovisioned", "us-east-1"),
    ("well_optimized", "us-east-1"),
    ("kubernetes_cluster", "us-east-1"),
    ("multi_environment", "us-east-1"),
    ("cost_traps", "us-east-1"),
]

# ── Azure fixtures the azure-retail backend covers meaningfully ──
AZURE_FIXTURES = [
    ("azure_web_app", "eastus"),
    ("azure_overprovisioned", "eastus"),
]


def _require_infracost() -> None:
    """Skip the test when Infracost isn't ready — we need a reference source."""
    if not InfracostBackend().is_available():
        pytest.skip("Infracost CLI not installed; parity test requires the reference backend.")
    if not os.environ.get("INFRACOST_API_KEY"):
        pytest.skip("INFRACOST_API_KEY not set; parity test requires a live Infracost key.")


def _cost_map(estimate: CostEstimate) -> dict[str, float]:
    """Flatten a CostEstimate into {address: monthly_cost}."""
    return {rc.resource.address: rc.monthly_cost for rc in estimate.resource_costs}


def _assert_parity(
    reference: Mapping[str, float],
    native: Mapping[str, float],
    *,
    label: str,
) -> list[str]:
    """Assert per-resource parity for every address priced by both backends."""
    overlap = [addr for addr in native if addr in reference and native[addr] >= MIN_COST_FOR_PARITY]
    if not overlap:
        # Some fixtures have no resources that aws-pricing / azure-retail handles
        # (e.g. a fixture with only S3 + RDS + LB). Skip the comparison — not a failure.
        pytest.skip(f"{label}: no overlapping priced resources to compare.")

    summary: list[str] = []
    failures: list[str] = []
    for addr in sorted(overlap):
        ref = reference[addr]
        nat = native[addr]
        if ref < MIN_COST_FOR_PARITY:
            continue
        higher = max(ref, nat)
        diff_pct = abs(ref - nat) / higher * 100.0 if higher > 0 else 0.0
        summary.append(f"  {addr}: infracost=${ref:,.2f}  native=${nat:,.2f}  diff={diff_pct:.1f}%")
        if diff_pct > PARITY_TOLERANCE_PCT:
            failures.append(
                f"{addr}: infracost=${ref:,.2f} vs native=${nat:,.2f} "
                f"(diff {diff_pct:.1f}% exceeds {PARITY_TOLERANCE_PCT:.0f}% tolerance)"
            )

    if failures:
        pytest.fail(
            f"{label} — parity failures:\n  " + "\n  ".join(failures) + "\n\nAll comparisons:\n" + "\n".join(summary)
        )
    return summary


async def _run_parity(
    fixture_name: str,
    region: str,
    native_backend_name: str,
    cloud_label: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _require_infracost()
    fixture = FIXTURES / fixture_name

    infracost_est = await InfracostBackend().estimate(str(fixture), region=region)
    native_est = await get_backend(native_backend_name).estimate(str(fixture), region=region)

    label = f"{cloud_label} {fixture_name}"
    summary = _assert_parity(_cost_map(infracost_est), _cost_map(native_est), label=label)

    with capsys.disabled():
        ic_total = infracost_est.total_monthly_cost
        nt_total = native_est.total_monthly_cost
        ic_count = len(infracost_est.resource_costs)
        nt_count = len(native_est.resource_costs)
        print(f"\n[{label} — region {region}]")
        print(f"  infracost total:           ${ic_total:>10,.2f} ({ic_count} resources)")
        print(f"  {native_backend_name:<25} ${nt_total:>10,.2f} ({nt_count} resources)")
        print("  Per-resource comparison (overlap only):")
        for line in summary:
            print(line)


class TestAWSParity:
    """Compare `infracost` vs `aws-pricing` on every AWS fixture."""

    @pytest.mark.parametrize(("fixture", "region"), AWS_FIXTURES, ids=[f[0] for f in AWS_FIXTURES])
    async def test_fixture(self, fixture: str, region: str, capsys: pytest.CaptureFixture[str]) -> None:
        await _run_parity(fixture, region, "aws-pricing", "AWS", capsys)


class TestAzureParity:
    """Compare `infracost` vs `azure-retail` on every Azure fixture."""

    @pytest.mark.parametrize(("fixture", "region"), AZURE_FIXTURES, ids=[f[0] for f in AZURE_FIXTURES])
    async def test_fixture(self, fixture: str, region: str, capsys: pytest.CaptureFixture[str]) -> None:
        await _run_parity(fixture, region, "azure-retail", "Azure", capsys)
