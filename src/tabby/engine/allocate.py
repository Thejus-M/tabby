"""Largest-remainder allocation: split an integer total by weights so parts sum exactly."""

from collections.abc import Sequence


def largest_remainder(total: int, weights: Sequence[int]) -> list[int]:
    """Split ``total`` (may be negative) across ``weights`` proportionally.

    Guarantees: ``sum(result) == total``; each part differs from its exact
    proportional share by less than 1; ties go to the earliest index, so the
    result is deterministic. Zero-weight slots always get 0.
    """
    if any(w < 0 for w in weights):
        raise ValueError("weights must be non-negative")
    weight_sum = sum(weights)
    if weight_sum == 0:
        if total != 0:
            raise ValueError("cannot allocate a non-zero total over zero weights")
        return [0] * len(weights)
    if total < 0:
        return [-part for part in largest_remainder(-total, weights)]

    floors = []
    remainders = []
    for w in weights:
        q, r = divmod(total * w, weight_sum)
        floors.append(q)
        remainders.append(r)

    leftover = total - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-remainders[i], i))
    for i in order[:leftover]:
        floors[i] += 1
    return floors
