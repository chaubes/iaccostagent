"""
Node: estimate_costs

Calls the configured cost backend (Infracost or OpenInfraQuote) against
the input path and normalizes the response into a CostEstimate.
"""

from iaccostagent.agent.state import IaCCostState
from iaccostagent.backends.base import CostBackend
from iaccostagent.backends.registry import get_backend


def _build_backend(name: str) -> CostBackend:
    try:
        return get_backend(name)
    except KeyError as e:
        raise ValueError(str(e)) from e


async def estimate_costs_node(state: IaCCostState) -> dict:
    """Run the chosen cost backend against the project path."""
    backend_name = state.get("backend", "infracost")
    path = state["project_path"]
    region = state.get("region")
    errors = list(state.get("errors", []))

    try:
        backend = _build_backend(backend_name)
        estimate = await backend.estimate(path, region=region)
    except Exception as e:
        errors.append(f"Cost estimation failed ({backend_name}): {e}")
        estimate = None

    return {
        "cost_estimate": estimate,
        "current_node": "estimate_costs",
        "errors": errors,
    }
