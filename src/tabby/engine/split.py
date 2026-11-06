"""Compute who owes what. Pure function, no I/O."""

from tabby.engine.allocate import largest_remainder
from tabby.models import Bill, Category, Line, PersonTotal, Scope, SplitResult


def _in_scope(category: Category, scope: Scope) -> bool:
    return scope is Scope.ALL or category.value == scope.value


def compute_split(bill: Bill) -> SplitResult:
    people = bill.people
    item_lines: list[list[Line]] = [[] for _ in people]
    charge_lines: list[list[Line]] = [[] for _ in people]
    # Per-person and unclaimed item value by category, used to spread charges.
    claimed_by_cat = {c: [0] * len(people) for c in Category}
    unclaimed_by_cat = dict.fromkeys(Category, 0)
    warnings: list[str] = []

    for item in bill.items:
        shares = {pid: w for pid, w in bill.assignments.get(item.id, {}).items() if w > 0}
        if not shares:
            unclaimed_by_cat[item.category] += item.amount
            continue
        weights = [shares.get(p.id, 0) for p in people]
        total_weight = sum(weights)
        for i, part in enumerate(largest_remainder(item.amount, weights)):
            if weights[i] == 0:
                continue
            name = item.name.strip() or "Item"
            label = name if len(shares) == 1 else f"{name} ({weights[i]}/{total_weight})"
            item_lines[i].append(Line(label=label, amount=part))
            claimed_by_cat[item.category][i] += part

    for charge in bill.charges:
        if not charge.enabled or charge.amount == 0:
            continue
        cats = [c for c in Category if _in_scope(c, charge.scope)]
        weights = [sum(claimed_by_cat[c][i] for c in cats) for i in range(len(people))]
        weights.append(sum(unclaimed_by_cat[c] for c in cats))  # unclaimed bucket
        if sum(weights) == 0:
            warnings.append(f"No {charge.scope.value} items for “{charge.name or 'charge'}”; split evenly.")
            weights = [1] * len(people) + [0 if people else 1]
        parts = largest_remainder(charge.amount, weights)
        for i, part in enumerate(parts[:-1]):
            if part:
                charge_lines[i].append(Line(label=charge.name.strip() or "Charge", amount=part))

    totals = []
    for i, person in enumerate(people):
        subtotal = sum(line.amount for line in item_lines[i])
        charges_total = sum(line.amount for line in charge_lines[i])
        totals.append(
            PersonTotal(
                person_id=person.id,
                name=person.name,
                items=item_lines[i],
                charges=charge_lines[i],
                subtotal=subtotal,
                charges_total=charges_total,
                total=subtotal + charges_total,
            )
        )

    item_total = sum(item.amount for item in bill.items)
    bill_total = item_total + sum(c.amount for c in bill.charges if c.enabled)
    claimed = sum(t.total for t in totals)
    unclaimed_items = sum(unclaimed_by_cat.values())
    progress = 1.0 if item_total == 0 else (item_total - unclaimed_items) / item_total
    return SplitResult(
        people=totals,
        bill_total=bill_total,
        claimed=claimed,
        unclaimed=bill_total - claimed,
        progress=round(progress, 4),
        warnings=warnings,
    )
