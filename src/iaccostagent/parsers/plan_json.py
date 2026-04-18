"""
Terraform plan JSON parser.

Reads the JSON produced by `terraform show -json tfplan.binary` and
flattens `planned_values.root_module` (recursively through child modules)
into a flat list of TerraformResource objects.
"""

import json
from pathlib import Path

from iaccostagent.models.schemas import TerraformResource
from iaccostagent.parsers.base import BaseTerraformParser, infer_provider


class PlanJSONParser(BaseTerraformParser):
    """Parse `terraform show -json` output."""

    def can_parse(self, path: str) -> bool:
        p = Path(path)
        if not p.is_file() or p.suffix != ".json":
            return False
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return False
        return "planned_values" in data or "format_version" in data

    def parse(self, path: str) -> list[TerraformResource]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Plan JSON not found: {path}")

        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid plan JSON at {path}: {e}") from e

        root_module = data.get("planned_values", {}).get("root_module", {})
        resources: list[TerraformResource] = []
        self._collect(root_module, resources, source=path)
        return resources

    def _collect(self, module: dict, out: list[TerraformResource], source: str) -> None:
        for r in module.get("resources", []):
            resource_type = r.get("type", "")
            resource_name = r.get("name", "")
            address = r.get("address", f"{resource_type}.{resource_name}")
            values = r.get("values", {}) or {}

            # Skip data sources; they have no cost.
            if r.get("mode") == "data":
                continue

            provider = infer_provider(resource_type)
            if provider is None:
                continue

            out.append(
                TerraformResource(
                    resource_type=resource_type,
                    resource_name=resource_name,
                    address=address,
                    provider=provider,
                    attributes=values,
                    source_file=source,
                )
            )

        for child in module.get("child_modules", []) or []:
            self._collect(child, out, source)
