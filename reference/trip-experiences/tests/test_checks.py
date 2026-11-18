"""The code checks: schema, season, age, arithmetic, quote on the page, the five picks."""
import json
from pathlib import Path

from backend import checks

DEMO = json.loads((Path(__file__).parent.parent / "data" / "demo_research.json").read_text())
PROFILE = {"destination": "Seychelles", "start": "2027-04-10", "end": "2027-04-20", "budget": 1500, "currency": "EUR",
           "travellers": [{"name": "Parent 1", "age": 50}, {"name": "Parent 2", "age": 48}, {"name": "Teen", "age": 15}]}
BY_ID = {e["id"]: e for e in DEMO["experiences"]}


def result(e, name, page=None):
    return next(c["result"] for c in checks.check(PROFILE, e, page) if c["name"] == name)


def test_demo_delivery_passes_the_schema():
    assert checks.delivery_errors({"experiences": DEMO["experiences"]}) == []


def test_schema_refuses_a_missing_source_and_a_short_list():
    bad = json.loads(json.dumps(DEMO["experiences"][:9]))
    bad[0]["sources"] = []
    errors = checks.delivery_errors({"experiences": bad})
    assert any("at least 10" in e for e in errors) and any("sources" in e for e in errors)


def test_trip_months_cross_the_year():
    assert checks.trip_months({"start": "2026-12-20", "end": "2027-01-05"}) == [12, 1]


def test_season_age_and_price():
    assert result(BY_ID["whale-shark-snorkel"], "season") == "warn"      # Aug-Nov, trip in April
    assert result(BY_ID["discover-scuba"], "age") == "fail"              # the teen is 15, minimum 16
    assert result(BY_ID["bird-island"], "price") == "fail"               # 650 x 3 = 1950 > 1500
    assert result(BY_ID["sunset-catamaran"], "price") == "warn"          # USD in a EUR budget
    assert checks.group_cost(PROFILE, BY_ID["sainte-anne-snorkel"]) == 270  # 90 x 3, computed by code


def test_quote_must_be_on_the_page():
    e = BY_ID["vallee-de-mai"]
    page = checks._norm("Intro. " + e["sources"][0]["quote"] + " More text.")
    assert result(e, "source", page) == "ok"
    assert result(e, "source", checks._norm("another page")) == "warn"
    assert result(e, "source", "") == "warn"


def test_status_combines_checks_and_verdict():
    ok = [{"result": "ok"}]
    assert checks.status(ok, {"verdict": "confirmed"}) == "verified"
    assert checks.status(ok, {"verdict": "not_sure"}) == "to_check"
    assert checks.status(ok, None) == "to_check"
    assert checks.status(ok, {"verdict": "contradicted"}) == "rejected"
    assert checks.status([{"result": "fail"}], {"verdict": "confirmed"}) == "rejected"


def test_picks_need_five_and_the_budget():
    exps = [dict(e, status="verified", group_cost=checks.group_cost(PROFILE, e)) for e in DEMO["experiences"]]
    errors, _ = checks.picks(PROFILE, exps, ["vallee-de-mai"])
    assert errors and "exactly 5" in errors[0]
    five = ["vallee-de-mai", "anse-source-dargent", "sainte-anne-snorkel", "curieuse-tortoises", "botanical-garden"]
    errors, totals = checks.picks(PROFILE, exps, five)
    assert errors == [] and totals["picked_cost"] == 105 + 30 + 270 + 360 + 24 and totals["left"] == 711
    errors, _ = checks.picks(PROFILE, exps, five[:4] + ["bird-island"])
    assert any("budget" in e for e in errors)
