"""
Node: parse_terraform

Reads either `.tf` files (HCL) or a Terraform plan JSON and populates
state['resources']. Pure Python — no LLM involved.
"""

from iaccostagent.agent.state import IaCCostState
from iaccostagent.parsers.hcl import HCLParser
from iaccostagent.parsers.plan_json import PlanJSONParser


async def parse_terraform_node(state: IaCCostState) -> dict:
    """Populate state['resources'] by parsing HCL or plan JSON."""
    path = state["project_path"]
    input_format = state.get("input_format", "hcl")
    errors = list(state.get("errors", []))

    parser = PlanJSONParser() if input_format == "plan-json" else HCLParser()

    try:
        resources = parser.parse(path)
    except FileNotFoundError as e:
        errors.append(str(e))
        resources = []
    except Exception as e:
        errors.append(f"Error parsing Terraform input: {e}")
        resources = []

    return {
        "resources": resources,
        "current_node": "parse_terraform",
        "errors": errors,
    }
