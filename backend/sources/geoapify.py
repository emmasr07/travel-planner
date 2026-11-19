# Geoapify (OpenStreetMap data): coordinates, address and timezone for a named place, plus OSM opening hours and
# wheelchair access where OSM has them, and the brochure's static map image.
# Docs: https://apidocs.geoapify.com/  Attribution: Geoapify, © OpenStreetMap.
import httpx

from backend.sources.common import SourceError, env, fetch, public_url, source_block

PROVIDER = "geoapify"
STATIC_URL = "https://maps.geoapify.com/v1/staticmap"
STATIC_MAX_URL = 2048        # Geoapify's limit for a GET request
STATIC_TIMEOUT_S = 20        # the user waits for it when building the brochure; a new map took over 10 s once
GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
REVERSE_URL = "https://api.geoapify.com/v1/geocode/reverse"
DETAILS_URL = "https://api.geoapify.com/v2/place-details"
PLACES_URL = "https://api.geoapify.com/v2/places"
# A match this vague is an area, not the place: better no location than a wrong one.
VAGUE_TYPES = {"unknown", "suburb", "district", "postcode", "city", "county", "state", "country"}
# Geoapify gives confidence 0 to many correct named places, so a full match counts whatever its confidence.
# A name search can still match the wrong place: the record returns matched_name so the verifier can check.
MIN_CONFIDENCE = 0.7
NEAR_RADIUS_M = 30_000
OSM_WHEELCHAIR = {"yes": "yes", "designated": "yes", "limited": "limited", "no": "no"}
ENTRY_TAGS = ("male", "female", "lgbtq:men", "lgbtq:women")   # OSM tags that can say who may enter


def find_place(name, city, *, near=None, client=None):
    """Best match for `name` in `city`, or None. `near` = (lat, lng) of the city keeps results within 30 km."""
    params = {"text": f"{name}, {city}", "format": "json", "limit": 1}
    if near:
        params["filter"] = f"circle:{near[1]},{near[0]},{NEAR_RADIUS_M}"
        params["bias"] = f"proximity:{near[1]},{near[0]}"
    data = fetch(PROVIDER, "GET", GEOCODE_URL, summary=f"GET /v1/geocode/search text={params['text']!r}",
                 client=client, params={**params, "apiKey": env("GEOAPIFY_API_KEY")},
                 items=lambda d: [r.get("place_id") for r in d.get("results") or []])
    results = data.get("results") or []
    if not results:
        return None
    match = results[0]
    rank = match.get("rank") or {}
    if match.get("result_type") in VAGUE_TYPES or \
            (rank.get("match_type") != "full_match" and (rank.get("confidence") or 0) < MIN_CONFIDENCE):
        return None

    place_id = match["place_id"]
    details = fetch(PROVIDER, "GET", DETAILS_URL, summary=f"GET /v2/place-details id={place_id}", client=client,
                    params={"id": place_id, "apiKey": env("GEOAPIFY_API_KEY")}, items=lambda d: [place_id])
    props = _details_properties(details)
    raw = (props.get("datasource") or {}).get("raw") or {}
    details_url = public_url(DETAILS_URL, {"id": place_id})

    hours = props.get("opening_hours") or raw.get("opening_hours")
    wheelchair = _wheelchair(props, raw)
    return {
        "matched_name": match.get("name"),
        "lat": match["lat"],
        "lng": match["lon"],
        "address": match.get("formatted"),
        "timezone": (match.get("timezone") or {}).get("name"),
        "source": source_block(PROVIDER, public_url(GEOCODE_URL, params)),
        "opening_hours": {"text": hours, "slots": [], "source": source_block(PROVIDER, details_url)} if hours else None,
        "accessibility": {"wheelchair": wheelchair, "notes": None,
                          "source": source_block(PROVIDER, details_url) if wheelchair != "unknown" else None},
    }


def reverse_place(lat, lng, *, client=None):
    """Address, timezone and coordinates of the nearest mapped place to (lat, lng), or None.
    distance_m is how far that place is from the point asked for."""
    params = {"lat": lat, "lon": lng, "format": "json", "limit": 1}
    data = fetch(PROVIDER, "GET", REVERSE_URL, summary=f"GET /v1/geocode/reverse lat={lat} lon={lng}", client=client,
                 params={**params, "apiKey": env("GEOAPIFY_API_KEY")},
                 items=lambda d: [r.get("place_id") for r in d.get("results") or []])
    results = data.get("results") or []
    if not results:
        return None
    match = results[0]
    return {
        "matched_name": match.get("name"),
        "lat": match["lat"],
        "lng": match["lon"],
        "address": match.get("formatted"),
        "timezone": (match.get("timezone") or {}).get("name"),
        "distance_m": match.get("distance"),
        "source": source_block(PROVIDER, public_url(REVERSE_URL, params)),
    }


def find_city(name, *, client=None):
    """Geoapify's city for `name` ("London, England" works): {name, lat, lng, country_code, timezone, source}."""
    params = {"text": name, "type": "city", "format": "json", "limit": 1}
    data = fetch(PROVIDER, "GET", GEOCODE_URL, summary=f"GET /v1/geocode/search text={name!r} type=city",
                 client=client, params={**params, "apiKey": env("GEOAPIFY_API_KEY")},
                 items=lambda d: [r.get("place_id") for r in d.get("results") or []])
    results = data.get("results") or []
    if not results:
        return None
    match = results[0]
    return {
        "name": match.get("city") or match.get("name"),
        "lat": match["lat"],
        "lng": match["lon"],
        "country_code": match.get("country_code"),
        "timezone": (match.get("timezone") or {}).get("name"),
        "source": source_block(PROVIDER, public_url(GEOCODE_URL, params)),
    }


def osm_id(raw):
    """Record id from the OpenStreetMap object, e.g. 'osm-w663318739' (w = way, n = node, r = relation)."""
    return f"osm-{raw.get('osm_type')}{raw.get('osm_id')}" if raw.get("osm_type") and raw.get("osm_id") else None


def search_places(center, categories, *, radius_m=5000, limit=100, client=None):
    """OpenStreetMap places in any of `categories` within radius_m of center (lat, lng), nearest first.
    Places API responses carry no timezone: take it from find_city."""
    lat, lng = center
    params = {"categories": ",".join(categories), "filter": f"circle:{lng},{lat},{radius_m}",
              "bias": f"proximity:{lng},{lat}", "limit": limit}

    def ids(data):
        return [osm_id(((f.get("properties") or {}).get("datasource") or {}).get("raw") or {})
                for f in data.get("features") or []]

    data = fetch(PROVIDER, "GET", PLACES_URL, client=client, params={**params, "apiKey": env("GEOAPIFY_API_KEY")},
                 summary=f"GET /v2/places categories={params['categories']} circle={lng},{lat},{radius_m} limit={limit}",
                 items=ids)
    url = public_url(PLACES_URL, params)
    out = []
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        raw = (props.get("datasource") or {}).get("raw") or {}
        out.append({
            "id": osm_id(raw),
            "name": None if props.get("name") is None else str(props["name"]),   # OSM has names like 25
            "lat": props.get("lat"),
            "lng": props.get("lon"),
            "address": props.get("formatted"),
            "categories": props.get("categories") or [],
            "description": props.get("description") or raw.get("description"),
            "website": props.get("website") or raw.get("website") or raw.get("contact:website"),
            "opening_hours": props.get("opening_hours") or raw.get("opening_hours"),
            "wheelchair": _wheelchair(props, raw),
            "entry_tags": {k: raw[k] for k in ENTRY_TAGS if k in raw},
            "source": source_block(PROVIDER, url),
        })
    return out


def _details_properties(details):
    features = details.get("features") or []
    feature = next((f for f in features if (f.get("properties") or {}).get("feature_type") == "details"),
                   features[0] if features else {})
    return feature.get("properties") or {}


def _wheelchair(props, raw):
    # The OSM tag in datasource.raw is the source value; facilities.wheelchair is Geoapify's yes/no reading of it.
    if raw.get("wheelchair") in OSM_WHEELCHAIR:
        return OSM_WHEELCHAIR[raw["wheelchair"]]
    flag = (props.get("facilities") or {}).get("wheelchair")
    if flag is True:
        return "yes"
    if flag is False:
        return "no"
    return "unknown"


def static_map(points, *, width=600, height=600, client=None):
    """One PNG map of numbered markers, in the given order and colours; with no center or zoom the view fits them.
    points: [{lat, lng, text, color: "#rrggbb"}]. Returns {png, source}; the source URL carries no key.
    Credits: 1 + map tiles / 4 + 1 per marker. Too many markers for one GET URL raise SourceError, with no call."""
    markers = "|".join(f"lonlat:{p['lng']},{p['lat']};type:material;color:{p['color']};text:{p['text']};"
                       "contentcolor:#ffffff;whitecircle:no" for p in points)
    params = {"style": "osm-bright-grey", "width": width, "height": height, "scaleFactor": 2, "format": "png",
              "marker": markers}
    key = env("GEOAPIFY_API_KEY")
    if len(public_url(STATIC_URL, {**params, "apiKey": key})) > STATIC_MAX_URL:
        raise SourceError(f"{PROVIDER}: too many stops for one static map ({len(points)})")
    own = client is None
    client = client or httpx.Client(timeout=STATIC_TIMEOUT_S)
    try:
        png = fetch(PROVIDER, "GET", STATIC_URL, summary=f"GET /v1/staticmap {len(points)} markers", client=client,
                    params={**params, "apiKey": key}, binary=True)
    finally:
        if own:
            client.close()
    return {"png": png, "source": source_block(PROVIDER, public_url(STATIC_URL, params))}
