# Source tools (Viator, Geoapify, Frankfurter, Tavily): records carry a source block, every HTTP call is logged,
# keys never leak. All HTTP is mocked (tests/fake_apis.py); prices are fixed test examples.
import json
from datetime import datetime

import httpx
import pytest

from backend import budget
from backend.sources import common, fx, geoapify, tavily, viator
from tests import fake_apis as fa
from tests.fake_apis import FakeAPIs


def log_lines():
    if not common.LOG_PATH.exists():
        return []
    return [json.loads(line) for line in common.LOG_PATH.read_text().splitlines()]


def assert_source(block, provider, url):
    assert set(block) == {"provider", "url", "retrieved_at", "quote"}
    assert block["provider"] == provider
    assert block["url"] == url
    assert block["quote"] is None
    assert datetime.fromisoformat(block["retrieved_at"]).utcoffset() is not None


def lisbon_product(**kw):
    code = kw.pop("code", "111P1")
    return (fa.summary(code, "Alfama food walk", **kw.pop("summary", {})),
            fa.details(code, **kw.pop("details", {})),
            fa.schedule(code, **kw.pop("schedule", {})))


def search_one(apis, **kw):
    fa.viator_routes(apis, [lisbon_product(**kw)])
    with apis.client() as c:
        return viator.search_viator("Lisbon", ["food"], fa.DATES, client=c)


# ---------- Viator ----------

def test_viator_base_url_from_env_and_headers(monkeypatch):
    monkeypatch.setenv("VIATOR_ENV", "sandbox")
    apis = fa.viator_routes(FakeAPIs(), [], host=fa.VIATOR_SANDBOX)
    with apis.client() as c:
        dest = viator.find_destination("Lisbon", client=c)
    assert dest["destinationId"] == 538
    req = apis.requests[0]
    assert str(req.url) == "https://api.sandbox.viator.com/partner/destinations"
    assert req.headers["exp-api-key"] == fa.VIATOR_KEY
    assert req.headers["accept"] == "application/json;version=2.0"
    assert req.headers["accept-language"] == "en-US"


def test_viator_env_must_be_sandbox_or_production(monkeypatch):
    monkeypatch.setenv("VIATOR_ENV", "staging")
    with pytest.raises(common.SourceError, match="VIATOR_ENV"):
        viator.find_destination("Lisbon", client=FakeAPIs().client())


def test_missing_key_names_the_variable(monkeypatch):
    monkeypatch.delenv("VIATOR_API_KEY")
    with pytest.raises(common.SourceError, match="VIATOR_API_KEY"):
        viator.find_destination("Lisbon", client=FakeAPIs().client())


def test_ambiguous_city_raises_and_region_picks_one():
    apis = fa.viator_routes(FakeAPIs(), [])
    with apis.client() as c:
        with pytest.raises(common.SourceError) as err:
            viator.find_destination("London", client=c)
        assert "England" in str(err.value) and "Ontario" in str(err.value)
        assert viator.find_destination("London, England", client=c)["destinationId"] == 737


def test_search_request_body():
    apis = FakeAPIs()
    search_one(apis)
    body = FakeAPIs.body(apis.sent("/products/search")[0])
    assert body["filtering"] == {"destination": "538", "tags": [21911],
                                 "startDate": "2026-12-04", "endDate": "2026-12-06"}
    assert body["currency"] == "EUR"
    assert body["sorting"] == {"sort": "TRAVELER_RATING", "order": "DESCENDING"}
    assert body["pagination"] == {"start": 1, "count": 5}


def test_search_viator_record_fields_and_sources():
    [rec] = search_one(FakeAPIs())
    url = fa.product_url("111P1")
    assert rec["id"] == "viator-111p1"
    assert rec["name"] == "Alfama food walk"
    assert rec["category"] == "food"
    assert rec["tags"] == ["Food Tours", "Kid-Friendly"]
    assert rec["duration_min"] == 180
    assert rec["booking_url"] == url
    assert rec["photo_url"] == "https://img.example/cover-720.jpg"
    assert {k: rec["price"][k] for k in ("amount", "currency", "per", "amount_eur", "fx")} == \
        {"amount": 35.0, "currency": "EUR", "per": "person", "amount_eur": None, "fx": None}
    assert {k: rec["rating"][k] for k in ("value", "scale", "review_count")} == \
        {"value": 4.8, "scale": 5, "review_count": 120}
    assert rec["opening_hours"]["slots"] == ["10:00", "14:00"]
    assert "10:00, 14:00" in rec["opening_hours"]["text"]
    assert rec["accessibility"]["wheelchair"] == "yes"
    assert rec["accessibility"]["notes"] == "Wheelchair accessible"
    assert rec["suitable_for"] == {"values": ["family"], "kind": "fact"}
    assert rec["indoor_outdoor"] == "unknown"
    assert rec["months"] == []
    assert rec["min_age"] is None
    assert rec["meeting_point"] == {"name": "Praça do Comércio", "street": "Praça do Comércio",
                                    "lat": fa.MEETING["latitude"], "lng": fa.MEETING["longitude"]}
    for block in (rec["price"]["source"], rec["rating"]["source"], rec["opening_hours"]["source"],
                  rec["accessibility"]["source"]):
        assert_source(block, "viator", url)


def test_outdoor_tag_and_adventure_category():
    apis = FakeAPIs()
    fa.viator_routes(apis, [lisbon_product(code="222P2", summary={"tag_ids": (12001,)})])
    with apis.client() as c:
        [rec] = viator.search_viator("Lisbon", ["adventure"], fa.DATES, client=c)
    assert rec["category"] == "adventure"
    assert rec["indoor_outdoor"] == "outdoor"
    assert rec["suitable_for"] == {"values": [], "kind": "fact"}


def test_product_found_under_two_interests_is_kept_once_with_first_category():
    apis = FakeAPIs()
    fa.viator_routes(apis, [lisbon_product(summary={"tag_ids": (12000, 12001)})])
    with apis.client() as c:
        recs = viator.search_viator("Lisbon", ["adventure", "food"], fa.DATES, client=c)
    assert [r["category"] for r in recs] == ["adventure"]


def test_interest_without_a_matching_tag_is_reported_not_searched():
    apis = fa.viator_routes(FakeAPIs(), [])
    with apis.client() as c:
        mapping, unmatched = viator.interest_tags(viator.load_tags(client=c), ["food", "relax"])
    assert mapping["food"] == [(21911, "Food & Drink")]
    assert mapping["relax"] == []
    assert unmatched["relax"] == viator.INTEREST_TAG_NAMES["relax"]


def test_description_keeps_whole_sentences_within_300_chars():
    text = "First sentence here. " + "Second one is longer than the first. " + "Third. " * 5
    assert viator.short_description(text) == "First sentence here. Second one is longer than the first."
    long = "word " * 100 + "end."
    short = viator.short_description(long)
    assert len(short) <= 300 and short.endswith("…")
    assert long.startswith(short[:-1].rstrip())
    assert viator.short_description("  Line one.\n\nLine   two.  ") == "Line one. Line two."


def test_wheelchair_mapping():
    no = [{"type": "NOT_WHEELCHAIR_ACCESSIBLE", "description": "Not wheelchair accessible"}]
    [rec] = search_one(FakeAPIs(), details={"additional": no})
    assert rec["accessibility"]["wheelchair"] == "no"
    viator.clear_cache()
    [rec] = search_one(FakeAPIs(), details={"additional": [{"type": "STROLLER_ACCESSIBLE"}]})
    assert rec["accessibility"] == {"wheelchair": "unknown", "notes": None, "source": None}


def test_schedule_only_counts_trip_dates():
    # 2026-12-04..06 is Friday..Sunday: a Monday-only tour has no start time on the trip.
    [rec] = search_one(FakeAPIs(), schedule={"days": ["MONDAY"]})
    assert rec["opening_hours"] is None
    viator.clear_cache()
    [rec] = search_one(FakeAPIs(), schedule={"season": ("2027-01-01", "2027-12-31")})
    assert rec["opening_hours"] is None


def test_schedule_unavailable_dates_and_operating_hours():
    dates = (fa.DATES[0], fa.DATES[0])
    sch = fa.schedule("X", start_times=(), unavailable=["2026-12-05"],
                      operating=[{"dayOfWeek": "FRIDAY", "operatingHours": [{"opensAt": "09:00", "closesAt": "18:00"}]}])
    hours = viator.hours_from_schedule(sch, dates, {"provider": "viator"})
    assert hours["slots"] == []
    assert "2026-12-04 09:00–18:00" in hours["text"]
    sch = fa.schedule("X", unavailable=["2026-12-04"])
    assert viator.hours_from_schedule(sch, dates, {}) is None


def test_months_from_schedule_seasons():
    summer = fa.schedule("X", season=("2027-06-01", "2027-09-30"))
    assert viator.months_from_schedule(summer, "2026-12-04") == [6, 7, 8, 9]
    assert viator.months_from_schedule(fa.schedule("X"), "2026-12-04") == []


def test_unit_pricing_and_variable_duration_are_noted():
    [rec] = search_one(FakeAPIs(), details={"pricing_type": "UNIT"},
                       summary={"duration": {"variableDurationFromMinutes": 120, "variableDurationToMinutes": 240}})
    assert rec["price"]["per"] == "group"
    assert rec["duration_min"] == 120
    assert any("per group" in n for n in rec["notes"])
    assert any("120–240" in n for n in rec["notes"])


# Viator's age bands and schedule prices, as production returned them on 19 Nov 2026 (amounts are test examples).
def band(name, start, end, **more):
    return {"ageBand": name, "startAge": start, "endAge": end, **more}


def tier(name, amount, low=0, high=9, package="PER_PERSON"):
    return {"pricingPackageType": package, "minTravelers": low, "maxTravelers": high, "ageBand": name,
            "price": {"original": {"recommendedRetailPrice": amount, "partnerNetPrice": amount * 0.8}}}


def priced(*, from_price=35.0, bands=None, tiers=(), pricing_type="PER_PERSON", unit_type=None, currency="EUR"):
    """One Lisbon product whose schedule lists these prices; the search's from-price is `from_price`."""
    code = "111P1"
    d = fa.details(code, pricing_type=pricing_type)
    d["pricingInfo"]["ageBands"] = bands or [band("ADULT", 18, 99)]
    if unit_type:
        d["pricingInfo"]["unitType"] = unit_type
    sch = fa.schedule(code)
    sch["currency"] = currency
    sch["bookableItems"][0]["seasons"][0]["pricingRecords"][0]["pricingDetails"] = list(tiers)
    apis = fa.viator_routes(FakeAPIs(), [(fa.summary(code, "Castle ticket", price=from_price), d, sch)])
    with apis.client() as c:
        [rec] = viator.search_viator("Lisbon", ["food"], fa.DATES, client=c)
    return rec


def test_label_names_the_age_band_the_from_price_is_for():
    rec = priced(bands=[band("CHILD", 3, 10), band("ADULT", 18, 65), band("SENIOR", 66, 100)],
                 tiers=[tier("ADULT", 35.0), tier("CHILD", 17.5), tier("SENIOR", 35.0)])
    assert rec["price"]["label"] == "Adult (18–65)"
    assert rec["price"]["per"] == "person" and rec["price"]["amount"] == 35.0


def test_label_says_when_the_from_price_is_for_a_group_booking_together():
    rec = priced(tiers=[tier("ADULT", 70.0, 1, 1), tier("ADULT", 35.0, 2, 2), tier("ADULT", 30.0, 3, 8)])
    assert rec["price"]["label"] == "Adult (18–99), when 2 book together"
    rec = priced(tiers=[tier("ADULT", 35.0, 2, 4)])
    assert rec["price"]["label"] == "Adult (18–99), when 2–4 book together"


def test_label_of_a_one_price_for_everyone_product_says_only_the_group():
    rec = priced(bands=[band("TRAVELER", 0, 120)], tiers=[tier("TRAVELER", 35.0)])
    assert rec["price"]["label"] is None
    rec = priced(bands=[band("TRAVELER", 0, 120)], tiers=[tier("TRAVELER", 35.0, 2, 2)])
    assert rec["price"]["label"] == "When 2 book together"


@pytest.mark.parametrize("kw", [
    {"tiers": [tier("ADULT", 40.0)]},                                         # no schedule price is the from-price
    {"tiers": [tier("ADULT", 35.0)], "currency": "GBP"},                       # schedule in another currency
    {"tiers": []},                                                           # no prices in the schedule
    {"bands": [band("YOUTH", 11, 17), band("SENIOR", 66, 99)],
     "tiers": [tier("YOUTH", 35.0), tier("SENIOR", 35.0)]},                   # two bands, neither adult: can't say
])
def test_label_is_null_when_viator_does_not_say_which_price_it_is(kw):
    assert priced(**kw)["price"]["label"] is None


def test_a_unit_price_is_for_the_whole_group():
    rec = priced(from_price=360.0, pricing_type="UNIT", unit_type="VEHICLE",
                 bands=[band("TRAVELER", 0, 120, maxTravelersPerBooking=4)],
                 tiers=[tier("TRAVELER", 360.0, package="UNIT")])
    assert rec["price"]["per"] == "group" and rec["price"]["amount"] == 360.0
    assert rec["price"]["label"] is None
    assert "Viator prices this per group (vehicle), not per person: up to 4 travellers per booking" in rec["notes"]


def test_meeting_point_missing_when_pickup_only_or_google_ref():
    [rec] = search_one(FakeAPIs(), details={"start_ref": None})
    assert rec["meeting_point"] is None
    viator.clear_cache()
    apis = FakeAPIs()
    fa.viator_routes(apis, [lisbon_product(details={"start_ref": "LOC-ggg"})],
                     locs={"LOC-ggg": {"provider": "GOOGLE", "providerReference": "ChIJ123"}})
    with apis.client() as c:
        [rec] = viator.search_viator("Lisbon", ["food"], fa.DATES, client=c)
    assert rec["meeting_point"] is None


def test_no_reviews_means_no_rating():
    [rec] = search_one(FakeAPIs(), summary={"reviews": None})
    assert rec["rating"] is None


def test_viator_401_raises_auth_error_and_logs_without_key():
    apis = FakeAPIs().add("GET", fa.VIATOR_PROD + "/partner/destinations",
                          (401, {"code": "UNAUTHORIZED", "message": "Invalid API Key"}))
    with pytest.raises(common.SourceAuthError) as err:
        viator.find_destination("Lisbon", client=apis.client())
    assert "viator" in str(err.value) and "401" in str(err.value)
    assert fa.VIATOR_KEY not in str(err.value)
    [line] = log_lines()
    assert line["provider"] == "viator" and line["status"] == 401


def test_viator_403_is_an_auth_error_too():
    apis = FakeAPIs().add("GET", fa.VIATOR_PROD + "/partner/destinations", (403, {"code": "FORBIDDEN"}))
    with pytest.raises(common.SourceAuthError):
        viator.find_destination("Lisbon", client=apis.client())


def test_viator_logs_one_line_per_call():
    search_one(FakeAPIs())
    lines = log_lines()
    requests = [l["request"] for l in lines]
    assert requests == [
        "GET /destinations",
        "GET /products/tags",
        "POST /products/search destination=538 tags=21911 2026-12-04..2026-12-06 currency=EUR",
        "GET /products/111P1",
        "GET /availability/schedules/111P1",
        "POST /locations/bulk refs=1",
    ]
    assert lines[2]["items"] == ["viator-111p1"]
    for l in lines:
        assert set(l) == {"at", "provider", "request", "status", "items"}
        assert l["provider"] == "viator" and l["status"] == 200


def test_tags_and_destinations_are_fetched_once_per_run():
    apis = FakeAPIs()
    fa.viator_routes(apis, [lisbon_product()])
    with apis.client() as c:
        viator.find_destination("Lisbon", client=c)
        viator.search_viator("Lisbon", ["food"], fa.DATES, client=c)
    assert len(apis.sent("/destinations")) == 1
    assert len(apis.sent("/products/tags")) == 1


# ---------- Geoapify ----------

def test_find_place_confident_match():
    apis = fa.geo_routes(FakeAPIs())
    with apis.client() as c:
        place = geoapify.find_place("Praça do Comércio", "Lisbon", near=(38.7223, -9.1393), client=c)
    assert (place["lat"], place["lng"]) == (38.70775, -9.13618)
    assert place["address"] == "Praça do Comércio, 1100-148 Lisbon, Portugal"
    assert place["timezone"] == "Europe/Lisbon"
    assert place["opening_hours"]["text"] == "Tu-Su 10:00-18:00"
    assert place["opening_hours"]["slots"] == []
    assert place["accessibility"]["wheelchair"] == "yes"
    assert place["matched_name"] == "Praça do Comércio"
    geo_req, det_req = apis.requests
    assert geo_req.url.params["apiKey"] == fa.GEO_KEY
    assert geo_req.url.params["text"] == "Praça do Comércio, Lisbon"
    assert geo_req.url.params["format"] == "json"
    assert geo_req.url.params["filter"] == "circle:-9.1393,38.7223,30000"
    assert geo_req.url.params["bias"] == "proximity:-9.1393,38.7223"
    assert det_req.url.params["id"] == "51abc"
    for block in (place["source"], place["opening_hours"]["source"], place["accessibility"]["source"]):
        assert block["provider"] == "geoapify" and block["quote"] is None
        assert "apiKey" not in block["url"] and fa.GEO_KEY not in block["url"]
    assert place["source"]["url"].startswith("https://api.geoapify.com/v1/geocode/search?")
    assert place["opening_hours"]["source"]["url"] == "https://api.geoapify.com/v2/place-details?id=51abc"


def test_find_place_accepts_a_full_match_with_zero_confidence():
    # Live Geoapify gives confidence 0 to correct named places (e.g. Tower of Belém, 18 Nov 2026).
    apis = fa.geo_routes(FakeAPIs(), geo=fa.geocode(confidence=0))
    with apis.client() as c:
        assert geoapify.find_place("Praça do Comércio", "Lisbon", client=c) is not None


@pytest.mark.parametrize("geo", [fa.geocode(result_type="city"), fa.geocode(confidence=0.5, match_type="inner_part"),
                                 {"results": []}])
def test_find_place_rejects_vague_matches(geo):
    apis = fa.geo_routes(FakeAPIs(), geo=geo)
    with apis.client() as c:
        assert geoapify.find_place("Somewhere", "Lisbon", client=c) is None
    assert len(apis.requests) == 1  # no place-details call
    assert len(log_lines()) == 1


@pytest.mark.parametrize("osm, expected", [("yes", "yes"), ("designated", "yes"), ("limited", "limited"),
                                           ("no", "no"), (None, "unknown")])
def test_find_place_wheelchair_from_osm(osm, expected):
    apis = fa.geo_routes(FakeAPIs(), det=fa.place_details(wheelchair=osm, opening_hours=None))
    with apis.client() as c:
        place = geoapify.find_place("Praça do Comércio", "Lisbon", client=c)
    assert place["accessibility"]["wheelchair"] == expected
    assert place["opening_hours"] is None
    if expected == "unknown":
        assert place["accessibility"]["source"] is None


def test_reverse_place_at_viator_coordinates():
    apis = fa.geo_routes(FakeAPIs())
    with apis.client() as c:
        place = geoapify.reverse_place(38.7077, -9.1365, client=c)
    [req] = apis.requests
    assert req.url.path == "/v1/geocode/reverse"
    assert (req.url.params["lat"], req.url.params["lon"]) == ("38.7077", "-9.1365")
    assert req.url.params["format"] == "json" and req.url.params["apiKey"] == fa.GEO_KEY
    assert place["address"] == "Praça do Comércio, 1100-148 Lisbon, Portugal"
    assert (place["lat"], place["lng"]) == (38.70775, -9.13618)
    assert place["timezone"] == "Europe/Lisbon"
    assert place["distance_m"] == 5.1
    assert place["source"]["provider"] == "geoapify"
    assert place["source"]["url"] == "https://api.geoapify.com/v1/geocode/reverse?lat=38.7077&lon=-9.1365&format=json&limit=1"
    [line] = log_lines()
    assert line["request"] == "GET /v1/geocode/reverse lat=38.7077 lon=-9.1365"


def test_reverse_place_without_result_is_none():
    apis = fa.geo_routes(FakeAPIs(), rev={"results": []})
    with apis.client() as c:
        assert geoapify.reverse_place(0.0, 0.0, client=c) is None


def test_geoapify_401_raises_without_key():
    apis = FakeAPIs().add("GET", fa.GEO + "/v1/geocode/search", (401, {"message": "Invalid apiKey"}))
    with pytest.raises(common.SourceAuthError) as err:
        geoapify.find_place("X", "Lisbon", client=apis.client())
    assert fa.GEO_KEY not in str(err.value)
    assert fa.GEO_KEY not in common.LOG_PATH.read_text()


# ---------- Frankfurter + budget ----------

def test_eur_needs_no_call():
    apis = FakeAPIs()
    assert fx.eur_rate("EUR", client=apis.client()) is None
    assert apis.requests == [] and log_lines() == []
    assert budget.to_eur(35.0, "EUR", None) == 35.0


def test_gbp_rate_from_frankfurter_and_conversion():
    apis = fa.fx_routes(FakeAPIs())
    with apis.client() as c:
        rate = fx.eur_rate("GBP", client=c)
        assert fx.eur_rate("GBP", client=c) is rate  # cached: one call per run
    assert len(apis.requests) == 1
    req = apis.requests[0]
    assert req.url.params["base"] == "GBP" and req.url.params["quotes"] == "EUR"
    assert {k: rate[k] for k in ("rate", "from", "to", "date")} == \
        {"rate": 1.1998, "from": "GBP", "to": "EUR", "date": "2026-11-18"}
    assert_source(rate["source"], "frankfurter", "https://api.frankfurter.dev/v2/rates?base=GBP&quotes=EUR")
    assert budget.to_eur(20.0, "GBP", rate) == 24.0     # 23.996 rounds to 24.00
    assert budget.to_eur(19.5, "GBP", rate) == 23.4     # 23.3961
    assert budget.to_eur(None, "GBP", rate) is None
    [line] = log_lines()
    assert line["provider"] == "frankfurter" and line["items"] == ["GBP->EUR"]


def test_to_eur_refuses_a_rate_for_another_currency():
    with pytest.raises(ValueError):
        budget.to_eur(10.0, "USD", {"rate": 1.2, "from": "GBP", "to": "EUR"})
    with pytest.raises(ValueError):
        budget.to_eur(10.0, "GBP", None)


# ---------- Tavily ----------

def test_web_search_results_and_request():
    apis = fa.tavily_routes(FakeAPIs())
    with apis.client() as c:
        results = tavily.web_search("Lisbon tram 28 timetable", client=c)
    req = apis.requests[0]
    assert req.headers["authorization"] == "Bearer " + fa.TAVILY_KEY
    body = FakeAPIs.body(req)
    assert body == {"query": "Lisbon tram 28 timetable", "search_depth": "basic", "max_results": 5}
    assert [r["url"] for r in results] == ["https://www.carris.pt/tram-28", "https://blog.example/tram"]
    assert results[0]["title"] == "Tram 28" and results[0]["snippet"] == "Tram 28 runs daily."
    assert_source(results[0]["source"], "tavily", "https://www.carris.pt/tram-28")
    [line] = log_lines()
    assert line["items"] == ["https://www.carris.pt/tram-28", "https://blog.example/tram"]


def test_read_page_text_and_failed_page():
    apis = fa.tavily_routes(FakeAPIs())
    with apis.client() as c:
        page = tavily.read_page("https://www.carris.pt/tram-28", client=c)
    assert page["text"] == "Tram 28 departs every 15 minutes from 07:00."
    assert_source(page["source"], "web", "https://www.carris.pt/tram-28")
    assert FakeAPIs.body(apis.requests[0]) == {"urls": ["https://www.carris.pt/tram-28"],
                                               "extract_depth": "basic", "format": "text"}
    apis.add("POST", fa.TAVILY + "/extract",
             {"results": [], "failed_results": [{"url": "https://x.example", "error": "timeout"}]})
    with apis.client() as c:
        assert tavily.read_page("https://x.example", client=c) is None
    assert len(log_lines()) == 2


def test_tavily_401_raises_without_key():
    apis = FakeAPIs().add("POST", fa.TAVILY + "/search", (401, {"detail": {"error": "Unauthorized"}}))
    with pytest.raises(common.SourceAuthError) as err:
        tavily.web_search("x", client=apis.client())
    assert fa.TAVILY_KEY not in str(err.value)


# ---------- Common: errors, retries, no leaks ----------

def test_network_error_becomes_source_error_without_url_or_key():
    def boom(request):
        raise httpx.ConnectError("connection failed for " + str(request.url), request=request)

    client = httpx.Client(transport=httpx.MockTransport(boom))
    with pytest.raises(common.SourceError) as err:
        geoapify.find_place("X", "Lisbon", client=client)
    assert fa.GEO_KEY not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__
    [line] = log_lines()
    assert line["status"] == "error: ConnectError"


def test_other_http_errors_raise_source_error():
    apis = FakeAPIs().add("GET", fa.VIATOR_PROD + "/partner/destinations", (500, {"message": "boom"}))
    with pytest.raises(common.SourceError) as err:
        viator.find_destination("Lisbon", client=apis.client())
    assert not isinstance(err.value, common.SourceAuthError)
    assert "500" in str(err.value)


def test_429_is_retried_once_after_retry_after(monkeypatch):
    waits = []
    monkeypatch.setattr(common.time, "sleep", waits.append)
    calls = iter([httpx.Response(429, headers={"Retry-After": "3"}), None])

    def dest(request):
        r = next(calls)
        return r if r is not None else fa.destinations()

    apis = FakeAPIs().add("GET", fa.VIATOR_PROD + "/partner/destinations", dest)
    assert viator.find_destination("Lisbon", client=apis.client())["destinationId"] == 538
    assert waits == [3]
    assert [l["status"] for l in log_lines()] == [429, 200]


def test_no_key_ever_reaches_the_log():
    apis = FakeAPIs()
    fa.viator_routes(apis, [lisbon_product()])
    fa.geo_routes(apis)
    fa.fx_routes(apis)
    fa.tavily_routes(apis)
    with apis.client() as c:
        viator.search_viator("Lisbon", ["food"], fa.DATES, client=c)
        geoapify.find_place("Praça do Comércio", "Lisbon", client=c)
        fx.eur_rate("GBP", client=c)
        tavily.web_search("q", client=c)
        tavily.read_page("https://www.carris.pt/tram-28", client=c)
    text = common.LOG_PATH.read_text()
    assert len(text.splitlines()) == 11
    for key in fa.ALL_KEYS:
        assert key not in text
    assert "apiKey" not in text and "exp-api-key" not in text
