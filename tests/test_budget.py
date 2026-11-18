# backend/budget.py: the cost of each item in the budget's unit, the kept total against the budget, and the
# fit-budget proposal. Money is Decimal inside budget.py and leaves it as 2-place strings, never floats.
# Prices here are fixed test examples.
from decimal import Decimal

from backend import budget


def profile(amount="250", per="person", size=4):
    return {"group_size": size, "budget": {"amount": amount, "currency": "EUR", "per": per}}


def price(amount_eur, per="person", currency="EUR"):
    return {"amount": amount_eur, "currency": currency, "per": per, "amount_eur": amount_eur, "fx": None, "source": None}


def exp(id, amount_eur, per="person", kept=True, status="to_check"):
    return {"id": id, "price": price(amount_eur, per), "status": status,
            "user": {"status": "kept" if kept else "removed", "position": None}}


def test_money_is_decimal_rounded_half_up():
    assert budget.money("2.005") == Decimal("2.01")
    assert budget.money(35) == Decimal("35.00")
    assert budget.fmt(Decimal("7.5")) == "7.50"


def test_unit_cost_per_person_budget():
    p = profile(per="person", size=4)
    assert budget.unit_cost(price(35.0), p) == Decimal("35.00")               # per person: as stated
    assert budget.unit_cost(price(100.0, per="group"), p) == Decimal("25.00")  # group price split over 4
    assert budget.unit_cost(price(10.0, per="group"), profile(size=3)) == Decimal("3.33")
    assert budget.unit_cost(price(None, per="free"), p) == Decimal("0.00")
    assert budget.unit_cost(price(None), p) is None                           # no price: not counted


def test_unit_cost_total_budget():
    p = profile(per="total", size=4)
    assert budget.unit_cost(price(35.0), p) == Decimal("140.00")              # 35 x 4
    assert budget.unit_cost(price(100.0, per="group"), p) == Decimal("100.00")
    assert budget.unit_cost(price(None, per="free"), p) == Decimal("0.00")


def test_item_cost_is_a_string_or_none():
    assert budget.item_cost(price(35.0), profile()) == "35.00"
    assert budget.item_cost(price(None), profile()) is None


def test_alone_over_budget():
    assert budget.alone_over_budget(price(300.0), profile("250")) is True
    assert budget.alone_over_budget(price(250.0), profile("250")) is False
    assert budget.alone_over_budget(price(70.0), profile("250", per="total", size=4)) is True   # 280 > 250
    assert budget.alone_over_budget(price(None), profile()) is False


def test_totals_count_only_kept_and_not_rejected():
    exps = [exp("a", 35.0), exp("b", 18.0), exp("c", 62.0, kept=False), exp("d", 99.0, status="rejected"),
            exp("e", None)]
    t = budget.totals(profile("250"), exps)
    assert t == {"per": "person", "group_size": 4, "budget": "250.00", "used": "53.00", "left": "197.00",
                 "over_by": "0.00", "over": False, "kept": 3, "counted": ["a", "b"], "not_counted": ["e"]}


def test_totals_over_budget_in_total_mode():
    t = budget.totals(profile("200", per="total", size=4), [exp("a", 35.0), exp("b", 18.0)])
    assert (t["used"], t["left"], t["over_by"], t["over"]) == ("212.00", "0.00", "12.00", True)


def test_totals_never_hold_floats():
    t = budget.totals(profile(), [exp("a", 35.1)])
    for key in ("budget", "used", "left", "over_by"):
        assert isinstance(t[key], str)


def test_fit_proposal_removes_last_added_priced_items_first():
    exps = [exp("first", 100.0), exp("second", 80.0), exp("no-price", None), exp("third", 30.0),
            exp("free", None, per="free"), exp("gone", 500.0, kept=False)]
    # kept and counted: 100 + 80 + 30 = 210 > 150. From the bottom: free (skip), third (30) -> 180, no-price (skip),
    # second (80) -> 100: within budget.
    proposal = budget.fit_proposal(profile("150"), exps)
    assert proposal == {"remove": ["third", "second"], "used_after": "100.00", "budget": "150.00",
                        "within_budget": True}


def test_fit_proposal_when_already_within_budget():
    proposal = budget.fit_proposal(profile("250"), [exp("a", 35.0)])
    assert proposal["remove"] == [] and proposal["within_budget"] is True


def test_to_eur_is_unchanged():
    fx = {"rate": 1.2, "from": "GBP", "to": "EUR", "date": "2026-11-17", "source": None}
    assert budget.to_eur(20.0, "GBP", fx) == 24.0
    assert budget.to_eur(None, "GBP", fx) is None
