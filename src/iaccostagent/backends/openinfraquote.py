"""
OpenInfraQuote (oiq) CLI wrapper.

Pipeline used by oiq:
    oiq match --pricesheet prices.csv plan.json | oiq price --region us-east-1

We replicate that by capturing the stdout of `oiq match` and feeding it as
stdin to `oiq price`. The final stdout is JSON that we normalize into a
CostEstimate. OIQ is AWS-only in its current release.

A path to the pricesheet CSV must be available — either supplied explicitly
or via the OIQ_PRICESHEET environment variable.
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

BINARY = "oiq"


@register_backend("openinfraquote")
class OpenInfraQuoteBackend(CostBackend):
    """Cost backend backed by the OpenInfraQuote CLI (fully local, AWS-only)."""

    name = "openinfraquote"

    def __init__(self, pricesheet: str | None = None) -> None:
        self.pricesheet = pricesheet or os.environ.get("OIQ_PRICESHEET")

    def is_available(self) -> bool:
        try:
            check_binary(BINARY)
        except BinaryNotFoundError:
            return False
        return True

    async def estimate(self, terraform_path: str, region: str | None = None) -> CostEstimate:
        if not self.is_available():
            raise BinaryNotFoundError(
                "OpenInfraQuote CLI not found. Install from "
                "https://github.com/terrateamio/openinfraquote or use --backend infracost."
            )
        if not self.pricesheet:
            raise RuntimeError("OIQ pricesheet not configured. Pass --pricesheet or set OIQ_PRICESHEET.")
        if not terraform_path.endswith(".json"):
            raise ValueError(
                "OpenInfraQuote requires a plan JSON file. Run `terraform show -json tfplan.binary > plan.json` first."
            )

        effective_region = region or os.environ.get("IACCOSTAGENT_DEFAULT_REGION", "us-east-1")

        match_args = [BINARY, "match", "--pricesheet", self.pricesheet, terraform_path]
        match = await asyncio.to_thread(run, match_args, timeout=180)

        price_args = [BINARY, "price", "--region", effective_region, "--format", "json"]
        price = await asyncio.to_thread(run, price_args, timeout=180, input_text=match.stdout)

        return self._parse(price.stdout, region=effective_region)

    def _parse(self, stdout: str, region: str | None) -> CostEstimate:
        data = json.loads(stdout)

        resources_data = data.get("resources") or data.get("items") or []
        total = float(data.get("total_monthly_cost") or data.get("monthly_cost") or 0.0)

        resource_costs: list[ResourceCost] = []
        for r in resources_data:
            address = r.get("address") or f"{r.get('type', '')}.{r.get('name', '')}"
            resource_type = r.get("type") or r.get("resource_type", "")
            resource_name = r.get("name", address.split(".")[-1] if "." in address else "")
            monthly = float(r.get("monthly_cost") or r.get("cost") or 0.0)

            if not total:
                total += monthly

            provider = infer_provider(resource_type) or CloudProvider.AWS

            components = []
            for c in r.get("components", []) or []:
                components.append(
                    CostComponent(
                        name=c.get("name", ""),
                        unit=c.get("unit", ""),
                        monthly_quantity=_to_float(c.get("monthly_quantity")),
                        monthly_unit_cost=_to_float(c.get("unit_cost")),
                        monthly_cost=_to_float(c.get("monthly_cost")) or 0.0,
                    )
                )

            resource_costs.append(
                ResourceCost(
                    resource=TerraformResource(
                        resource_type=resource_type,
                        resource_name=resource_name,
                        address=address,
                        provider=provider,
                        attributes={},
                    ),
                    monthly_cost=monthly,
                    cost_components=components,
                )
            )

        # Pass 2: now that `total` is known, fill in percentages.
        for rc in resource_costs:
            rc.percentage_of_total = (rc.monthly_cost / total * 100.0) if total > 0 else 0.0

        return CostEstimate(
            backend=self.name,
            currency="USD",
            total_monthly_cost=total,
            total_hourly_cost=(total / 730.0) if total else None,
            resource_costs=resource_costs,
            provider=CloudProvider.AWS,
            region=region,
            estimated_at=datetime.now(UTC),
        )


def _to_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
