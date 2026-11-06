import pytest
from hypothesis import given
from hypothesis import strategies as st

from tabby.engine.allocate import largest_remainder

weights_st = st.lists(st.integers(min_value=0, max_value=10_000), min_size=1, max_size=30).filter(lambda w: sum(w) > 0)


@given(total=st.integers(min_value=-10_000_000, max_value=10_000_000), weights=weights_st)
def test_parts_sum_exactly_and_stay_within_one_paisa(total, weights):
    parts = largest_remainder(total, weights)
    assert sum(parts) == total
    weight_sum = sum(weights)
    for part, w in zip(parts, weights, strict=True):
        exact = total * w / weight_sum
        assert abs(part - exact) < 1
        if w == 0:
            assert part == 0


def test_even_split_gives_extra_paisa_to_first():
    assert largest_remainder(100, [1, 1, 1]) == [34, 33, 33]


def test_deterministic():
    assert largest_remainder(1001, [3, 2, 2]) == largest_remainder(1001, [3, 2, 2])


def test_zero_weights():
    assert largest_remainder(0, [0, 0]) == [0, 0]
    with pytest.raises(ValueError):
        largest_remainder(5, [0, 0])


def test_negative_weight_rejected():
    with pytest.raises(ValueError):
        largest_remainder(5, [1, -1])
