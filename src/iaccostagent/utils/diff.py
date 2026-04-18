"""Cost diff helper used by the `iaccostagent diff` command."""

from iaccostagent.models.schemas import CostEstimate, DiffResult, ResourceCost


def diff_estimates(before: CostEstimate, after: CostEstimate) -> DiffResult:
    """Compute the added/removed/changed resources between two cost estimates."""
    before_by_addr = {rc.resource.address: rc for rc in before.resource_costs}
    after_by_addr = {rc.resource.address: rc for rc in after.resource_costs}

    added: list[ResourceCost] = [rc for addr, rc in after_by_addr.items() if addr not in before_by_addr]
    removed: list[ResourceCost] = [rc for addr, rc in before_by_addr.items() if addr not in after_by_addr]
    changed: list[tuple[ResourceCost, ResourceCost]] = []

    for addr, before_rc in before_by_addr.items():
        after_rc = after_by_addr.get(addr)
        if after_rc is not None and before_rc.monthly_cost != after_rc.monthly_cost:
            changed.append((before_rc, after_rc))

    before_total = before.total_monthly_cost
    after_total = after.total_monthly_cost
    delta = after_total - before_total
    pct = (delta / before_total * 100.0) if before_total > 0 else 0.0

    return DiffResult(
        before_monthly_cost=before_total,
        after_monthly_cost=after_total,
        delta_monthly=delta,
        delta_percentage=pct,
        added_resources=added,
        removed_resources=removed,
        changed_resources=changed,
    )
