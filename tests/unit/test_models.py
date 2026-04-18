"""Schema sanity tests — round-trip, validation, enum coverage."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from iaccostagent.models.schemas import (
    CloudProvider,
    CostAnalysisReport,
    CostEstimate,
    CostPattern,
    CostPatternType,
    OptimizationRisk,
    OptimizationSuggestion,
    ResourceCost,
    TerraformResource,
)


class TestTerraformResource:
    def test_minimal_construction(self) -> None:
        r = TerraformResource(
            resource_type="aws_instance",
            resource_name="web",
            address="aws_instance.web",
            provider=CloudProvider.AWS,
        )
        assert r.attributes == {}
        assert r.source_file is None


class TestCostEstimate:
    def test_empty_estimate_valid(self) -> None:
        e = CostEstimate(
            backend="infracost",
            total_monthly_cost=0.0,
            estimated_at=datetime.now(UTC),
        )
        assert e.resource_costs == []


class TestCostPattern:
    def test_confidence_bounds(self) -> None:
        CostPattern(
            pattern_type=CostPatternType.OVERSIZED_INSTANCE,
            resource_address="aws_instance.x",
            description="foo",
            confidence=1.0,
        )
        with pytest.raises(ValidationError):
            CostPattern(
                pattern_type=CostPatternType.OVERSIZED_INSTANCE,
                resource_address="aws_instance.x",
                description="foo",
                confidence=1.5,
            )


class TestOptimizationSuggestion:
    def test_risk_enum(self) -> None:
        s = OptimizationSuggestion(
            title="Right-size EC2",
            resource_address="aws_instance.web",
            current_config="m5.4xlarge",
            suggested_config="m5.large",
            estimated_monthly_savings=400.0,
            risk=OptimizationRisk.MEDIUM,
            risk_explanation="requires performance testing",
            implementation_notes="change instance_type attribute",
        )
        assert s.risk == OptimizationRisk.MEDIUM


class TestReportJsonRoundTrip:
    def test_roundtrip(self) -> None:
        report = CostAnalysisReport(
            project_path="/x",
            analyzed_at=datetime.now(UTC),
            backend_used="infracost",
            provider=CloudProvider.AWS,
            region="us-east-1",
            total_monthly_cost=100.0,
            resource_count=1,
            top_cost_drivers=[
                ResourceCost(
                    resource=TerraformResource(
                        resource_type="aws_instance",
                        resource_name="x",
                        address="aws_instance.x",
                        provider=CloudProvider.AWS,
                    ),
                    monthly_cost=100.0,
                )
            ],
        )
        as_json = report.model_dump_json()
        parsed = CostAnalysisReport.model_validate_json(as_json)
        assert parsed.total_monthly_cost == 100.0
