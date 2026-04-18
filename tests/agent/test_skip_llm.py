"""
Verify that skip_llm short-circuits both LLM nodes without ever calling an LLM.

We construct a minimal cost estimate + pattern list in-memory and run just
the two LLM-backed nodes directly. `create_llm` is patched to raise if it
were ever called — the test fails loudly if the short-circuit breaks.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from iaccostagent.agent.nodes.generate_report import generate_report_node
from iaccostagent.agent.nodes.suggest_optimizations import suggest_optimizations_node
from iaccostagent.models.schemas import (
    CloudProvider,
    CostEstimate,
    CostPattern,
    CostPatternType,
    ResourceCost,
    TerraformResource,
)


def _sample_state(skip_llm: bool) -> dict:
    resource = TerraformResource(
        resource_type="aws_ebs_volume",
        resource_name="data",
        address="aws_ebs_volume.data",
        provider=CloudProvider.AWS,
        attributes={"type": "gp2", "size": 500},
    )
    estimate = CostEstimate(
        backend="infracost",
        total_monthly_cost=50.0,
        provider=CloudProvider.AWS,
        region="us-east-1",
        resource_costs=[
            ResourceCost(resource=resource, monthly_cost=50.0, percentage_of_total=100.0),
        ],
        estimated_at=datetime.now(UTC),
    )
    patterns = [
        CostPattern(
            pattern_type=CostPatternType.MISSING_GP3_STORAGE,
            resource_address="aws_ebs_volume.data",
            description="gp2 volume",
            estimated_savings_monthly=10.0,
        )
    ]
    return {
        "project_path": "/tmp/fake",
        "input_format": "hcl",
        "backend": "infracost",
        "region": "us-east-1",
        "llm_provider": "ollama/qwen3:8b",
        "skip_llm": skip_llm,
        "resources": [resource],
        "cost_estimate": estimate,
        "patterns": patterns,
        "optimizations": [],
        "report": None,
        "current_node": "",
        "iteration": 0,
        "errors": [],
        "messages": [],
    }


class TestSkipLLMSuggestOptimizations:
    async def test_skip_llm_uses_rule_fallback(self) -> None:
        state = _sample_state(skip_llm=True)
        with patch(
            "iaccostagent.agent.nodes.suggest_optimizations.create_llm",
            side_effect=AssertionError("LLM should not be called when skip_llm=True"),
        ):
            result = await suggest_optimizations_node(state)
        assert len(result["optimizations"]) == 1
        assert result["optimizations"][0].resource_address == "aws_ebs_volume.data"
        assert result["optimizations"][0].estimated_monthly_savings == 10.0


class TestSkipLLMGenerateReport:
    async def test_skip_llm_uses_rule_based_summary(self) -> None:
        state = _sample_state(skip_llm=True)
        # Pretend suggest_optimizations already ran and filled this in.
        from iaccostagent.agent.nodes.suggest_optimizations import _fallback_suggestions

        state["optimizations"] = _fallback_suggestions(state["patterns"])

        with patch(
            "iaccostagent.agent.nodes.generate_report.create_llm",
            side_effect=AssertionError("LLM should not be called when skip_llm=True"),
        ):
            result = await generate_report_node(state)

        report = result["report"]
        assert report is not None
        assert report.total_monthly_cost == 50.0
        # Rule-based summary mentions the monthly total and savings.
        assert "$50.00" in report.executive_summary
        assert "savings" in report.executive_summary.lower()


class TestEndToEndSkipLLM:
    """Full pipeline with skip_llm=True — never contact Ollama/OpenAI."""

    async def test_run_analysis_skip_llm(
        self,
        terraform_fixtures_dir,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Patch the backend to avoid running infracost.
        from unittest.mock import AsyncMock

        from iaccostagent.agent.graph import run_analysis

        fake_estimate = CostEstimate(
            backend="infracost",
            total_monthly_cost=100.0,
            provider=CloudProvider.AWS,
            region="us-east-1",
            resource_costs=[],
            estimated_at=datetime.now(UTC),
        )

        with patch("iaccostagent.agent.nodes.estimate_costs._build_backend") as mock_build:
            backend_mock = mock_build.return_value
            backend_mock.estimate = AsyncMock(return_value=fake_estimate)

            # Fail loudly if either LLM node tries to create a client.
            with (
                patch(
                    "iaccostagent.agent.nodes.suggest_optimizations.create_llm",
                    side_effect=AssertionError("skip_llm must bypass LLM"),
                ),
                patch(
                    "iaccostagent.agent.nodes.generate_report.create_llm",
                    side_effect=AssertionError("skip_llm must bypass LLM"),
                ),
            ):
                report = await run_analysis(
                    str(terraform_fixtures_dir / "overprovisioned"),
                    backend="infracost",
                    region="us-east-1",
                    skip_llm=True,
                )

        assert report is not None
        assert report.total_monthly_cost == 100.0
        # Pattern engine still ran — overprovisioned fixture triggers patterns.
        assert len(report.patterns_detected) > 0
