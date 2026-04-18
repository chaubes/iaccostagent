"""
HCL/Terraform file parser.

Walks a directory of `.tf` files using python-hcl2 and extracts every
`resource` block. Other block types (data, module, variable, output,
provider, terraform, locals) are ignored — they have no direct cost.

Nested modules referenced via `module` blocks are NOT expanded in v1.
Users who need multi-module coverage should pass a plan JSON instead.
"""

from pathlib import Path
from typing import Any

import hcl2

from iaccostagent.models.schemas import TerraformResource
from iaccostagent.parsers.base import BaseTerraformParser, infer_provider


class HCLParser(BaseTerraformParser):
    """Parse one or more `.tf` files into TerraformResource objects."""

    def can_parse(self, path: str) -> bool:
        """True if `path` is a `.tf` file or a directory containing `.tf` files."""
        p = Path(path)
        if p.is_file():
            return p.suffix == ".tf"
        if p.is_dir():
            return any(p.glob("*.tf"))
        return False

    def parse(self, path: str) -> list[TerraformResource]:
        """Parse a file or directory. Missing path raises FileNotFoundError."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Path not found: {path}")

        files: list[Path]
        if p.is_file():
            files = [p]
        else:
            files = sorted(p.glob("*.tf"))

        resources: list[TerraformResource] = []
        for tf_file in files:
            resources.extend(self._parse_file(tf_file))
        return resources

    def _parse_file(self, tf_file: Path) -> list[TerraformResource]:
        with tf_file.open() as f:
            parsed = hcl2.load(f)

        resource_blocks = parsed.get("resource", [])
        out: list[TerraformResource] = []

        # python-hcl2 v8 yields a list of single-key dicts for resource blocks, where
        # each key / string value carries its source HCL quoting. Example:
        #   [{'"aws_instance"': {'"web"': {'instance_type': '"t3.large"', ...}}}]
        for block in resource_blocks:
            for raw_type, named in block.items():
                resource_type = _unquote(raw_type)
                if not isinstance(named, dict):
                    continue
                for raw_name, attrs in named.items():
                    resource_name = _unquote(raw_name)
                    provider = infer_provider(resource_type)
                    if provider is None:
                        # Non-cloud provider (null_resource, random_*, etc.) — skip
                        continue
                    cleaned_attrs = _clean_attrs(attrs)
                    for address, instance_attrs in _expand_instances(resource_type, resource_name, cleaned_attrs):
                        out.append(
                            TerraformResource(
                                resource_type=resource_type,
                                resource_name=resource_name,
                                address=address,
                                provider=provider,
                                attributes=instance_attrs,
                                source_file=str(tf_file),
                            )
                        )
        return out


def _unquote(value: Any) -> Any:
    """Strip a single layer of surrounding double-quotes left in by python-hcl2."""
    if isinstance(value, str) and len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _clean_attrs(attrs: Any) -> dict:
    """
    Normalize a block's attributes:
      - drop the `__is_block__` marker python-hcl2 adds to every block
      - strip surrounding quotes on string values
      - unwrap single-element lists (legacy python-hcl2 behavior)
      - recurse into nested dicts (e.g., `tags = { ... }`)
    """
    if not isinstance(attrs, dict):
        return {}

    out: dict = {}
    for k, v in attrs.items():
        if k == "__is_block__":
            continue
        if isinstance(v, list) and len(v) == 1:
            v = v[0]
        if isinstance(v, dict):
            out[k] = _clean_attrs(v)
        else:
            out[k] = _unquote(v)
    return out


def _expand_instances(resource_type: str, resource_name: str, attrs: dict) -> list[tuple[str, dict]]:
    """
    Expand Terraform's `count` and `for_each` meta-arguments into one entry per
    instance — matching Terraform / Infracost semantics.

    Examples::

        count = 3                           → name[0], name[1], name[2]
        for_each = { a = ..., b = ... }     → name["a"], name["b"]
        for_each = ["a", "b"]               → name["a"], name["b"]  (set-of-strings)

    When count or for_each is a variable/expression we can't evaluate at parse
    time (e.g. `count = var.replicas`), we fall back to a single instance so the
    resource still appears in the report — with a note that users who need full
    expansion should run against a `terraform plan` JSON instead.

    Meta-arguments `count` / `for_each` / `depends_on` / `provider` / `lifecycle`
    are stripped from each instance's attributes since they aren't real
    resource attributes.
    """
    meta_keys = {"count", "for_each", "depends_on", "provider", "lifecycle"}
    base = {k: v for k, v in attrs.items() if k not in meta_keys}
    base_address = f"{resource_type}.{resource_name}"

    count = attrs.get("count")
    for_each = attrs.get("for_each")

    if isinstance(count, int) and count >= 0:
        return [(f"{base_address}[{i}]", dict(base)) for i in range(count)]
    if isinstance(count, bool):  # bool is a subtype of int; guard explicitly.
        pass

    if isinstance(for_each, dict):
        return [(f'{base_address}["{k}"]', dict(base)) for k in for_each]

    if isinstance(for_each, list):
        # Treat as a set-of-strings literal (most common for_each = toset([...]) pattern
        # where python-hcl2 has evaluated toset() at parse time).
        keys = [str(k) for k in for_each if isinstance(k, str | int | float)]
        if keys:
            return [(f'{base_address}["{k}"]', dict(base)) for k in keys]

    # count/for_each missing or not evaluable at parse time — single instance.
    return [(base_address, dict(base))]
