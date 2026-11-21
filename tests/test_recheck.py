# backend/recheck.py: the code verifies facts from our API tools by fetching the same record again (Viator product
# details and schedule, the stored Geoapify URL with our key) and comparing price, currency, per, label, rating, review
# count, hours, coordinates and wheelchair access. Match: confirmed; a difference: contradicted with the fields; no
# answer or nothing comparable: not_sure. All HTTP is mocked (tests/fake_apis.py); prices are fixed test examples.
import json

import pytest

from backend import recheck
from backend.sources import geoapify
from tests import fake_apis as fa
from tests.factories import checked, profile
from tests.fake_apis import FakeAPIs

URL = fa.product_url("111P1")
VIATOR = {"provider": "viator", "url": URL, "retrieved_at": "2026-11-21T00:36:05+01:00", "quote": None}
GEOCODE_URL = geoapify.public_url(geoapify.GEOCODE_URL, {"text": "Praça do Comércio, Lisbon", "format": "json",
                                                          "limit": 1})
DETAILS_URL = geoapify.public_url(geoapify.DETAILS_URL, {"id": "51abc"})
GEOCODE = {"provider": "geoapify", "url": GEOCODE_URL, "retrieved_at": "2026-11-21T00:36:15+01:00", "quote": None}
DETAILS = {"provider": "geoapify", "url": DETAILS_URL, "retrieved_at": "2026-11-21T00:36:15+01:00", "quote": None}
WEB = {"provider": "web", "url": "https://www.carris.pt/tram-28", "retrieved_at": "2026-11-21T00:37:00+01:00",
       "quote": "Tram 28 departs every 15 minutes from 07:00."}
START_TIMES = "Start times on 2026-12-04 to 2026-12-06: 10:00, 14:00"      # fa.schedule() on the profile's dates


def tour(id="alfama-walk", **over):
    """A Viator tour as search_viator gives it, located with find_place (geocode search)."""
    fields = dict(
        price={"amount": 35.0, "currency": "EUR", "per": "person", "label": None, "source": VIATOR},
        rating={"value": 4.8, "scale": 5, "review_count": 120, "source": VIATOR},
        opening_hours={"text": START_TIMES, "slots": ["10:00", "14:00"], "source": VIATOR},
        location={"lat": 38.70775, "lng": -9.13618, "source": GEOCODE},
        accessibility={"wheelchair": "unknown", "notes": None, "source": None},
        booking_url=URL)
    fields.update(over)
    return checked(id, **fields)


def museum(**over):
    """A place found with find_place: coordinates from the geocode search, hours and wheelchair from place details."""
    fields = dict(
        price={"amount": 10.0, "currency": "EUR", "per": "person", "label": "Adult", "source": WEB},
        opening_hours={"text": "Tu-Su 10:00-18:00", "slots": [], "source": DETAILS},
        location={"lat": 38.70775, "lng": -9.13618, "source": GEOCODE},
        accessibility={"wheelchair": "yes", "notes": None, "source": DETAILS})
    fields.update(over)
    return checked("tile-museum", **fields)


def apis(*, details=None, schedule=None, geo=None, det=None):
    a = FakeAPIs()
    d = details or fa.details("111P1")
    d.setdefault("reviews", {"totalReviews": 120, "combinedAverageRating": 4.8})
    fa.viator_routes(a, [(fa.summary("111P1", "Alfama walk"), d, schedule or fa.schedule("111P1"))])
    fa.geo_routes(a, geo=geo, det=det)
    return a


def verdict(e, fake=None):
    fake = fake or apis()
    with fake.client() as c:
        return recheck.verdict(profile(), e, client=c), fake


# --- a match is confirmed -------------------------------------------------------------------------------------------

def test_viator_and_geoapify_facts_that_match_are_confirmed():
    v, fake = verdict(tour())
    assert v["id"] == "alfama-walk" and v["verdict"] == "confirmed" and v["contested_fields"] == []
    assert v["url_read"] == URL and v["passage"] == ""
    assert "Checked by the code" in v["note"] and "match" in v["note"]
    assert len(fake.sent("/products/111P1")) == 1 and len(fake.sent("/availability/schedules/111P1")) == 1
    [geo] = fake.sent("/v1/geocode/search")                       # the stored URL, asked again with our key
    assert geo.url.params["text"] == "Praça do Comércio, Lisbon" and geo.url.params["apiKey"] == fa.GEO_KEY
    assert not any(key in json.dumps(v) for key in fa.ALL_KEYS)


def test_place_details_hours_and_wheelchair_that_match_are_confirmed():
    v, fake = verdict(museum(price={"source": None, "amount": None}))
    assert v["verdict"] == "confirmed", v["note"]
    assert len(fake.sent("/v2/place-details")) == 1               # hours and wheelchair: one answer
    assert fake.sent("/v2/place-details")[0].url.params["id"] == "51abc"


# --- a difference is contradicted, with the fields ------------------------------------------------------------------

@pytest.mark.parametrize("over, field, detail", [
    ({"price": {"amount": 30.0}}, "price.amount", "price.amount: record 30.0, Viator 35.0"),
    ({"price": {"per": "group"}}, "price.per", 'price.per: record "group", Viator "person"'),
    ({"price": {"label": "Adult (18–99)"}}, "price.label", 'price.label: record "Adult (18–99)", Viator null'),
    ({"rating": {"value": 4.5}}, "rating.value", "rating.value: record 4.5, Viator 4.8"),
    ({"rating": {"review_count": 100}}, "rating.review_count", "rating.review_count: record 100, Viator 120"),
    ({"opening_hours": {"text": "Start times on 2026-12-04 to 2026-12-06: 09:00", "slots": ["09:00"],
                        "source": VIATOR}}, "opening_hours", "opening_hours: record"),
    ({"location": {"lat": 38.8}}, "location", "location: record [38.8, -9.13618], Geoapify [38.70775, -9.13618]"),
])
def test_a_difference_from_the_api_is_contradicted_with_its_field(over, field, detail):
    e = tour()
    for key, value in over.items():
        e[key] = value if key == "opening_hours" else {**e[key], **value}
    v, _ = verdict(e)
    assert v["verdict"] == "contradicted" and v["contested_fields"] == [field]
    assert detail in v["note"]


def reviews(value, count):
    d = fa.details("111P1")
    d["reviews"] = {"totalReviews": count, "combinedAverageRating": value}
    return apis(details=d)


@pytest.mark.parametrize("value, count", [
    (4.9, 120),          # +0.1 star
    (4.7, 120),          # -0.1 star
    (4.8, 126),          # +5% reviews (120 -> 126)
    (4.85, 123),         # both a little
])
def test_a_rating_within_a_tenth_and_up_to_5_percent_more_reviews_is_confirmed(value, count):
    v, _ = verdict(tour(), reviews(value, count))                   # the record: 4.8 from 120 reviews
    assert v["verdict"] == "confirmed" and v["contested_fields"] == [], v["note"]
    assert "rating match" in v["note"] or "price, rating" in v["note"]
    if (value, count) != (4.8, 120):
        assert "within tolerance" in v["note"]


@pytest.mark.parametrize("value, count, field", [
    (4.95, 120, "rating.value"),        # +0.15 star
    (4.65, 120, "rating.value"),        # -0.15 star
    (4.8, 127, "rating.review_count"),  # +5.8% reviews
    (4.8, 119, "rating.review_count"),  # fewer reviews than the record
])
def test_a_rating_further_off_is_contradicted(value, count, field):
    v, _ = verdict(tour(), reviews(value, count))
    assert v["verdict"] == "contradicted" and v["contested_fields"] == [field]


def test_a_price_in_another_currency_than_viators_schedule_is_not_compared():
    sch = fa.schedule("111P1")
    v, _ = verdict(tour(price={"amount": 35.0, "currency": "GBP", "per": "person", "label": None, "source": VIATOR}),
                   apis(schedule=sch))
    assert v["verdict"] == "not_sure"                             # the schedule prices it in EUR: not comparable
    assert "price not compared" in v["note"] and "EUR" in v["note"]


def test_place_details_differences_are_contradicted():
    v, _ = verdict(museum(), apis(det=fa.place_details(opening_hours="Tu-Su 10:00-17:00", wheelchair="limited")))
    assert v["verdict"] == "contradicted"
    assert v["contested_fields"] == ["opening_hours", "accessibility.wheelchair"]
    assert 'accessibility.wheelchair: record "yes", Geoapify "limited"' in v["note"]


def test_a_contradiction_wins_over_a_field_that_could_not_be_compared():
    v, _ = verdict(tour(price={"amount": 35.0, "currency": "GBP", "per": "person", "label": None, "source": VIATOR},
                        rating={"value": 4.8, "scale": 5, "review_count": 99, "source": VIATOR}))
    assert v["verdict"] == "contradicted" and v["contested_fields"] == ["rating.review_count"]
    assert "price not compared" in v["note"]


# --- nothing to compare is not_sure, never contradicted ---------------------------------------------------------------

def test_viator_not_answering_is_not_sure():
    fake = apis().add("GET", fa.VIATOR_PROD + "/partner/products/111P1", (500, {"message": "boom"}))
    v, _ = verdict(tour(), fake)
    assert v["verdict"] == "not_sure" and v["contested_fields"] == []
    assert "Viator did not answer" in v["note"] and "500" in v["note"]


def test_a_refused_key_is_not_sure_and_never_shows_the_key():
    fake = apis().add("GET", fa.VIATOR_PROD + "/partner/products/111P1", (401, {"message": "Invalid API Key"}))
    v, _ = verdict(tour(), fake)
    assert v["verdict"] == "not_sure"
    assert not any(key in json.dumps(v) for key in fa.ALL_KEYS)


def test_a_viator_link_without_a_product_code_is_not_sure_and_not_fetched():
    src = {**VIATOR, "url": "https://www.viator.com/tours/Lisbon/x"}
    v, fake = verdict(tour(price={"source": src}, rating={"source": src},
                           opening_hours={"text": START_TIMES, "slots": ["10:00", "14:00"], "source": src}))
    assert v["verdict"] == "not_sure" and "no Viator product code" in v["note"]
    assert fake.sent("/products/111P1") == [] and fake.sent("/availability/schedules/111P1") == []


def test_an_inactive_viator_product_is_not_sure():
    d = fa.details("111P1")
    d["status"] = "INACTIVE"
    v, _ = verdict(tour(), apis(details=d))
    assert v["verdict"] == "not_sure" and "INACTIVE" in v["note"]


def test_a_geoapify_answer_without_a_result_is_not_sure():
    v, _ = verdict(tour(), apis(geo={"results": []}))
    assert v["verdict"] == "not_sure" and "location not compared" in v["note"]


def test_a_geoapify_url_the_code_cannot_ask_again_is_not_sure():
    places = {**GEOCODE, "url": "https://api.geoapify.com/v2/places?categories=leisure.park"}
    v, fake = verdict(museum(location={"lat": 38.70775, "lng": -9.13618, "source": places},
                             opening_hours=None, accessibility={"wheelchair": "unknown", "notes": None,
                                                                "source": None}))
    assert v["verdict"] == "not_sure" and fake.sent("/v2/places") == []


def test_an_item_without_viator_or_geoapify_facts_has_no_code_verdict():
    e = museum(opening_hours={"text": "Tu-Su 10:00-18:00", "slots": [], "source": WEB},
               location={"lat": 38.70775, "lng": -9.13618, "source": WEB},
               accessibility={"wheelchair": "yes", "notes": None, "source": WEB})
    v, fake = verdict(e)
    assert v is None and fake.requests == []


# --- web facts: what the verifier agent gets, and one verdict per item ------------------------------------------------

def test_web_facts_keep_only_the_fields_from_web_pages():
    e = museum()
    assert recheck.has_web_facts(e) and not recheck.has_web_facts(tour())
    web = recheck.web_only(e)
    assert web["price"]["source"] == WEB
    assert not {"location", "opening_hours", "accessibility"} & set(web)
    assert web["name"] == e["name"] and web["id"] == e["id"]
    assert e["location"]["source"] == GEOCODE                       # the item itself is not changed


def part(verdict, fields=(), note="n", url="u", passage=""):
    return {"id": "x", "verdict": verdict, "url_read": url, "passage": passage, "contested_fields": list(fields),
            "note": note}


@pytest.mark.parametrize("verdicts, expected", [
    (["confirmed", "confirmed"], "confirmed"),
    (["confirmed", "not_sure"], "not_sure"),
    (["not_sure", "contradicted"], "contradicted"),
    (["confirmed"], "confirmed"),
])
def test_one_verdict_per_item_from_the_code_and_the_agent(verdicts, expected):
    assert recheck.combine("x", [part(v) for v in verdicts])["verdict"] == expected


def test_the_combined_verdict_keeps_the_pages_passage_and_every_contested_field():
    code = part("contradicted", ["price.amount"], note="Checked by the code: price differs.", url="https://viator")
    agent = part("contradicted", ["opening_hours"], note="The page says 09:00.", url="https://page",
                 passage="Open from 09:00.")
    v = recheck.combine("x", [code, agent])
    assert v["contested_fields"] == ["price.amount", "opening_hours"]
    assert v["url_read"] == "https://page" and v["passage"] == "Open from 09:00."
    assert v["note"] == "Checked by the code: price differs. The page says 09:00."


def test_an_item_with_nothing_to_check_is_not_sure():
    v = recheck.combine("x", [])
    assert v["verdict"] == "not_sure" and v["note"] == "No fact with a source to check."
