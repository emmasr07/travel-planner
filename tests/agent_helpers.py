# Helpers for the agents-mode tests: settings and a lock file as scripts/create_agents.py writes it, the fake Anthropic
# client installed in backend/agents.py, fake source servers for the agent tools, and valid deliveries.
# Prices are fixed test examples.
import json

from backend import agents
from tests import fake_apis
from tests.factories import experience
from tests.fake_anthropic import FakeAnthropic

LOCK = {"environment_id": "env_test", "researcher": {"id": "agent_res", "version": 3},
        "verifier": {"id": "agent_ver", "version": 2}}
SETTINGS = {"MODE": "agents", "AGENT_MODEL": "claude-opus-5-5", "RESEARCHER_CAP_CENTS": "100",
            "VERIFIER_CAP_CENTS": "50", "AGENT_DEADLINE_S": "600"}
PAGE_URL = "https://www.carris.pt/tram-28"
PAGE_QUOTE = "Tram 28 departs every 15 minutes from 07:00."
WEB = {"provider": "web", "url": PAGE_URL, "retrieved_at": "2026-11-18T10:00:00+01:00", "quote": PAGE_QUOTE}


class Steps(list):
    """Collects the (who, text) step lines, as trips.py's step() would."""

    def __call__(self, who, text):
        self.append((who, text))

    def text(self):
        return "\n".join(f"{who}: {text}" for who, text in self)


def set_up(monkeypatch, **over):
    agents.LOCK.parent.mkdir(parents=True, exist_ok=True)
    agents.LOCK.write_text(json.dumps(LOCK))
    for name, value in {**SETTINGS, **over}.items():
        monkeypatch.setenv(name, value)


def install(monkeypatch, *scripts, **kwargs):
    fake = FakeAnthropic(*scripts, **kwargs)
    monkeypatch.setattr(agents, "_client", lambda: fake)
    return fake


def fake_http(monkeypatch, *, page_text=PAGE_QUOTE):
    """Geoapify (city and place), Tavily (search and extract) and Frankfurter (GBP) for the agent tools."""
    apis = fake_apis.FakeAPIs()

    def geocode(request):
        return fake_apis.city() if request.url.params.get("type") == "city" else fake_apis.geocode()

    apis.add("GET", fake_apis.GEO + "/v1/geocode/search", geocode)
    apis.add("GET", fake_apis.GEO + "/v2/place-details", fake_apis.place_details())
    fake_apis.tavily_routes(apis)
    apis.add("POST", fake_apis.TAVILY + "/extract", {"results": [{"url": PAGE_URL, "raw_content": page_text}]})
    fake_apis.fx_routes(apis)
    monkeypatch.setattr(agents, "HTTP", apis.client())
    return apis


def item(i, **over):
    """One delivered experience (120 min) on the 3 trip days, at 09:00, 12:30, 16:00, then 19:30: no overlaps."""
    start = ["09:00", "12:30", "16:00", "19:30"][i // 3 % 4]
    end = {"09:00": "11:00", "12:30": "14:30", "16:00": "18:00", "19:30": "21:30"}[start]
    return experience(f"item-{i}", name=f"Item {i}", schedule={"day": i % 3 + 1, "start": start, "end": end}, **over)


def from_the_web(e):
    """The item's price, location and hours from the page the fake researcher reads: facts the verifier agent checks.
    (Facts from Viator and Geoapify are checked by the code, backend/recheck.py, and never reach the agent.)"""
    for field in ("price", "location", "opening_hours"):
        if isinstance(e.get(field), dict):
            e[field]["source"] = dict(WEB)
    return e


def delivery(n=10, **over):
    return {"experiences": [item(i, **over) for i in range(n)]}


def verdicts(ids, verdict="confirmed"):
    return {"verdicts": [{"id": i, "verdict": verdict, "url_read": PAGE_URL, "passage": PAGE_QUOTE,
                          "contested_fields": [], "note": "The page supports the record."} for i in ids]}
