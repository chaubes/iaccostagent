"""
Azure Retail Prices backend — REFERENCE / EXTENSION-PATTERN IMPLEMENTATION.

⚠  STATUS: Reference implementation. Do NOT rely on this backend for
   production cost analysis or billing decisions. Coverage is a deliberate
   starter subset — Infracost (``--backend infracost``) remains the
   recommended choice for full coverage. The CLI prints a yellow warning
   whenever this backend is selected so users aren't surprised.

Queries the public Azure Retail Prices API (https://prices.azure.com/api/retail/prices)
to price Terraform resources directly. No API key required.

This backend exists as a working example of how to integrate a cloud-native
pricing API. It covers a starter set of resource types — see
docs/adding-backends.md for the extension pattern; add handlers to `HANDLERS`
for additional resource types.

Supported resource types:
- azurerm_linux_virtual_machine
- azurerm_windows_virtual_machine
- azurerm_virtual_machine (legacy)
- azurerm_managed_disk

Use Infracost as the primary Azure backend for full coverage; reach for this
when you need an air-gapped-friendly public-API path or want to extend the
rule surface with custom resource pricing.
"""

import asyncio
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

AZURE_RETAIL_URL = "https://prices.azure.com/api/retail/prices"
HOURS_PER_MONTH = 730.0
DEFAULT_REGION = "eastus"

# Map Azure Terraform region names to Retail API 'armRegionName' values.
# The API accepts either the display name or the armRegionName; using
# armRegionName here keeps the query simple.


async def _query_retail(
    client: httpx.AsyncClient,
    filter_expr: str,
    *,
    cache: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Run a $filter query against the Retail Prices API and paginate.

    When `cache` is provided, identical filter strings within the same
    `estimate()` call reuse the previous response — critical when the same
    VM size or disk tier appears many times in a fixture (e.g. ``count = 10``
    of identical disks).
    """
    if cache is not None and filter_expr in cache:
        return cache[filter_expr]

    params: dict[str, str] = {"$filter": filter_expr, "api-version": "2023-01-01-preview"}
    items: list[dict[str, Any]] = []
    url: str | None = AZURE_RETAIL_URL
    while url:
        resp = await client.get(url, params=params if url == AZURE_RETAIL_URL else None, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get("Items") or [])
        url = data.get("NextPageLink")

    if cache is not None:
        cache[filter_expr] = items
    return items


async def _price_linux_vm(
    client: httpx.AsyncClient,
    resource: TerraformResource,
    region: str,
    cache: dict[str, list[dict[str, Any]]] | None = None,
) -> ResourceCost | None:
    size = str(resource.attributes.get("size", ""))
    if not size:
        return None
    # Retail API filter: service="Virtual Machines", armSkuName=<size>, priceType="Consumption",
    # armRegionName=<region>, and exclude low-priority / spot.
    filt = (
        f"serviceName eq 'Virtual Machines' "
        f"and armSkuName eq '{size}' "
        f"and armRegionName eq '{region}' "
        f"and priceType eq 'Consumption'"
    )
    items = await _query_retail(client, filt, cache=cache)
    # Prefer Linux (productName excludes "Windows"), no low-priority/spot variants.
    linux = [
        p
        for p in items
        if "Windows" not in (p.get("productName") or "")
        and "Low Priority" not in (p.get("meterName") or "")
        and "Spot" not in (p.get("meterName") or "")
    ]
    if not linux:
        return None
    hourly = float(linux[0].get("retailPrice") or 0.0)
    monthly = round(hourly * HOURS_PER_MONTH, 2)
    return ResourceCost(
        resource=resource,
        monthly_cost=monthly,
        hourly_cost=hourly,
        cost_components=[
            CostComponent(
                name=f"Linux VM {size}, on-demand",
                unit="hours",
                monthly_quantity=HOURS_PER_MONTH,
                monthly_unit_cost=hourly,
                monthly_cost=monthly,
            )
        ],
    )


async def _price_windows_vm(
    client: httpx.AsyncClient,
    resource: TerraformResource,
    region: str,
    cache: dict[str, list[dict[str, Any]]] | None = None,
) -> ResourceCost | None:
    size = str(resource.attributes.get("size", ""))
    if not size:
        return None
    filt = (
        f"serviceName eq 'Virtual Machines' "
        f"and armSkuName eq '{size}' "
        f"and armRegionName eq '{region}' "
        f"and priceType eq 'Consumption'"
    )
    items = await _query_retail(client, filt, cache=cache)
    windows = [p for p in items if "Windows" in (p.get("productName") or "")]
    if not windows:
        return None
    hourly = float(windows[0].get("retailPrice") or 0.0)
    monthly = round(hourly * HOURS_PER_MONTH, 2)
    return ResourceCost(
        resource=resource,
        monthly_cost=monthly,
        hourly_cost=hourly,
        cost_components=[
            CostComponent(
                name=f"Windows VM {size}, on-demand",
                unit="hours",
                monthly_quantity=HOURS_PER_MONTH,
                monthly_unit_cost=hourly,
                monthly_cost=monthly,
            )
        ],
    )


# Azure prices managed disks by tier SKU, not per GB. A 100 GB StandardSSD
# is billed as the E10 tier (128 GiB provisioned) at a flat monthly rate —
# not 100 × a per-GB rate. These tables map disk size → cheapest tier that
# fits, for the three storage_account_type values users most commonly set.
DISK_TIERS: dict[str, list[tuple[int, str]]] = {
    "Standard_LRS": [  # HDD, S-series
        (32, "S4"),
        (64, "S6"),
        (128, "S10"),
        (256, "S15"),
        (512, "S20"),
        (1024, "S30"),
        (2048, "S40"),
        (4096, "S50"),
        (8192, "S60"),
        (16384, "S70"),
        (32767, "S80"),
    ],
    "StandardSSD_LRS": [  # Standard SSD, E-series
        (4, "E1"),
        (8, "E2"),
        (16, "E3"),
        (32, "E4"),
        (64, "E6"),
        (128, "E10"),
        (256, "E15"),
        (512, "E20"),
        (1024, "E30"),
        (2048, "E40"),
        (4096, "E50"),
        (8192, "E60"),
        (16384, "E70"),
        (32767, "E80"),
    ],
    "Premium_LRS": [  # Premium SSD, P-series
        (4, "P1"),
        (8, "P2"),
        (16, "P3"),
        (32, "P4"),
        (64, "P6"),
        (128, "P10"),
        (256, "P15"),
        (512, "P20"),
        (1024, "P30"),
        (2048, "P40"),
        (4096, "P50"),
        (8192, "P60"),
        (16384, "P70"),
        (32767, "P80"),
    ],
}


def _pick_disk_tier(storage_account_type: str, size_gb: float) -> str | None:
    """Return the SKU prefix (e.g. 'E10') for the smallest tier that fits `size_gb`."""
    tiers = DISK_TIERS.get(storage_account_type)
    if not tiers:
        return None
    for cap, sku in tiers:
        if size_gb <= cap:
            return sku
    return None


async def _price_managed_disk(
    client: httpx.AsyncClient,
    resource: TerraformResource,
    region: str,
    cache: dict[str, list[dict[str, Any]]] | None = None,
) -> ResourceCost | None:
    tier = str(resource.attributes.get("storage_account_type", ""))
    size = resource.attributes.get("disk_size_gb")
    if not tier or not isinstance(size, int | float):
        return None

    sku_prefix = _pick_disk_tier(tier, float(size))
    if sku_prefix is None:
        return None

    # Azure's skuName for managed disks is e.g. "E10 LRS", "P30 LRS", "S6 LRS".
    redundancy = tier.split("_")[-1] if "_" in tier else "LRS"
    sku_name = f"{sku_prefix} {redundancy}"

    filt = (
        f"serviceName eq 'Storage' "
        f"and armRegionName eq '{region}' "
        f"and skuName eq '{sku_name}' "
        f"and priceType eq 'Consumption'"
    )
    items = await _query_retail(client, filt, cache=cache)
    # The per-disk monthly charge has unitOfMeasure "1/Month"; ignore per-op/per-GB rows.
    tier_rows = [p for p in items if (p.get("unitOfMeasure") or "") == "1/Month"]
    if not tier_rows:
        return None
    monthly = round(float(tier_rows[0].get("retailPrice") or 0.0), 2)

    return ResourceCost(
        resource=resource,
        monthly_cost=monthly,
        cost_components=[
            CostComponent(
                name=f"{tier} disk ({sku_prefix}, provisioned for up to {size} GB)",
                unit="disk-month",
                monthly_quantity=1.0,
                monthly_unit_cost=monthly,
                monthly_cost=monthly,
            )
        ],
    )


# Handler registry — extend this to add resource types.
HandlerFn = Callable[
    [httpx.AsyncClient, TerraformResource, str, dict[str, list[dict[str, Any]]] | None],
    Awaitable[ResourceCost | None],
]

HANDLERS: dict[str, HandlerFn] = {
    "azurerm_linux_virtual_machine": _price_linux_vm,
    "azurerm_windows_virtual_machine": _price_windows_vm,
    "azurerm_virtual_machine": _price_linux_vm,  # legacy resource, default Linux
    "azurerm_managed_disk": _price_managed_disk,
}


@register_backend("azure-retail")
class AzureRetailPricesBackend(CostBackend):
    """
    Reference backend that prices Azure resources via the public Retail Prices API.

    No API key required. HTTPS access to https://prices.azure.com is the only
    dependency. Coverage is a deliberate subset — see docs/adding-backends.md
    for how to extend `HANDLERS`.
    """

    name = "azure-retail"

    def is_available(self) -> bool:
        # Always available — the only dependency is HTTPS egress.
        return True

    async def estimate(self, terraform_path: str, region: str | None = None) -> CostEstimate:
        parser = PlanJSONParser() if terraform_path.endswith(".json") else HCLParser()
        resources = parser.parse(terraform_path)

        effective_region = (region or DEFAULT_REGION).lower().replace(" ", "")
        resource_costs: list[ResourceCost] = []
        unsupported: list[str] = []

        # Per-call response cache — identical filter strings share one HTTP call.
        query_cache: dict[str, list[dict[str, Any]]] = {}

        async with httpx.AsyncClient() as client:
            tasks = []
            typed_resources = []
            for resource in resources:
                handler = HANDLERS.get(resource.resource_type)
                if handler is None:
                    unsupported.append(resource.resource_type)
                    continue
                tasks.append(handler(client, resource, effective_region, query_cache))
                typed_resources.append(resource)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for resource, res in zip(typed_resources, results, strict=True):
                if isinstance(res, ResourceCost):
                    resource_costs.append(res)
                elif isinstance(res, Exception):
                    unsupported.append(f"{resource.resource_type} ({res.__class__.__name__})")

        total = round(sum(rc.monthly_cost for rc in resource_costs), 2)
        for rc in resource_costs:
            rc.percentage_of_total = (rc.monthly_cost / total * 100.0) if total > 0 else 0.0

        return CostEstimate(
            backend=self.name,
            currency="USD",
            total_monthly_cost=total,
            total_hourly_cost=(total / HOURS_PER_MONTH) if total else None,
            resource_costs=resource_costs,
            provider=CloudProvider.AZURE,
            region=effective_region,
            estimated_at=datetime.now(UTC),
        )
