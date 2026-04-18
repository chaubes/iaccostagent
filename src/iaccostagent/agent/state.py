"""
LangGraph agent state definition.

Every node receives this TypedDict, reads what it needs, and returns a
partial update that LangGraph merges back into the running state.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages

from iaccostagent.models.schemas import (
    CostAnalysisReport,
    CostEstimate,
    CostPattern,
    OptimizationSuggestion,
    TerraformResource,
)


class IaCCostState(TypedDict):
    """Complete state of an IaCCostAgent analysis run."""

    # ── Input (set once at the start) ──
    project_path: str
    input_format: str  # "hcl" | "plan-json"
    backend: str  # "infracost" | "openinfraquote"
    region: str | None
    llm_provider: str
    skip_llm: bool  # when True, suggest_optimizations and generate_report skip the LLM

    # ── Pipeline data (accumulated by nodes) ──
    resources: list[TerraformResource]
    cost_estimate: CostEstimate | None
    patterns: list[CostPattern]
    optimizations: list[OptimizationSuggestion]

    # ── Output ──
    report: CostAnalysisReport | None

    # ── Control flow ──
    current_node: str
    iteration: int
    errors: list[str]

    # ── LLM message history ──
    messages: Annotated[list[BaseMessage], add_messages]
