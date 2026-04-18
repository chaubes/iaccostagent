"""
AWS Pricing backend — REFERENCE / EXTENSION-PATTERN IMPLEMENTATION.

⚠  STATUS: Reference implementation. Do NOT rely on this backend for
   production cost analysis or billing decisions. Coverage is a deliberate
   starter subset — Infracost (``--backend infracost``) remains the
   recommended choice for full coverage. The CLI prints a yellow warning
   whenever this backend is selected so users aren't surprised.

Queries AWS's public Price List JSON endpoints (no IAM credentials required)
to price Terraform resources directly. This file exists as a working example
of how to integrate a native pricing source — see docs/adding-backends.md for
the extension pattern.

Supported resource types:
- aws_instance (Linux on-demand, Shared tenancy)
- aws_ebs_volume (gp2, gp3, io1, io2, st1, sc1, standard)
- aws_nat_gateway (hourly charge; usage-based data-processing excluded)
- aws_db_instance (RDS compute + allocated storage; Postgres/MySQL/MariaDB/Oracle/SQL Server/Aurora)

Extend coverage by adding handlers to `HANDLERS`.

Notes on the data source:
- https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/<region>/index.json
  is several hundred MB for EC2; we pull only the JSON once per region and
  cache it on the instance so repeated resources in one run share the lookup.
- Spot, reserved, and savings-plan prices are out of scope here — we report
  on-demand list prices only.
"""

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
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
DEFAULT_REGION = "us-east-1"

# Mapping from AWS region code to the "location" string used inside the
# price list JSON. The full list is extensive; these are the common ones.
REGION_TO_LOCATION = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-central-1": "EU (Frankfurt)",
    "eu-north-1": "EU (Stockholm)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
}

EC2_PRICE_URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/{region}/index.json"
RDS_PRICE_URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/{region}/index.json"

# Map Terraform engine value → the Retail "databaseEngine" attribute string.
RDS_ENGINE_MAP = {
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "oracle-ee": "Oracle",
    "oracle-se2": "Oracle",
    "sqlserver-ee": "SQL Server",
    "sqlserver-se": "SQL Server",
    "sqlserver-ex": "SQL Server",
    "sqlserver-web": "SQL Server",
    "aurora-postgresql": "Aurora PostgreSQL",
    "aurora-mysql": "Aurora MySQL",
}

# EBS volume type → API usageType fragment and $/GB-month default (fallback).
EBS_USAGE_TYPES = {
    "gp2": "EBS:VolumeUsage.gp2",
    "gp3": "EBS:VolumeUsage.gp3",
    "io1": "EBS:VolumeUsage.piops",
    "io2": "EBS:VolumeUsage.io2",
    "st1": "EBS:VolumeUsage.st1",
    "sc1": "EBS:VolumeUsage.sc1",
    "standard": "EBS:VolumeUsage",
}


# AWS's per-region EC2 JSON is ~200-400 MB and rarely changes. Keep the
# full payload on disk for a day so repeat runs don't re-download it.
CACHE_TTL_SECONDS = 24 * 60 * 60


def _cache_dir() -> Path:
    """Resolve the on-disk cache directory for downloaded price lists."""
    base = os.environ.get("IACCOSTAGENT_CACHE_DIR") or str(Path.home() / ".cache" / "iaccostagent")
    cache = Path(base).expanduser() / "aws-pricing"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _cache_path(service: str, region: str) -> Path:
    return _cache_dir() / f"{service}-{region}.json"


def _load_from_cache(service: str, region: str) -> dict[str, Any] | None:
    path = _cache_path(service, region)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_to_cache(service: str, region: str, data: dict[str, Any]) -> None:
    path = _cache_path(service, region)
    try:
        # Write atomically so partial downloads don't leave half-baked JSON.
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w") as f:
            json.dump(data, f)
        tmp.replace(path)
    except OSError:
        pass  # cache failures are non-fatal


async def _fetch_pricing_json(client: httpx.AsyncClient, *, service: str, region: str, url: str) -> dict[str, Any]:
    """
    Return a cached AWS price-list JSON for `service` × `region`.

    Tries the on-disk cache first (TTL: 24h). If absent or stale, downloads
    from AWS — this takes a minute on a fresh cache because the files are
    ~200-400 MB, then subsequent runs are instant.
    """
    cached = _load_from_cache(service, region)
    if cached is not None:
        return cached

    # Bumped timeout — the initial download can take a minute on slow connections.
    resp = await client.get(url, timeout=600.0)
    resp.raise_for_status()
    data = resp.json()
    _save_to_cache(service, region, data)
    return data


async def _fetch_ec2_pricing(client: httpx.AsyncClient, region: str) -> dict[str, Any]:
    return await _fetch_pricing_json(client, service="ec2", region=region, url=EC2_PRICE_URL.format(region=region))


async def _fetch_rds_pricing(client: httpx.AsyncClient, region: str) -> dict[str, Any]:
    return await _fetch_pricing_json(client, service="rds", region=region, url=RDS_PRICE_URL.format(region=region))


def _find_instance_price(pricing: dict[str, Any], instance_type: str, location: str) -> float | None:
    """Find the Linux on-demand hourly price for `instance_type` in `location`."""
    products = pricing.get("products", {})
    on_demand = pricing.get("terms", {}).get("OnDemand", {})

    for sku, product in products.items():
        attrs = product.get("attributes", {})
        if (
            attrs.get("instanceType") == instance_type
            and attrs.get("location") == location
            and attrs.get("operatingSystem") == "Linux"
            and attrs.get("tenancy") == "Shared"
            and attrs.get("preInstalledSw") == "NA"
            and attrs.get("capacitystatus") == "Used"
        ):
            terms = on_demand.get(sku, {})
            for term in terms.values():
                for dim in term.get("priceDimensions", {}).values():
                    price = float(dim.get("pricePerUnit", {}).get("USD") or 0.0)
                    if price > 0:
                        return price
    return None


def _find_nat_gateway_hourly(pricing: dict[str, Any], location: str) -> float | None:
    """Find the hourly NAT Gateway price in `location`.

    NAT Gateways live under productFamily = "NAT Gateway" with usagetype
    "NatGateway-Hours" (or regional variants). Data-processing charges
    ($/GB) are billed separately and depend on actual traffic — we skip
    them here since they'd require runtime usage inputs.
    """
    products = pricing.get("products", {})
    on_demand = pricing.get("terms", {}).get("OnDemand", {})

    for sku, product in products.items():
        if product.get("productFamily") != "NAT Gateway":
            continue
        attrs = product.get("attributes", {})
        if attrs.get("location") != location:
            continue
        usage = attrs.get("usagetype") or ""
        if not usage.endswith("NatGateway-Hours"):
            continue
        terms = on_demand.get(sku, {})
        for term in terms.values():
            for dim in term.get("priceDimensions", {}).values():
                unit = (dim.get("unit") or "").lower()
                if unit not in ("hrs", "hour", "hours"):
                    continue
                price = float(dim.get("pricePerUnit", {}).get("USD") or 0.0)
                if price > 0:
                    return price
    return None


def _find_rds_instance_price(
    pricing: dict[str, Any],
    *,
    instance_class: str,
    location: str,
    engine: str,
    multi_az: bool,
) -> float | None:
    """Find the on-demand hourly price for an RDS instance class.

    RDS products carry productFamily = "Database Instance" with rich
    attribute filters: `instanceType`, `location`, `databaseEngine`,
    `deploymentOption` (Single-AZ / Multi-AZ), and `licenseModel`. We
    pick the BYOL / no-license-required row since Terraform usually
    doesn't specify a license.
    """
    products = pricing.get("products", {})
    on_demand = pricing.get("terms", {}).get("OnDemand", {})
    deployment = "Multi-AZ" if multi_az else "Single-AZ"
    engine_label = RDS_ENGINE_MAP.get(engine.lower(), engine)

    for sku, product in products.items():
        if product.get("productFamily") != "Database Instance":
            continue
        attrs = product.get("attributes", {})
        if attrs.get("location") != location:
            continue
        if attrs.get("instanceType") != instance_class:
            continue
        if attrs.get("deploymentOption") != deployment:
            continue
        # Exact engine match — substring matching trips over variants like
        # "Aurora PostgreSQL" containing "postgresql" or "PostgreSQL
        # (on-premise for Outpost)" containing "postgresql".
        if (attrs.get("databaseEngine") or "") != engine_label:
            continue
        # Skip BYOL vs License-included mismatches; prefer license-included-free.
        if attrs.get("licenseModel") not in (None, "No license required", "Bring your own license"):
            continue
        terms = on_demand.get(sku, {})
        for term in terms.values():
            for dim in term.get("priceDimensions", {}).values():
                price = float(dim.get("pricePerUnit", {}).get("USD") or 0.0)
                if price > 0:
                    return price
    return None


def _find_rds_storage_price(
    pricing: dict[str, Any],
    *,
    location: str,
    storage_type: str,
    multi_az: bool,
) -> float | None:
    """Find the $/GB-month price for RDS allocated storage."""
    products = pricing.get("products", {})
    on_demand = pricing.get("terms", {}).get("OnDemand", {})
    deployment = "Multi-AZ" if multi_az else "Single-AZ"

    # Map Terraform storage_type → Retail "volumeType" attribute.
    vol_map = {
        "gp2": "General Purpose",
        "gp3": "General Purpose-GP3",
        "io1": "Provisioned IOPS",
        "io2": "Provisioned IOPS",
        "standard": "Magnetic",
    }
    wanted_vol = vol_map.get(storage_type, "General Purpose")

    for sku, product in products.items():
        if product.get("productFamily") != "Database Storage":
            continue
        attrs = product.get("attributes", {})
        if attrs.get("location") != location:
            continue
        if attrs.get("deploymentOption") != deployment:
            continue
        if wanted_vol not in (attrs.get("volumeType") or ""):
            continue
        terms = on_demand.get(sku, {})
        for term in terms.values():
            for dim in term.get("priceDimensions", {}).values():
                price = float(dim.get("pricePerUnit", {}).get("USD") or 0.0)
                if price > 0:
                    return price
    return None


def _find_ebs_price(pricing: dict[str, Any], usage_type_fragment: str, location: str) -> float | None:
    """Find the per-GB-month price for a given EBS usage type in `location`.

    Note: in the AWS price-list JSON, `productFamily` is a top-level key of
    each product (NOT inside `attributes`). EBS volumes are `productFamily`
    == "Storage"; the specific volume type lives in `attributes.volumeApiName`
    (e.g. "gp2", "gp3") and `attributes.usagetype` (e.g. "EBS:VolumeUsage.gp2").
    """
    products = pricing.get("products", {})
    on_demand = pricing.get("terms", {}).get("OnDemand", {})

    for sku, product in products.items():
        if product.get("productFamily") != "Storage":
            continue
        attrs = product.get("attributes", {})
        if attrs.get("location") != location:
            continue
        if usage_type_fragment not in (attrs.get("usagetype") or ""):
            continue
        terms = on_demand.get(sku, {})
        for term in terms.values():
            for dim in term.get("priceDimensions", {}).values():
                price = float(dim.get("pricePerUnit", {}).get("USD") or 0.0)
                if price > 0:
                    return price
    return None


async def _get_ec2_pricing(client: httpx.AsyncClient, region: str, cache: dict[str, Any]) -> dict[str, Any]:
    key = f"ec2:{region}"
    pricing = cache.get(key)
    if pricing is None:
        pricing = await _fetch_ec2_pricing(client, region)
        cache[key] = pricing
    return pricing


async def _get_rds_pricing(client: httpx.AsyncClient, region: str, cache: dict[str, Any]) -> dict[str, Any]:
    key = f"rds:{region}"
    pricing = cache.get(key)
    if pricing is None:
        pricing = await _fetch_rds_pricing(client, region)
        cache[key] = pricing
    return pricing


async def _price_aws_instance(
    client: httpx.AsyncClient,
    resource: TerraformResource,
    region: str,
    cache: dict[str, Any],
) -> ResourceCost | None:
    instance_type = str(resource.attributes.get("instance_type", ""))
    if not instance_type:
        return None
    location = REGION_TO_LOCATION.get(region, "US East (N. Virginia)")
    pricing = await _get_ec2_pricing(client, region, cache)

    hourly = _find_instance_price(pricing, instance_type, location)
    if hourly is None:
        return None

    monthly = round(hourly * HOURS_PER_MONTH, 2)
    return ResourceCost(
        resource=resource,
        monthly_cost=monthly,
        hourly_cost=hourly,
        cost_components=[
            CostComponent(
                name=f"Linux/UNIX usage (on-demand, {instance_type})",
                unit="hours",
                monthly_quantity=HOURS_PER_MONTH,
                monthly_unit_cost=hourly,
                monthly_cost=monthly,
            )
        ],
    )


async def _price_ebs_volume(
    client: httpx.AsyncClient,
    resource: TerraformResource,
    region: str,
    cache: dict[str, Any],
) -> ResourceCost | None:
    volume_type = str(resource.attributes.get("type", "gp2"))
    size = resource.attributes.get("size")
    if not isinstance(size, int | float):
        return None

    usage_fragment = EBS_USAGE_TYPES.get(volume_type)
    if usage_fragment is None:
        return None

    location = REGION_TO_LOCATION.get(region, "US East (N. Virginia)")
    pricing = await _get_ec2_pricing(client, region, cache)

    per_gb_month = _find_ebs_price(pricing, usage_fragment, location)
    if per_gb_month is None:
        return None

    monthly = round(per_gb_month * float(size), 2)
    return ResourceCost(
        resource=resource,
        monthly_cost=monthly,
        cost_components=[
            CostComponent(
                name=f"EBS {volume_type}, {size} GB",
                unit="GB",
                monthly_quantity=float(size),
                monthly_unit_cost=per_gb_month,
                monthly_cost=monthly,
            )
        ],
    )


async def _price_nat_gateway(
    client: httpx.AsyncClient,
    resource: TerraformResource,
    region: str,
    cache: dict[str, Any],
) -> ResourceCost | None:
    """Price a NAT Gateway's hourly charge. Data-processing cost is usage-based
    and excluded here (the cost backend can't know runtime GB without actuals).
    """
    location = REGION_TO_LOCATION.get(region, "US East (N. Virginia)")
    pricing = await _get_ec2_pricing(client, region, cache)

    hourly = _find_nat_gateway_hourly(pricing, location)
    if hourly is None:
        return None

    monthly = round(hourly * HOURS_PER_MONTH, 2)
    return ResourceCost(
        resource=resource,
        monthly_cost=monthly,
        hourly_cost=hourly,
        cost_components=[
            CostComponent(
                name="NAT Gateway hours (data processing excluded)",
                unit="hours",
                monthly_quantity=HOURS_PER_MONTH,
                monthly_unit_cost=hourly,
                monthly_cost=monthly,
            )
        ],
    )


async def _price_rds_instance(
    client: httpx.AsyncClient,
    resource: TerraformResource,
    region: str,
    cache: dict[str, Any],
) -> ResourceCost | None:
    """
    Price an RDS instance's on-demand compute + allocated storage.

    We don't model backup storage, I/O, or Performance Insights — these
    depend on runtime usage that isn't declared in Terraform.
    """
    instance_class = str(resource.attributes.get("instance_class", ""))
    engine = str(resource.attributes.get("engine", ""))
    if not instance_class or not engine:
        return None

    location = REGION_TO_LOCATION.get(region, "US East (N. Virginia)")
    multi_az = bool(resource.attributes.get("multi_az"))
    allocated = resource.attributes.get("allocated_storage")
    storage_type = str(resource.attributes.get("storage_type", "gp2"))

    pricing = await _get_rds_pricing(client, region, cache)

    components: list[CostComponent] = []
    hourly = _find_rds_instance_price(
        pricing,
        instance_class=instance_class,
        location=location,
        engine=engine,
        multi_az=multi_az,
    )
    compute_monthly = 0.0
    if hourly is not None:
        compute_monthly = round(hourly * HOURS_PER_MONTH, 2)
        components.append(
            CostComponent(
                name=f"RDS {engine} {instance_class}" + (" (Multi-AZ)" if multi_az else " (Single-AZ)"),
                unit="hours",
                monthly_quantity=HOURS_PER_MONTH,
                monthly_unit_cost=hourly,
                monthly_cost=compute_monthly,
            )
        )

    storage_monthly = 0.0
    if isinstance(allocated, int | float):
        per_gb = _find_rds_storage_price(
            pricing,
            location=location,
            storage_type=storage_type,
            multi_az=multi_az,
        )
        if per_gb is not None:
            storage_monthly = round(per_gb * float(allocated), 2)
            components.append(
                CostComponent(
                    name=f"RDS storage ({storage_type}, {allocated} GB)",
                    unit="GB",
                    monthly_quantity=float(allocated),
                    monthly_unit_cost=per_gb,
                    monthly_cost=storage_monthly,
                )
            )

    total = round(compute_monthly + storage_monthly, 2)
    if total == 0.0:
        return None  # Couldn't price anything; let the skip-silently path handle it.

    return ResourceCost(
        resource=resource,
        monthly_cost=total,
        hourly_cost=hourly,
        cost_components=components,
    )


HandlerFn = Callable[
    [httpx.AsyncClient, TerraformResource, str, dict[str, Any]],
    Awaitable[ResourceCost | None],
]

HANDLERS: dict[str, HandlerFn] = {
    "aws_instance": _price_aws_instance,
    "aws_ebs_volume": _price_ebs_volume,
    "aws_nat_gateway": _price_nat_gateway,
    "aws_db_instance": _price_rds_instance,
}


@register_backend("aws-pricing")
class AWSPricingBackend(CostBackend):
    """
    Reference backend that prices AWS resources via the public Price List API.

    No IAM credentials required — the price list is public JSON. Coverage
    is a deliberate starter subset (EC2 + EBS). Extend `HANDLERS` for
    additional resource types, or use Infracost for broader coverage.
    """

    name = "aws-pricing"

    def is_available(self) -> bool:
        # Always available — the only dependency is HTTPS egress.
        return True

    async def estimate(self, terraform_path: str, region: str | None = None) -> CostEstimate:
        parser = PlanJSONParser() if terraform_path.endswith(".json") else HCLParser()
        resources = parser.parse(terraform_path)

        effective_region = region or DEFAULT_REGION
        resource_costs: list[ResourceCost] = []
        cache: dict[str, Any] = {}

        async with httpx.AsyncClient() as client:
            tasks = []
            for resource in resources:
                handler = HANDLERS.get(resource.resource_type)
                if handler is None:
                    continue
                tasks.append(handler(client, resource, effective_region, cache))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, ResourceCost):
                    resource_costs.append(res)

        total = round(sum(rc.monthly_cost for rc in resource_costs), 2)
        for rc in resource_costs:
            rc.percentage_of_total = (rc.monthly_cost / total * 100.0) if total > 0 else 0.0

        return CostEstimate(
            backend=self.name,
            currency="USD",
            total_monthly_cost=total,
            total_hourly_cost=(total / HOURS_PER_MONTH) if total else None,
            resource_costs=resource_costs,
            provider=CloudProvider.AWS,
            region=effective_region,
            estimated_at=datetime.now(UTC),
        )
