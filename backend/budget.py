# Sums itinerary costs and checks them against the budget in Python, never by the model.
from decimal import ROUND_HALF_UP, Decimal


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
