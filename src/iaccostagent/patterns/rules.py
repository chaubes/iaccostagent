"""
Deterministic cost-pattern rule engine.

Rules run before the LLM and produce concrete, rule-based findings with
rough dollar savings estimates. Per the two-layer philosophy, the rule
engine output is ground truth; the LLM explains and ranks.

Rules are grouped by cloud provider (AWS, Azure, GCP). Add new rules by
appending to `SINGLE_RESOURCE_RULES` or `COLLECTION_RULES` in the relevant
section. All savings estimates are rough monthly USD heuristics based on
on-demand list prices and exist as starting points for LLM reasoning,
not as replacements for the cost backend.
"""

from collections.abc import Callable
from dataclasses import dataclass

from iaccostagent.models.schemas import (
    CostPattern,
    CostPatternType,
    TerraformResource,
)

# ══ AWS constants ═════════════════════════════════════════════════════

OLDER_GEN_EC2_PREFIXES = ("m4.", "m3.", "c4.", "c3.", "r4.", "r3.", "t2.")
OLDER_GEN_RDS_PREFIXES = ("db.m4.", "db.m3.", "db.r4.", "db.r3.", "db.t2.")

OVERSIZED_EC2_PREFIXES = (
    "m5.4xlarge",
    "m5.8xlarge",
    "m5.12xlarge",
    "m5.16xlarge",
    "m5.24xlarge",
    "m6i.4xlarge",
    "m6i.8xlarge",
    "m6i.12xlarge",
    "m6i.16xlarge",
    "m6i.24xlarge",
    "r5.4xlarge",
    "r5.8xlarge",
    "r5.12xlarge",
    "r6i.4xlarge",
    "r6i.8xlarge",
    "r6i.12xlarge",
    "c5.4xlarge",
    "c5.9xlarge",
    "c5.12xlarge",
    "c5.18xlarge",
)

NAT_GATEWAY_MONTHLY_USD = 32.0  # base hourly * 730 hours

# ══ Azure constants ═══════════════════════════════════════════════════

# Older Azure VM generations users should migrate off.
OLDER_GEN_AZURE_VM_PREFIXES = (
    "Standard_A",  # v1 A-series (no _v2)
    "Standard_D1",  # v1 D-series
    "Standard_D2",
    "Standard_D3",
    "Standard_D4",
    "Standard_D11",
    "Standard_D12",
    "Standard_D13",
    "Standard_D14",
    "Basic_A",
)

# Azure VM sizes commonly over-provisioned.
OVERSIZED_AZURE_VM_PREFIXES = (
    "Standard_D16",
    "Standard_D32",
    "Standard_D48",
    "Standard_D64",
    "Standard_E16",
    "Standard_E32",
    "Standard_E48",
    "Standard_E64",
    "Standard_F16",
    "Standard_F32",
    "Standard_F72",
    "Standard_M",  # M-series are memory monsters and usually over-provisioned
)

# ══ GCP constants ═════════════════════════════════════════════════════

# GCP machine-type families considered "older generation" today.
OLDER_GEN_GCP_PREFIXES = ("n1-", "g1-", "f1-")

# Oversized GCP machine types (simple prefix match on common overkill SKUs).
OVERSIZED_GCP_PREFIXES = (
    "n1-highmem-96",
    "n1-highmem-64",
    "n2-highmem-96",
    "n2-highmem-64",
    "n2-standard-96",
    "n2-standard-80",
    "c2-standard-60",
    "c2-standard-30",
    "m1-megamem-96",
    "m1-ultramem",
)


# ══ Rule dataclasses ══════════════════════════════════════════════════


@dataclass
class SingleResourceRule:
    """Rule that examines one resource at a time."""

    pattern_type: CostPatternType
    applies: Callable[[TerraformResource], bool]
    describe: Callable[[TerraformResource], str]
    estimate_savings: Callable[[TerraformResource], float | None]
    confidence: float = 0.8


@dataclass
class CollectionRule:
    """Rule that needs the whole resource list (e.g., to count NAT gateways)."""

    pattern_type: CostPatternType
    applies: Callable[[list[TerraformResource]], bool]
    build: Callable[[list[TerraformResource]], list[CostPattern]]


# ══ AWS single-resource rules ═════════════════════════════════════════


def _is_oversized_ec2(r: TerraformResource) -> bool:
    if r.resource_type != "aws_instance":
        return False
    itype = str(r.attributes.get("instance_type", ""))
    return any(itype.startswith(p) for p in OVERSIZED_EC2_PREFIXES)


def _is_older_gen_ec2(r: TerraformResource) -> bool:
    if r.resource_type != "aws_instance":
        return False
    itype = str(r.attributes.get("instance_type", ""))
    return any(itype.startswith(p) for p in OLDER_GEN_EC2_PREFIXES)


def _is_older_gen_rds(r: TerraformResource) -> bool:
    if r.resource_type != "aws_db_instance":
        return False
    cls = str(r.attributes.get("instance_class", ""))
    return any(cls.startswith(p) for p in OLDER_GEN_RDS_PREFIXES)


def _is_gp2_volume(r: TerraformResource) -> bool:
    return r.resource_type == "aws_ebs_volume" and str(r.attributes.get("type", "")) == "gp2"


def _is_unused_eip(r: TerraformResource) -> bool:
    if r.resource_type != "aws_eip":
        return False
    attached = any(r.attributes.get(k) for k in ("instance", "network_interface", "associated_instance"))
    return not attached


def _gp2_to_gp3_savings(r: TerraformResource) -> float | None:
    size = r.attributes.get("size")
    if not isinstance(size, int | float):
        return None
    return round(float(size) * 0.02, 2)


AWS_RULES: list[SingleResourceRule] = [
    SingleResourceRule(
        pattern_type=CostPatternType.OVERSIZED_INSTANCE,
        applies=_is_oversized_ec2,
        describe=lambda r: (
            f"{r.address} uses {r.attributes.get('instance_type')}, commonly over-provisioned for typical workloads."
        ),
        estimate_savings=lambda r: 200.0,
        confidence=0.6,
    ),
    SingleResourceRule(
        pattern_type=CostPatternType.OLDER_GENERATION_INSTANCE,
        applies=_is_older_gen_ec2,
        describe=lambda r: (
            f"{r.address} uses previous-generation EC2 type "
            f"{r.attributes.get('instance_type')}. Current-gen (m6/c6/r6/t3) is ~10-20% cheaper."
        ),
        estimate_savings=lambda r: 15.0,
        confidence=0.85,
    ),
    SingleResourceRule(
        pattern_type=CostPatternType.OLDER_GENERATION_DATABASE,
        applies=_is_older_gen_rds,
        describe=lambda r: (
            f"{r.address} uses previous-generation RDS class "
            f"{r.attributes.get('instance_class')}. Graviton (db.m6g/db.r6g/db.t4g) is up to 20% cheaper."
        ),
        estimate_savings=lambda r: 40.0,
        confidence=0.8,
    ),
    SingleResourceRule(
        pattern_type=CostPatternType.MISSING_GP3_STORAGE,
        applies=_is_gp2_volume,
        describe=lambda r: (
            f"{r.address} uses gp2 EBS. gp3 offers the same baseline IOPS at ~20% lower cost "
            "and is a drop-in replacement."
        ),
        estimate_savings=_gp2_to_gp3_savings,
        confidence=0.95,
    ),
    SingleResourceRule(
        pattern_type=CostPatternType.UNUSED_PUBLIC_IP,
        applies=_is_unused_eip,
        describe=lambda r: (
            f"{r.address} is an Elastic IP with no visible association. "
            "Unassociated EIPs incur an hourly charge (~$3.60/month)."
        ),
        estimate_savings=lambda r: 3.6,
        confidence=0.6,
    ),
]


# ══ Azure single-resource rules ═══════════════════════════════════════

AZURE_VM_TYPES = ("azurerm_linux_virtual_machine", "azurerm_windows_virtual_machine", "azurerm_virtual_machine")


def _is_oversized_azure_vm(r: TerraformResource) -> bool:
    if r.resource_type not in AZURE_VM_TYPES:
        return False
    size = str(r.attributes.get("size") or r.attributes.get("vm_size", ""))
    return any(size.startswith(p) for p in OVERSIZED_AZURE_VM_PREFIXES)


def _is_older_gen_azure_vm(r: TerraformResource) -> bool:
    if r.resource_type not in AZURE_VM_TYPES:
        return False
    size = str(r.attributes.get("size") or r.attributes.get("vm_size", ""))
    if not size:
        return False
    # Skip v2/v3/v4/v5 generations (those are fine).
    if any(size.endswith(suffix) for suffix in ("_v2", "_v3", "_v4", "_v5")):
        return False
    return any(size.startswith(p) for p in OLDER_GEN_AZURE_VM_PREFIXES)


def _is_standard_lrs_disk(r: TerraformResource) -> bool:
    if r.resource_type != "azurerm_managed_disk":
        return False
    return str(r.attributes.get("storage_account_type", "")) == "Standard_LRS"


def _is_unused_azure_public_ip(r: TerraformResource) -> bool:
    if r.resource_type != "azurerm_public_ip":
        return False
    # Azure public IPs have no explicit association field in the resource; Terraform
    # associates them via separate azurerm_network_interface / nat_gateway /
    # virtual_network_gateway resources. As a heuristic we flag Standard SKU IPs
    # that are tagged with allocation_method=Static (they always bill) and let the
    # LLM decide whether the user has them attached.
    sku = str(r.attributes.get("sku", "Basic"))
    alloc = str(r.attributes.get("allocation_method", ""))
    return sku == "Standard" and alloc == "Static"


def _is_older_gen_azure_db(r: TerraformResource) -> bool:
    """Flag old Azure SQL/PostgreSQL/MySQL single-server SKUs.

    `azurerm_postgresql_server` (old single-server) was superseded by
    `azurerm_postgresql_flexible_server`. Same for MySQL.
    """
    return r.resource_type in ("azurerm_postgresql_server", "azurerm_mysql_server")


def _standard_lrs_savings(r: TerraformResource) -> float | None:
    size = r.attributes.get("disk_size_gb")
    if not isinstance(size, int | float):
        return None
    # Standard_LRS ~ $0.045/GB-month, StandardSSD_LRS ~ $0.075/GB-month for perf
    # uplift — but going *down* isn't the savings; going from Premium_LRS to
    # StandardSSD_LRS is. Here we flag only Standard_LRS being used for
    # workloads that likely need StandardSSD — so no guaranteed savings.
    # Use a conservative flat heuristic: 15% of nominal disk cost.
    return round(float(size) * 0.045 * 0.15, 2)


AZURE_RULES: list[SingleResourceRule] = [
    SingleResourceRule(
        pattern_type=CostPatternType.OVERSIZED_INSTANCE,
        applies=_is_oversized_azure_vm,
        describe=lambda r: (
            f"{r.address} uses {r.attributes.get('size') or r.attributes.get('vm_size')}, "
            "commonly over-provisioned for typical workloads."
        ),
        estimate_savings=lambda r: 250.0,
        confidence=0.6,
    ),
    SingleResourceRule(
        pattern_type=CostPatternType.OLDER_GENERATION_INSTANCE,
        applies=_is_older_gen_azure_vm,
        describe=lambda r: (
            f"{r.address} uses older-generation VM size "
            f"{r.attributes.get('size') or r.attributes.get('vm_size')}. "
            "Migrate to Dv5 / Ev5 / Dasv5 for ~15-20% better price-performance."
        ),
        estimate_savings=lambda r: 25.0,
        confidence=0.85,
    ),
    SingleResourceRule(
        pattern_type=CostPatternType.SUBOPTIMAL_DISK_TIER,
        applies=_is_standard_lrs_disk,
        describe=lambda r: (
            f"{r.address} uses Standard_LRS HDD. For VM OS disks and general-purpose workloads, "
            "StandardSSD_LRS has dramatically better IOPS at modest extra cost — "
            "or Premium_SSD_v2 lets you provision IOPS independently."
        ),
        estimate_savings=_standard_lrs_savings,
        confidence=0.7,
    ),
    SingleResourceRule(
        pattern_type=CostPatternType.UNUSED_PUBLIC_IP,
        applies=_is_unused_azure_public_ip,
        describe=lambda r: (
            f"{r.address} is a Standard SKU static public IP (~$3.60/month). "
            "Verify it is actually associated with a NIC, NAT Gateway, or Load Balancer."
        ),
        estimate_savings=lambda r: 3.6,
        confidence=0.5,
    ),
    SingleResourceRule(
        pattern_type=CostPatternType.OLDER_GENERATION_DATABASE,
        applies=_is_older_gen_azure_db,
        describe=lambda r: (
            f"{r.address} uses the deprecated '{r.resource_type}' (single server). "
            "Migrate to the flexible-server equivalent: lower cost, better features, no retirement date."
        ),
        estimate_savings=lambda r: 30.0,
        confidence=0.9,
    ),
]


# ══ GCP single-resource rules ═════════════════════════════════════════


def _is_oversized_gcp_instance(r: TerraformResource) -> bool:
    if r.resource_type != "google_compute_instance":
        return False
    mt = str(r.attributes.get("machine_type", ""))
    return any(mt.startswith(p) or mt.endswith(p) for p in OVERSIZED_GCP_PREFIXES)


def _is_older_gen_gcp_instance(r: TerraformResource) -> bool:
    if r.resource_type != "google_compute_instance":
        return False
    mt = str(r.attributes.get("machine_type", ""))
    return any(mt.startswith(p) for p in OLDER_GEN_GCP_PREFIXES)


def _is_pd_standard_disk(r: TerraformResource) -> bool:
    if r.resource_type not in ("google_compute_disk", "google_compute_region_disk"):
        return False
    return str(r.attributes.get("type", "pd-standard")) == "pd-standard"


def _is_unused_static_ip(r: TerraformResource) -> bool:
    """Reserved google_compute_address with no target.

    Unlike AWS, GCP charges for reserved static IPs only when they're *not*
    attached — attached ones are free. So this is a reliable anti-pattern.
    """
    if r.resource_type != "google_compute_address":
        return False
    # If a target is set via network_tier/purpose or implied via usage, skip.
    return r.attributes.get("purpose") not in ("GCE_ENDPOINT", "SHARED_LOADBALANCER_VIP")


def _pd_standard_savings(r: TerraformResource) -> float | None:
    size = r.attributes.get("size")
    if not isinstance(size, int | float):
        return None
    # pd-standard ~$0.04/GB-month, pd-balanced ~$0.10/GB-month (more perf).
    # Savings accrue the other direction only for low-perf workloads — here we
    # use a conservative heuristic of 10% of nominal disk cost as "optimization
    # potential" since pd-balanced gives major perf uplift at modest cost.
    return round(float(size) * 0.04 * 0.10, 2)


GCP_RULES: list[SingleResourceRule] = [
    SingleResourceRule(
        pattern_type=CostPatternType.OVERSIZED_INSTANCE,
        applies=_is_oversized_gcp_instance,
        describe=lambda r: (
            f"{r.address} uses {r.attributes.get('machine_type')}, a very large GCE machine type "
            "commonly over-provisioned for typical workloads."
        ),
        estimate_savings=lambda r: 300.0,
        confidence=0.6,
    ),
    SingleResourceRule(
        pattern_type=CostPatternType.OLDER_GENERATION_INSTANCE,
        applies=_is_older_gen_gcp_instance,
        describe=lambda r: (
            f"{r.address} uses older-gen machine type {r.attributes.get('machine_type')}. "
            "Migrate to e2-/n2-/n2d- for ~20-30% better price-performance. "
            "e2-standard/highmem in particular is often a direct n1- replacement."
        ),
        estimate_savings=lambda r: 20.0,
        confidence=0.85,
    ),
    SingleResourceRule(
        pattern_type=CostPatternType.SUBOPTIMAL_DISK_TIER,
        applies=_is_pd_standard_disk,
        describe=lambda r: (
            f"{r.address} uses pd-standard (HDD). pd-balanced offers much higher IOPS for "
            "a modest cost bump and is the recommended default; pd-standard is usually only a win "
            "for very large, infrequently accessed volumes."
        ),
        estimate_savings=_pd_standard_savings,
        confidence=0.7,
    ),
    SingleResourceRule(
        pattern_type=CostPatternType.UNUSED_PUBLIC_IP,
        applies=_is_unused_static_ip,
        describe=lambda r: (
            f"{r.address} is a reserved static IP. GCP bills these only when *not* attached "
            "(~$2.92/month). Verify it is actually being used by a forwarding rule or instance."
        ),
        estimate_savings=lambda r: 2.92,
        confidence=0.5,
    ),
]


SINGLE_RESOURCE_RULES: list[SingleResourceRule] = [*AWS_RULES, *AZURE_RULES, *GCP_RULES]


# ══ Collection rules (cross-resource patterns) ════════════════════════


def _nat_gateway_rule(
    tf_type: str,
    label: str,
    resources: list[TerraformResource],
) -> list[CostPattern]:
    nats = [r for r in resources if r.resource_type == tf_type]
    if len(nats) < 3:
        return []
    savings = (len(nats) - 1) * NAT_GATEWAY_MONTHLY_USD
    return [
        CostPattern(
            pattern_type=CostPatternType.EXPENSIVE_NAT_GATEWAY,
            resource_address=",".join(r.address for r in nats),
            description=(
                f"{len(nats)} {label} detected (~${NAT_GATEWAY_MONTHLY_USD:.0f}/month each). "
                "For non-production, a single NAT may suffice."
            ),
            estimated_savings_monthly=round(savings, 2),
            confidence=0.7,
        )
    ]


COLLECTION_RULES: list[CollectionRule] = [
    CollectionRule(
        pattern_type=CostPatternType.EXPENSIVE_NAT_GATEWAY,
        applies=lambda rs: sum(1 for r in rs if r.resource_type == "aws_nat_gateway") >= 3,
        build=lambda rs: _nat_gateway_rule("aws_nat_gateway", "AWS NAT Gateways", rs),
    ),
    CollectionRule(
        pattern_type=CostPatternType.EXPENSIVE_NAT_GATEWAY,
        applies=lambda rs: sum(1 for r in rs if r.resource_type == "azurerm_nat_gateway") >= 3,
        build=lambda rs: _nat_gateway_rule("azurerm_nat_gateway", "Azure NAT Gateways", rs),
    ),
    CollectionRule(
        pattern_type=CostPatternType.EXPENSIVE_NAT_GATEWAY,
        applies=lambda rs: sum(1 for r in rs if r.resource_type == "google_compute_router_nat") >= 3,
        build=lambda rs: _nat_gateway_rule("google_compute_router_nat", "GCP Cloud NAT gateways", rs),
    ),
]


# ══ Entry point ═══════════════════════════════════════════════════════


def detect_patterns(resources: list[TerraformResource]) -> list[CostPattern]:
    """Run all rules and return the accumulated list of CostPattern findings."""
    findings: list[CostPattern] = []

    for resource in resources:
        for rule in SINGLE_RESOURCE_RULES:
            if rule.applies(resource):
                findings.append(
                    CostPattern(
                        pattern_type=rule.pattern_type,
                        resource_address=resource.address,
                        description=rule.describe(resource),
                        estimated_savings_monthly=rule.estimate_savings(resource),
                        confidence=rule.confidence,
                    )
                )

    for crule in COLLECTION_RULES:
        if crule.applies(resources):
            findings.extend(crule.build(resources))

    return findings
