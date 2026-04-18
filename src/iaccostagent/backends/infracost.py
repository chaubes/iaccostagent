"""
Infracost CLI wrapper.

Shells out to `infracost breakdown --path <dir> --format json` and
normalizes the resulting JSON into a CostEstimate. See PRD §4.1 for the
expected Infracost JSON structure.
"""

import asyncio
import json
import os
from datetime import UTC, datetime

from iaccostagent.backends.base import CostBackend
from iaccostagent.backends.registry import register_backend
from iaccostagent.models.schemas import (
    CloudProvider,
    CostComponent,
    CostEstimate,
    ResourceCost,
    TerraformResource,
)
from iaccostagent.parsers.base import infer_provider
from iaccostagent.utils.subprocess_runner import (
    BinaryNotFoundError,
    check_binary,
    run,
)

BINARY = "infracost"


@register_backend("infracost")
class InfracostBackend(CostBackend):
    """Cost backend backed by the Infracost CLI."""

    name = "infracost"

    def is_available(self) -> bool:
        try:
            check_binary(BINARY)
        except BinaryNotFoundError:
            return False
        return True

    async def estimate(self, terraform_path: str, region: str | None = None) -> CostEstimate:
        if not self.is_available():
            raise BinaryNotFoundError(
                "Infracost CLI not found. Install from https://infracost.io or use --backend openinfraquote."
            )

        if not os.environ.get("INFRACOST_API_KEY"):
            raise RuntimeError(
                "Set INFRACOST_API_KEY environment variable (free registration at https://infracost.io)."
            )

        args = [BINARY, "breakdown", "--path", terraform_path, "--format", "json"]
        # infracost is CPU/IO-bound; run in a thread so we don't block the event loop.
        result = await asyncio.to_thread(run, args, timeout=300)
        return self._parse(result.stdout, region=region)

    def _parse(self, stdout: str, region: str | None) -> CostEstimate:
        data = json.loads(stdout)
        currency = data.get("currency", "USD")

        project = (data.get("projects") or [{}])[0]
        breakdown = project.get("breakdown", {})
        total = float(breakdown.get("totalMonthlyCost") or 0.0)

        resource_costs: list[ResourceCost] = []
        top_provider: CloudProvider | None = None
        for r in breakdown.get("resources", []) or []:
            resource_type = r.get("resourceType", "")
            name = r.get("name", "")
            address_parts = name.split(".")
            resource_name = address_parts[-1] if address_parts else ""
            provider = infer_provider(resource_type)
            if top_provider is None and provider is not None:
                top_provider = provider

            monthly = float(r.get("monthlyCost") or 0.0)
            hourly = float(r.get("hourlyCost") or 0.0) or None

            components = [self._parse_component(c) for c in (r.get("costComponents") or [])]

            resource = TerraformResource(
                resource_type=resource_type,
                resource_name=resource_name,
                address=name or f"{resource_type}.{resource_name}",
                provider=provider or CloudProvider.AWS,
                attributes={},
            )
            pct = (monthly / total * 100.0) if total > 0 else 0.0
            resource_costs.append(
                ResourceCost(
                    resource=resource,
                    monthly_cost=monthly,
                    hourly_cost=hourly,
                    cost_components=components,
                    percentage_of_total=pct,
                )
            )

        return CostEstimate(
            backend=self.name,
            currency=currency,
            total_monthly_cost=total,
            total_hourly_cost=(total / 730.0) if total else None,
            resource_costs=resource_costs,
            provider=top_provider,
            region=region,
            estimated_at=datetime.now(UTC),
        )

    @staticmethod
    def _parse_component(c: dict) -> CostComponent:
        return CostComponent(
            name=c.get("name", ""),
            unit=c.get("unit", ""),
            monthly_quantity=_to_float(c.get("monthlyQuantity")),
            monthly_unit_cost=_to_float(c.get("monthlyUnitCost")),
            monthly_cost=_to_float(c.get("monthlyCost")) or 0.0,
            is_usage_based=c.get("usageBased", False),
        )


def _to_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
