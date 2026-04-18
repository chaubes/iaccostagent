"""
LangGraph graph construction for IaCCostAgent.

Wires the six agent nodes into a directed graph:

    parse_terraform → [has_resources?] → estimate_costs → analyze_resources
                                                              ↓
                                                       detect_patterns
                                                              ↓
                                                    suggest_optimizations
                                                              ↓
                                                     generate_report → END
                   [no_resources] ───────────────────────────→ generate_report → END
"""

from datetime import UTC, datetime
from pathlib import Path

from langgraph.graph import END, StateGraph

from iaccostagent.agent.nodes.analyze_resources import analyze_resources_node
from iaccostagent.agent.nodes.detect_patterns import detect_patterns_node
from iaccostagent.agent.nodes.estimate_costs import estimate_costs_node
from iaccostagent.agent.nodes.generate_report import generate_report_node
from iaccostagent.agent.nodes.parse_terraform import parse_terraform_node
from iaccostagent.agent.nodes.suggest_optimizations import suggest_optimizations_node
from iaccostagent.agent.state import IaCCostState
from iaccostagent.models.schemas import CostAnalysisReport


def _check_resources_found(state: IaCCostState) -> str:
    return "has_resources" if state.get("resources") else "no_resources"


def build_graph():
    """Construct and compile the IaCCostAgent graph."""
    workflow = StateGraph(IaCCostState)

    workflow.add_node("parse_terraform", parse_terraform_node)
    workflow.add_node("estimate_costs", estimate_costs_node)
    workflow.add_node("analyze_resources", analyze_resources_node)
    workflow.add_node("detect_patterns", detect_patterns_node)
    workflow.add_node("suggest_optimizations", suggest_optimizations_node)
    workflow.add_node("generate_report", generate_report_node)

    workflow.set_entry_point("parse_terraform")

    workflow.add_conditional_edges(
        "parse_terraform",
        _check_resources_found,
        {
            "has_resources": "estimate_costs",
            "no_resources": "generate_report",
        },
    )
    workflow.add_edge("estimate_costs", "analyze_resources")
    workflow.add_edge("analyze_resources", "detect_patterns")
    workflow.add_edge("detect_patterns", "suggest_optimizations")
    workflow.add_edge("suggest_optimizations", "generate_report")
    workflow.add_edge("generate_report", END)

    return workflow.compile()


async def run_analysis(
    project_path: str,
    *,
    input_format: str = "hcl",
    backend: str = "infracost",
    region: str | None = None,
    llm_provider: str = "ollama/qwen3:8b",
    skip_llm: bool = False,
) -> CostAnalysisReport | None:
    """Run a complete cost analysis and return the final report.

    Args:
        skip_llm: When True, the two LLM nodes short-circuit to their
            rule-based fallback paths without ever contacting a model.
    """
    graph = build_graph()

    initial_state: IaCCostState = {
        "project_path": project_path,
        "input_format": input_format,
        "backend": backend,
        "region": region,
        "llm_provider": llm_provider,
        "skip_llm": skip_llm,
        "resources": [],
        "cost_estimate": None,
        "patterns": [],
        "optimizations": [],
        "report": None,
        "current_node": "",
        "iteration": 0,
        "errors": [],
        "messages": [],
    }

    # LangSmith tracing config — picked up automatically when
    # LANGSMITH_TRACING=true is set in the environment.
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    project_name = Path(project_path).resolve().name
    run_config = {
        "run_name": f"iaccostagent-{backend}-{project_name}-{timestamp}",
        "tags": ["iaccostagent", backend, llm_provider.split("/")[0]],
        "metadata": {
            "project_path": project_path,
            "input_format": input_format,
            "backend": backend,
            "llm_provider": llm_provider,
        },
    }

    result = await graph.ainvoke(initial_state, config=run_config)
    return result.get("report")
