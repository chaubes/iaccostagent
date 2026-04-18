"""
Node: analyze_resources

Correlates parsed Terraform resources with the cost backend's per-resource
cost data so downstream nodes can see both structure and dollars in one
place. Also ensures `percentage_of_total` is set on every ResourceCost.

When the cost backend can't identify a resource by address (common with
OpenInfraQuote's minimal output), we fall back to attribute-less
TerraformResource objects from the estimate itself.
"""

from iaccostagent.agent.state import IaCCostState
from iaccostagent.models.schemas import ResourceCost


async def analyze_resources_node(state: IaCCostState) -> dict:
    """Merge parsed resources' attributes back into the cost-backend output."""
    estimate = state.get("cost_estimate")
    parsed_resources = state.get("resources", [])
    errors = list(state.get("errors", []))

    if estimate is None:
        return {"current_node": "analyze_resources", "errors": errors}

    parsed_by_address = {r.address: r for r in parsed_resources}

    total = estimate.total_monthly_cost or 0.0
    enriched: list[ResourceCost] = []
    for rc in estimate.resource_costs:
        tfr = parsed_by_address.get(rc.resource.address)
        if tfr is not None:
            rc.resource = tfr.model_copy(update={"source_file": tfr.source_file})
        if total > 0 and rc.percentage_of_total == 0.0:
            rc.percentage_of_total = rc.monthly_cost / total * 100.0
        enriched.append(rc)

    estimate.resource_costs = enriched

    return {
        "cost_estimate": estimate,
        "current_node": "analyze_resources",
        "errors": errors,
    }
