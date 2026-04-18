"""
Node: detect_patterns

Runs the deterministic rule engine against the parsed resources.
Produces a list of CostPattern findings — rule-based and independent
of any LLM.
"""

from iaccostagent.agent.state import IaCCostState
from iaccostagent.patterns.rules import detect_patterns


async def detect_patterns_node(state: IaCCostState) -> dict:
    """Apply pattern rules to state['resources']."""
    resources = state.get("resources", [])
    patterns = detect_patterns(resources) if resources else []
    return {
        "patterns": patterns,
        "current_node": "detect_patterns",
        "errors": list(state.get("errors", [])),
    }
