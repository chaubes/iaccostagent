"""
Pydantic data models for IaCCostAgent.

Every piece of data flowing through the agent — parsed resources, cost
estimates from the backend, detected patterns, optimization suggestions,
and the final analysis report — is represented as one of these models.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# ── Enums ────────────────────────────────────────────────────


class CloudProvider(str, Enum):
    """Supported cloud providers."""

    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"


class CostPatternType(str, Enum):
    """Types of cost anti-patterns the rule engine can detect.

    Values are intentionally cloud-agnostic (e.g. UNUSED_PUBLIC_IP rather
    than UNUSED_ELASTIC_IP) so the same pattern type applies across AWS,
    Azure, and GCP. The rule itself encodes the provider specifics.
    """

    OVERSIZED_INSTANCE = "oversized_instance"
    MISSING_RESERVED_INSTANCE = "missing_reserved_instance"
    EXPENSIVE_NAT_GATEWAY = "expensive_nat_gateway"
    OVERSIZED_STORAGE = "oversized_storage"
    MISSING_LIFECYCLE_POLICY = "missing_lifecycle_policy"
    REDUNDANT_FOR_NON_PROD = "redundant_for_non_prod"
    OLDER_GENERATION_INSTANCE = "older_generation_instance"
    MISSING_SPOT_OPPORTUNITY = "missing_spot_opportunity"
    DATA_TRANSFER_COST = "data_transfer_cost"
    UNUSED_PUBLIC_IP = "unused_public_ip"  # AWS EIP, Azure public IP, GCP static IP
    UNUSED_ELASTIC_IP = "unused_elastic_ip"  # kept for backwards-compat with older reports
    MISSING_GP3_STORAGE = "missing_gp3_storage"
    SUBOPTIMAL_DISK_TIER = "suboptimal_disk_tier"  # Azure Standard_LRS→StandardSSD, GCP pd-standard→pd-balanced
    UNATTACHED_DISK = "unattached_disk"
    OLDER_GENERATION_DATABASE = "older_generation_database"


class OptimizationRisk(str, Enum):
    """Risk levels attached to optimization suggestions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ── Core Models ──────────────────────────────────────────────


class TerraformResource(BaseModel):
    """A single resource parsed from Terraform configuration (HCL or plan JSON)."""

    resource_type: str = Field(description="e.g., aws_instance, azurerm_virtual_machine")
    resource_name: str = Field(description="e.g., web_server, database")
    address: str = Field(description="Full Terraform address: aws_instance.web_server")
    provider: CloudProvider
    attributes: dict = Field(
        default_factory=dict,
        description="Key resource attributes (instance_type, engine, etc.)",
    )
    source_file: str | None = None
    line_number: int | None = None


class CostComponent(BaseModel):
    """A single cost component within a resource (e.g., compute hours, storage GB)."""

    name: str = Field(description="e.g., 'Linux/UNIX usage (on-demand, t3.large)'")
    unit: str = Field(description="e.g., 'hours', 'GB', 'requests'")
    monthly_quantity: float | None = None
    monthly_unit_cost: float | None = None
    monthly_cost: float
    is_usage_based: bool = Field(
        default=False,
        description="Whether this cost depends on actual usage (e.g., GB egress)",
    )


class ResourceCost(BaseModel):
    """Cost data for a single Terraform resource."""

    resource: TerraformResource
    monthly_cost: float
    hourly_cost: float | None = None
    cost_components: list[CostComponent] = []
    percentage_of_total: float = 0.0


class CostEstimate(BaseModel):
    """Complete cost estimate returned by a cost backend."""

    backend: str = Field(description="infracost or openinfraquote")
    currency: str = "USD"
    total_monthly_cost: float
    total_hourly_cost: float | None = None
    resource_costs: list[ResourceCost] = []
    provider: CloudProvider | None = None
    region: str | None = None
    estimated_at: datetime


class CostPattern(BaseModel):
    """A cost anti-pattern detected by the rule engine."""

    pattern_type: CostPatternType
    resource_address: str
    description: str
    estimated_savings_monthly: float | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)


class OptimizationSuggestion(BaseModel):
    """An LLM-generated cost optimization suggestion."""

    title: str
    resource_address: str
    current_config: str = Field(description="Current configuration description")
    suggested_config: str = Field(description="Suggested configuration change")
    estimated_monthly_savings: float
    risk: OptimizationRisk
    risk_explanation: str
    implementation_notes: str = Field(description="How to implement this change in Terraform")


class DiffResult(BaseModel):
    """Result of comparing two Terraform configurations."""

    before_monthly_cost: float
    after_monthly_cost: float
    delta_monthly: float
    delta_percentage: float
    added_resources: list[ResourceCost] = []
    removed_resources: list[ResourceCost] = []
    changed_resources: list[tuple[ResourceCost, ResourceCost]] = []


class CostAnalysisReport(BaseModel):
    """Final output of an IaCCostAgent analysis run."""

    project_path: str
    analyzed_at: datetime
    backend_used: str
    provider: CloudProvider | None
    region: str | None
    total_monthly_cost: float
    resource_count: int
    top_cost_drivers: list[ResourceCost] = []
    patterns_detected: list[CostPattern] = []
    optimizations: list[OptimizationSuggestion] = []
    total_potential_savings: float = 0.0
    savings_percentage: float = 0.0
    executive_summary: str = Field(default="", description="LLM-generated plain-English summary")
    diff: DiffResult | None = None
    errors: list[str] = []
