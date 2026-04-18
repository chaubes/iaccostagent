"""
Node: suggest_optimizations

Two-layer approach:
1. Rule-engine patterns (always present) give us ground-truth anti-patterns
   and rough dollar savings estimates.
2. LLM enrichment turns those patterns plus the cost breakdown into
   OptimizationSuggestions with risk assessment and Terraform-specific
   implementation notes.

If the LLM fails or returns unparseable JSON, we fall back to a
rule-derived OptimizationSuggestion per pattern so the report is still
useful without Ollama or OpenAI.
"""

import json
import re
from typing import Any

from iaccostagent.agent.state import IaCCostState
from iaccostagent.llm.prompts import OPTIMIZATION_ADVISOR_PROMPT
from iaccostagent.llm.provider import create_llm
from iaccostagent.models.schemas import (
    CostPattern,
    OptimizationRisk,
    OptimizationSuggestion,
)


def _extract_json(text: str) -> str:
    """Strip markdown code fences if the model wraps its response in them."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _coerce_risk(value: Any) -> OptimizationRisk:
    try:
        return OptimizationRisk(str(value).lower())
    except ValueError:
        return OptimizationRisk.MEDIUM


def _fallback_suggestions(patterns: list[CostPattern]) -> list[OptimizationSuggestion]:
    """Produce rule-based OptimizationSuggestions when the LLM is unavailable."""
    out: list[OptimizationSuggestion] = []
    for p in patterns:
        if not p.estimated_savings_monthly:
            continue
        out.append(
            OptimizationSuggestion(
                title=p.pattern_type.value.replace("_", " ").title(),
                resource_address=p.resource_address,
                current_config=p.description,
                suggested_config="See description for the suggested change.",
                estimated_monthly_savings=p.estimated_savings_monthly,
                risk=OptimizationRisk.MEDIUM,
                risk_explanation="Rule-based default risk — LLM enrichment unavailable.",
                implementation_notes=(
                    "Update the affected Terraform resource(s) with the recommended "
                    "configuration shown in the description."
                ),
            )
        )
    return out


async def suggest_optimizations_node(state: IaCCostState) -> dict:
    """LLM-enrich the rule-engine patterns into full OptimizationSuggestions."""
    estimate = state.get("cost_estimate")
    patterns = state.get("patterns", [])
    llm_provider = state.get("llm_provider", "ollama/qwen3:8b")
    errors = list(state.get("errors", []))
    skip_llm = state.get("skip_llm", False)

    if estimate is None or skip_llm:
        return {
            "optimizations": _fallback_suggestions(patterns),
            "current_node": "suggest_optimizations",
            "errors": errors,
        }

    resource_costs_json = json.dumps(
        [
            {
                "address": rc.resource.address,
                "resource_type": rc.resource.resource_type,
                "monthly_cost": rc.monthly_cost,
                "percentage_of_total": round(rc.percentage_of_total, 2),
                "attributes": rc.resource.attributes,
            }
            for rc in estimate.resource_costs
        ],
        indent=2,
    )

    patterns_json = json.dumps(
        [
            {
                "type": p.pattern_type.value,
                "resource_address": p.resource_address,
                "description": p.description,
                "estimated_savings_monthly": p.estimated_savings_monthly,
                "confidence": p.confidence,
            }
            for p in patterns
        ],
        indent=2,
    )

    prompt = OPTIMIZATION_ADVISOR_PROMPT.format(
        total_monthly_cost=f"{estimate.total_monthly_cost:.2f}",
        provider=estimate.provider.value if estimate.provider else "unknown",
        region=estimate.region or "unknown",
        resource_costs_json=resource_costs_json,
        patterns_json=patterns_json,
    )

    try:
        llm = create_llm(llm_provider)
        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        parsed = json.loads(_extract_json(str(content)))
        raw_opts = parsed.get("optimizations", [])

        optimizations: list[OptimizationSuggestion] = []
        for entry in raw_opts:
            try:
                optimizations.append(
                    OptimizationSuggestion(
                        title=str(entry.get("title", "Optimization opportunity")),
                        resource_address=str(entry.get("resource_address", "")),
                        current_config=str(entry.get("current_config", "")),
                        suggested_config=str(entry.get("suggested_config", "")),
                        estimated_monthly_savings=float(entry.get("estimated_monthly_savings", 0) or 0),
                        risk=_coerce_risk(entry.get("risk", "medium")),
                        risk_explanation=str(entry.get("risk_explanation", "")),
                        implementation_notes=str(entry.get("implementation_notes", "")),
                    )
                )
            except Exception as inner:
                errors.append(f"Skipping malformed optimization entry: {inner}")

        if not optimizations:
            optimizations = _fallback_suggestions(patterns)

    except Exception as e:
        errors.append(f"LLM optimization advisor failed (using rule-based fallback): {e}")
        optimizations = _fallback_suggestions(patterns)

    return {
        "optimizations": optimizations,
        "current_node": "suggest_optimizations",
        "iteration": state.get("iteration", 0) + 1,
        "errors": errors,
    }
