from hypothesis import given, settings
from hypothesis import strategies as st

from tabby.engine.gst import RawCharge, build_charges
from tabby.engine.split import compute_split
from tabby.models import Bill, Category, Charge, ChargeKind, Item, Person, Scope

ASHA, BEN, CHITRA = Person(id="a", name="Asha"), Person(id="b", name="Ben"), Person(id="c", name="Chitra")


def bill(**kw) -> Bill:
    return Bill(people=[ASHA, BEN, CHITRA], **kw)


def totals(result) -> dict[str, int]:
    return {p.person_id: p.total for p in result.people}


def test_single_owner_items():
    b = bill(
        items=[Item(id="1", name="Biryani", amount=30000), Item(id="2", name="Naan", amount=6000)],
        assignments={"1": {"a": 1}, "2": {"b": 1, "c": 1}},
    )
    r = compute_split(b)
    assert totals(r) == {"a": 30000, "b": 3000, "c": 3000}
    assert r.unclaimed == 0
    assert r.progress == 1.0


def test_gst_proportional_to_food_and_vat_only_to_drinkers():
    b = bill(
        items=[
            Item(id="1", name="Paneer", amount=40000),
            Item(id="2", name="Beer", amount=50000, category=Category.LIQUOR),
        ],
        charges=[
            Charge(id="gst", name="GST 5%", amount=2000, scope=Scope.FOOD),
            Charge(id="vat", name="VAT", amount=10000, scope=Scope.LIQUOR),
        ],
        assignments={"1": {"a": 1, "b": 1, "c": 2}, "2": {"b": 1}},
    )
    r = compute_split(b)
    t = totals(r)
    assert t == {"a": 10000 + 500, "b": 10000 + 500 + 50000 + 10000, "c": 20000 + 1000}
    assert r.unclaimed == 0
    assert sum(t.values()) == r.bill_total


def test_disabled_service_charge_ignored():
    b = bill(
        items=[Item(id="1", name="Dosa", amount=10000)],
        charges=[Charge(id="s", name="Service charge", kind=ChargeKind.SERVICE, amount=1000, enabled=False)],
        assignments={"1": {"a": 1}},
    )
    r = compute_split(b)
    assert r.bill_total == 10000
    assert totals(r)["a"] == 10000


def test_unclaimed_items_keep_their_share_of_tax():
    b = bill(
        items=[Item(id="1", name="Dosa", amount=10000), Item(id="2", name="Idli", amount=10000)],
        charges=[Charge(id="t", name="GST", amount=1000)],
        assignments={"1": {"a": 1}},
    )
    r = compute_split(b)
    assert totals(r)["a"] == 10500
    assert r.unclaimed == 10500
    assert r.progress == 0.5


def test_discount_reduces_totals():
    b = bill(
        items=[Item(id="1", name="Pizza", amount=90000)],
        charges=[Charge(id="d", name="Discount", kind=ChargeKind.DISCOUNT, amount=-9001)],
        assignments={"1": {"a": 1, "b": 1, "c": 1}},
    )
    r = compute_split(b)
    assert sum(totals(r).values()) == 90000 - 9001
    assert r.unclaimed == 0


def test_charge_with_empty_scope_splits_evenly_with_warning():
    b = bill(
        items=[Item(id="1", name="Dosa", amount=10000)],
        charges=[Charge(id="v", name="VAT", amount=300, scope=Scope.LIQUOR)],
        assignments={"1": {"a": 1}},
    )
    r = compute_split(b)
    assert totals(r) == {"a": 10100, "b": 100, "c": 100}
    assert r.warnings


def test_build_charges_merges_cgst_sgst_and_scopes():
    raw = [
        RawCharge("CGST @2.5%", 1250),
        RawCharge("SGST @2.5%", 1250),
        RawCharge("VAT on liquor 20%", 4000),
        RawCharge("Service Charge 10%", 5000),
        RawCharge("Discount", 2000),
        RawCharge("Round off", -3),
    ]
    charges = build_charges(raw, has_liquor=True)
    by_name = {c.name: c for c in charges}
    assert by_name["GST 5%"].amount == 2500
    assert by_name["GST 5%"].scope is Scope.FOOD
    assert by_name["VAT on liquor 20%"].scope is Scope.LIQUOR
    assert by_name["Service Charge 10%"].kind is ChargeKind.SERVICE
    assert by_name["Discount"].amount == -2000
    assert by_name["Round off"].kind is ChargeKind.OTHER
    assert len({c.id for c in charges}) == len(charges)


def test_positive_round_off_keeps_its_sign():
    charges = build_charges([RawCharge("Round Off", 25), RawCharge("Rounded off", -10)], has_liquor=False)
    assert [c.amount for c in charges] == [25, -10]
    assert all(c.kind is ChargeKind.OTHER for c in charges)


def test_vat_without_liquor_spreads_over_all():
    charges = build_charges([RawCharge("VAT 5%", 500)], has_liquor=False)
    assert charges[0].scope is Scope.ALL


@st.composite
def random_bill(draw):
    n_people = draw(st.integers(min_value=1, max_value=8))
    people = [Person(id=f"p{i}", name=f"P{i}") for i in range(n_people)]
    n_items = draw(st.integers(min_value=0, max_value=15))
    items = [
        Item(
            id=f"i{i}",
            name=f"Item {i}",
            amount=draw(st.integers(min_value=0, max_value=500_000)),
            category=draw(st.sampled_from(list(Category))),
        )
        for i in range(n_items)
    ]
    charges = [
        Charge(
            id=f"c{i}",
            name=f"C{i}",
            amount=draw(st.integers(min_value=-50_000, max_value=100_000)),
            scope=draw(st.sampled_from(list(Scope))),
            enabled=draw(st.booleans()),
        )
        for i in range(draw(st.integers(min_value=0, max_value=5)))
    ]
    assignments = {}
    for item in items:
        if draw(st.booleans()):
            assignments[item.id] = {
                p.id: draw(st.integers(min_value=0, max_value=4)) for p in people if draw(st.booleans())
            }
    return Bill(people=people, items=items, charges=charges, assignments=assignments)


@settings(max_examples=1000)
@given(random_bill())
def test_fuzz_everything_adds_up_to_the_paisa(b):
    r = compute_split(b)
    assert sum(p.total for p in r.people) + r.unclaimed == r.bill_total
    for p in r.people:
        assert p.total == sum(line.amount for line in p.items) + sum(line.amount for line in p.charges)
    assert 0 <= r.progress <= 1
    fully_assigned = all(any(w > 0 for w in b.assignments.get(i.id, {}).values()) for i in b.items)
    if fully_assigned:
        assert r.unclaimed == 0
