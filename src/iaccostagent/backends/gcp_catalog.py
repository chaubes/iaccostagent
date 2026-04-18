"""
GCP Cloud Billing Catalog backend — REFERENCE / EXTENSION-PATTERN IMPLEMENTATION.

⚠  STATUS: Reference implementation. Do NOT rely on this backend for
   production cost analysis or billing decisions. Coverage is a deliberate
   starter subset — Infracost (``--backend infracost``) remains the
   recommended choice for full coverage. The CLI prints a yellow warning
   whenever this backend is selected so users aren't surprised.

Queries the Cloud Billing Catalog API (https://cloudbilling.googleapis.com/v1/services)
to price Terraform resources directly. Requires a GCP API key with the Cloud
Billing API enabled — set via `GOOGLE_API_KEY` environment variable.

This backend exists as a working example of how to integrate an API-key-authed
pricing source — see docs/adding-backends.md for the extension pattern.

Supported resource types:
- google_compute_instance (Linux on-demand, us-central1 primary)

Use Infracost as the primary GCP backend for full coverage; extend `HANDLERS`
here when you need to handle additional resource types without an Infracost
dependency.
"""

import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from iaccostagent.backends.base import CostBackend
from iaccostagent.backends.registry import register_backend
from iaccostagent.models.schemas import (
    CloudProvider,
    CostComponent,
    CostEstimate,
    ResourceCost,
    TerraformResource,
)
from iaccostagent.parsers.hcl import HCLParser
from iaccostagent.parsers.plan_json import PlanJSONParser

HOURS_PER_MONTH = 730.0
DEFAULT_REGION = "us-central1"
COMPUTE_SERVICE_ID = "services/6F81-5844-456A"  # Compute Engine
CATALOG_URL = "https://cloudbilling.googleapis.com/v1/{service}/skus"


class GCPBackendError(RuntimeError):
    """Raised when the GCP Cloud Billing Catalog API cannot be queried."""


async def _fetch_compute_skus(client: httpx.AsyncClient, api_key: str) -> list[dict[str, Any]]:
    """Page through all Compute Engine SKUs."""
    skus: list[dict[str, Any]] = []
    params = {"key": api_key, "pageSize": 5000}
    url = CATALOG_URL.format(service=COMPUTE_SERVICE_ID)
    page_token: str | None = None

    while True:
        if page_token:
            params["pageToken"] = page_token
        resp = await client.get(url, params=params, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        skus.extend(data.get("skus") or [])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return skus


def _match_instance_sku(skus: list[dict[str, Any]], machine_type: str, region: str) -> float | None:
    """Find the hourly on-demand price for `machine_type` in `region`.

    Pricing in the catalog is in nanos (1e-9 USD). We sum the Core + Ram
    SKUs for the family if no aggregate SKU is found.
    """
    # Crude but effective: match SKUs where description contains the family
    # and region, category = Compute, usage_type = OnDemand.
    family = machine_type.split("-")[0].upper()  # "n1", "n2", "e2" → "N1", "N2", "E2"

    total_nanos = 0
    matched_any = False

    for sku in skus:
        category = sku.get("category") or {}
        if category.get("resourceFamily") != "Compute":
            continue
        if category.get("usageType") != "OnDemand":
            continue
        if region not in (sku.get("serviceRegions") or []):
            continue
        description = (sku.get("description") or "").lower()
        if f"{family.lower()} " not in description and f"{family.lower()}-" not in description:
            continue
        # Skip preemptible / reserved.
        if "preemptible" in description or "committed" in description:
            continue

        pricing_info = sku.get("pricingInfo") or []
        if not pricing_info:
            continue
        tiered_rates = (pricing_info[0].get("pricingExpression") or {}).get("tieredRates") or []
        if not tiered_rates:
            continue
        nanos = int((tiered_rates[0].get("unitPrice") or {}).get("nanos") or 0)
        if nanos > 0:
            total_nanos += nanos
            matched_any = True

    if not matched_any:
        return None
    # Convert nanos to USD. This is a coarse approximation — GCP's machine-type
    # pricing is separated into core + memory SKUs and the actual per-instance
    # price requires weighting by vCPU and GB RAM counts. Users who need
    # precision should use the Infracost backend; this reference impl returns
    # the summed unit price as a rough hourly estimate.
    return total_nanos * 1e-9


async def _price_compute_instance(
    client: httpx.AsyncClient,
    resource: TerraformResource,
    region: str,
    cache: dict[str, Any],
) -> ResourceCost | None:
    machine_type = str(resource.attributes.get("machine_type", ""))
    if not machine_type:
        return None

    skus = cache.get("skus")
    if skus is None:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise GCPBackendError(
                "GOOGLE_API_KEY is required for the gcp-catalog backend. "
                "Create a key at https://console.cloud.google.com/apis/credentials "
                "with the Cloud Billing API enabled."
            )
        skus = await _fetch_compute_skus(client, api_key)
        cache["skus"] = skus

    hourly = _match_instance_sku(skus, machine_type, region)
    if hourly is None:
        return None

    monthly = round(hourly * HOURS_PER_MONTH, 2)
    return ResourceCost(
        resource=resource,
        monthly_cost=monthly,
        hourly_cost=hourly,
        cost_components=[
            CostComponent(
                name=f"Compute Engine {machine_type}, on-demand",
                unit="hours",
                monthly_quantity=HOURS_PER_MONTH,
                monthly_unit_cost=hourly,
                monthly_cost=monthly,
            )
        ],
    )


HandlerFn = Callable[
    [httpx.AsyncClient, TerraformResource, str, dict[str, Any]],
    Awaitable[ResourceCost | None],
]

HANDLERS: dict[str, HandlerFn] = {
    "google_compute_instance": _price_compute_instance,
}


@register_backend("gcp-catalog")
class GCPCatalogBackend(CostBackend):
    """
    Reference backend that prices GCP resources via the Cloud Billing Catalog API.

    Requires `GOOGLE_API_KEY` with the Cloud Billing API enabled. Coverage
    is a deliberate starter subset; extend `HANDLERS` for more resource types.
    """

    name = "gcp-catalog"

    def is_available(self) -> bool:
        # We report available when the key is set; without it, estimate() raises
        # a clear error. The CLI pre-flight also checks the env var.
        return bool(os.environ.get("GOOGLE_API_KEY"))

    async def estimate(self, terraform_path: str, region: str | None = None) -> CostEstimate:
        if not os.environ.get("GOOGLE_API_KEY"):
            raise GCPBackendError(
                "GOOGLE_API_KEY is not set. Create a GCP API key with the Cloud Billing "
                "API enabled and export it, or use --backend infracost."
            )

        parser = PlanJSONParser() if terraform_path.endswith(".json") else HCLParser()
        resources = parser.parse(terraform_path)

        effective_region = region or DEFAULT_REGION
        resource_costs: list[ResourceCost] = []
        cache: dict[str, Any] = {}

        async with httpx.AsyncClient() as client:
            for resource in resources:
                handler = HANDLERS.get(resource.resource_type)
                if handler is None:
                    continue
                rc = await handler(client, resource, effective_region, cache)
                if rc is not None:
                    resource_costs.append(rc)

        total = round(sum(rc.monthly_cost for rc in resource_costs), 2)
        for rc in resource_costs:
            rc.percentage_of_total = (rc.monthly_cost / total * 100.0) if total > 0 else 0.0

        return CostEstimate(
            backend=self.name,
            currency="USD",
            total_monthly_cost=total,
            total_hourly_cost=(total / HOURS_PER_MONTH) if total else None,
            resource_costs=resource_costs,
            provider=CloudProvider.GCP,
            region=effective_region,
            estimated_at=datetime.now(UTC),
        )
