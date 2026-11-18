# All money arithmetic, in Python with Decimal, never by the model and never in the browser.
# Amounts leave this file as 2-place strings ("35.00"), so no float is ever stored or summed.
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def to_eur(amount, currency, fx):
    """A price in EUR, rounded to cents. EUR needs no fx; any other currency needs its fx block from sources/fx.py."""
    if amount is None:
        return None
    if currency == "EUR":
        return amount
    if not fx or fx.get("from") != currency or fx.get("to") != "EUR":
        raise ValueError(f"no {currency}->EUR rate for this price")
    eur = Decimal(str(amount)) * Decimal(str(fx["rate"]))
    return float(eur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def money(value):
    """Any amount (str, int, float, Decimal) as a Decimal rounded half-up to cents."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(amount):
    return str(money(amount))


def limit(profile):
    """The budget in its own unit: per person or total for the group, as the user chose."""
    return money(profile["budget"]["amount"])


def unit_cost(price, profile):
    """One item's cost in the budget's unit, or None when it can't be counted (no EUR price).
    Per-person budget: per-person price as is, a group price split over the group. Total budget: the group's cost."""
    if price["per"] == "free":
        return ZERO
    if price.get("amount_eur") is None:
        return None
    eur, size = money(price["amount_eur"]), profile["group_size"]
    if profile["budget"]["per"] == "person":
        return eur if price["per"] == "person" else money(eur / size)
    return money(eur * size) if price["per"] == "person" else eur


def item_cost(price, profile):
    cost = unit_cost(price, profile)
    return None if cost is None else fmt(cost)


def alone_over_budget(price, profile):
    cost = unit_cost(price, profile)
    return cost is not None and cost > limit(profile)


def counts(e):
    """Kept by the user and not rejected by the checks."""
    return e.get("status") != "rejected" and e["user"]["status"] == "kept"


def totals(profile, experiences):
    kept = [e for e in experiences if counts(e)]
    used, counted, not_counted = ZERO, [], []
    for e in kept:
        cost = unit_cost(e["price"], profile)
        if cost is None:
            not_counted.append(e["id"])
        else:
            used += cost
            counted.append(e["id"])
    budget = limit(profile)
    return {"per": profile["budget"]["per"], "group_size": profile["group_size"], "budget": fmt(budget),
            "used": fmt(used), "left": fmt(max(budget - used, ZERO)), "over_by": fmt(max(used - budget, ZERO)),
            "over": used > budget, "kept": len(kept), "counted": counted, "not_counted": not_counted}


def fit_proposal(profile, experiences):
    """Which kept items to remove to get within budget, last-added first (the list is best fit first).
    Items without a price or free ones are skipped: removing them saves nothing. Nothing is applied here."""
    kept = [e for e in experiences if counts(e)]
    costs = {e["id"]: unit_cost(e["price"], profile) for e in kept}
    used = sum((c for c in costs.values() if c is not None), ZERO)
    budget, remove = limit(profile), []
    for e in reversed(kept):
        if used <= budget:
            break
        if costs[e["id"]]:
            remove.append(e["id"])
            used -= costs[e["id"]]
    return {"remove": remove, "used_after": fmt(used), "budget": fmt(budget), "within_budget": used <= budget}
