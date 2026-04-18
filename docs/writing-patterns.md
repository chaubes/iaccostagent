# Writing a Cost Pattern Rule

Pattern rules are deterministic Python — no LLM calls. They produce `CostPattern` findings with rough monthly dollar savings estimates. The LLM layer later ranks them and attaches risk assessments.

There are two rule shapes in `patterns/rules.py`:

## Single-resource rule

Runs against every resource individually.

```python
SingleResourceRule(
    pattern_type=CostPatternType.OVERSIZED_INSTANCE,
    applies=lambda r: (
        r.resource_type == "aws_instance"
        and str(r.attributes.get("instance_type", "")).startswith("m5.4xlarge")
    ),
    describe=lambda r: (
        f"{r.address} uses {r.attributes.get('instance_type')}, often over-provisioned."
    ),
    estimate_savings=lambda r: 200.0,  # rough monthly USD
    confidence=0.6,
)
```

Append your rule to `SINGLE_RESOURCE_RULES`.

## Collection rule

Runs against the entire resource list (for aggregate patterns like "≥3 NAT Gateways").

```python
def _my_collection_rule(resources: list[TerraformResource]) -> list[CostPattern]:
    matching = [r for r in resources if ...]
    if not matching:
        return []
    return [
        CostPattern(
            pattern_type=CostPatternType.EXPENSIVE_NAT_GATEWAY,
            resource_address=",".join(r.address for r in matching),
            description="...",
            estimated_savings_monthly=...,
        )
    ]

COLLECTION_RULES.append(
    CollectionRule(
        pattern_type=CostPatternType.EXPENSIVE_NAT_GATEWAY,
        applies=lambda rs: any(...),
        build=_my_collection_rule,
    )
)
```

## Guidelines

- **Savings estimates are heuristics**, not precise forecasts. The cost backend provides the authoritative numbers; the rule's job is to flag the opportunity and give the LLM a starting point.
- **Confidence reflects how often this rule is actually actionable** — e.g., gp2 → gp3 is almost always safe (`confidence=0.95`), while right-sizing an instance often requires workload analysis (`confidence=0.6`).
- **Use attributes, not comments or tags** for matching. Comments are stripped by python-hcl2; tags vary widely.
- **Add a CostPatternType enum entry** in `models/schemas.py` if your pattern doesn't fit an existing one.
- **Write a fixture + test.** Any new pattern should have both a unit test (`tests/unit/test_patterns.py`) and, where relevant, a fixture `.tf` file that triggers it.
