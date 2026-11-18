# Frankfurter (no key): the daily reference rate to EUR for a price in another currency.
# The multiplication itself lives in backend/budget.py. Docs: https://frankfurter.dev/
from backend.sources.common import SourceError, fetch, public_url, source_block

PROVIDER = "frankfurter"
RATES_URL = "https://api.frankfurter.dev/v2/rates"

_cache = {}  # one rate per currency per run


def clear_cache():
    _cache.clear()


def eur_rate(currency, *, client=None):
    """fx block {rate, from, to, date, source} for currency -> EUR; None for EUR (nothing to convert)."""
    if currency == "EUR":
        return None
    if currency in _cache:
        return _cache[currency]
    params = {"base": currency, "quotes": "EUR"}
    data = fetch(PROVIDER, "GET", RATES_URL, summary=f"GET /v2/rates base={currency} quotes=EUR", client=client,
                 params=params, items=lambda d: [f"{currency}->EUR"])
    row = next((r for r in data if r.get("base") == currency and r.get("quote") == "EUR"), None) \
        if isinstance(data, list) else None
    if not row or not row.get("rate"):
        raise SourceError(f"frankfurter: no {currency}->EUR rate in the response")
    _cache[currency] = {"rate": row["rate"], "from": currency, "to": "EUR", "date": row.get("date"),
                        "source": source_block(PROVIDER, public_url(RATES_URL, params))}
    return _cache[currency]
