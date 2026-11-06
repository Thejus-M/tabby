"""Bill data model. Amounts are integer paise; the browser converts for display."""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class Category(StrEnum):
    FOOD = "food"
    LIQUOR = "liquor"


class Scope(StrEnum):
    """Which items a charge is levied on."""

    ALL = "all"
    FOOD = "food"
    LIQUOR = "liquor"


class ChargeKind(StrEnum):
    TAX = "tax"
    SERVICE = "service"
    DISCOUNT = "discount"
    OTHER = "other"


class Person(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=60)


class Item(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=120)
    quantity: float = Field(default=1, gt=0)
    amount: int = Field(ge=0, description="Line total in paise")
    category: Category = Category.FOOD


class Charge(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=80)
    kind: ChargeKind = ChargeKind.TAX
    amount: int = Field(description="Paise; negative for discounts")
    scope: Scope = Scope.ALL
    enabled: bool = True


class Bill(BaseModel):
    title: str = Field(default="", max_length=120)
    people: list[Person] = Field(default_factory=list, max_length=50)
    items: list[Item] = Field(default_factory=list, max_length=300)
    charges: list[Charge] = Field(default_factory=list, max_length=30)
    # item_id -> person_id -> weight (portions). Missing or empty means unclaimed.
    assignments: dict[str, dict[str, int]] = Field(default_factory=dict)
    payer_id: str | None = None

    @field_validator("assignments")
    @classmethod
    def _non_negative_weights(cls, v: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        for shares in v.values():
            if any(w < 0 for w in shares.values()):
                raise ValueError("assignment weights must be non-negative")
        return v

    @model_validator(mode="after")
    def _references_exist(self) -> "Bill":
        person_ids = {p.id for p in self.people}
        item_ids = {i.id for i in self.items}
        if len(person_ids) != len(self.people):
            raise ValueError("duplicate person id")
        if len(item_ids) != len(self.items):
            raise ValueError("duplicate item id")
        for item_id, shares in self.assignments.items():
            if item_id not in item_ids:
                raise ValueError(f"assignment for unknown item {item_id!r}")
            unknown = set(shares) - person_ids
            if unknown:
                raise ValueError(f"assignment to unknown person {sorted(unknown)!r}")
        if self.payer_id is not None and self.payer_id not in person_ids:
            raise ValueError("payer is not one of the people")
        return self


class Line(BaseModel):
    label: str
    amount: int


class PersonTotal(BaseModel):
    person_id: str
    name: str
    items: list[Line]
    charges: list[Line]
    subtotal: int
    charges_total: int
    total: int


class SplitResult(BaseModel):
    people: list[PersonTotal]
    bill_total: int
    claimed: int
    unclaimed: int
    progress: float = Field(description="Share of item value assigned, 0..1")
    warnings: list[str] = Field(default_factory=list)
