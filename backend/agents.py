# The only file that talks to the AI (Claude Managed Agents), or stands in for it in demo mode.
#   MODE=demo (default): research = the matching sample in data/samples/<city>.json plus fixed suggestions;
#                        verification = fixed "not_sure" verdicts, clearly labelled demo. Free, no key, no network.
#   MODE=agents:         the researcher and the verifier on Claude Managed Agents. scripts/create_agents.py creates them
#                        once (ids in agents/agents.lock.json); here every job is one session with a cost cap, a time
#                        limit and the model from .env. The agents' tools are answered by this file over
#                        backend/sources/, and every delivery is checked by the code and sent back with its errors.
# Every function returns data in the agents' delivery shape (schemas/*.schema.json), so trips.py treats both alike.
import copy
import itertools
import json
import os
import re
import threading
import time
from pathlib import Path

from backend import budget, checks
from backend.checks import PACE_LIMIT, clock, minutes, trip_days
from backend.schema import QUICK_MAX_ITEMS, VERDICTS_SCHEMA, delivery_schema, experiences_schema, validate_delivery
from backend.sources import fx, geoapify, tavily, viator
from backend.sources.common import SourceAuthError, SourceError, now_iso

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data" / "samples"
PROMPTS_DIR = ROOT / "prompts"
LOCK = ROOT / "agents" / "agents.lock.json"   # written by scripts/create_agents.py: environment and agent ids
DEMO_PAUSE_S = 0.6          # between demo step lines, so the page can show the loop; 0 in tests
MAX_ITEMS = 15
DEFAULT_VISIT_MIN = 120     # demo visit length when the source gives no duration
START_TIMES = {"chill": ["10:00", "15:00"], "balanced": ["10:00", "14:00", "17:00"],
               "packed": ["09:30", "12:00", "14:30", "17:00"]}
DEMO_REASON = "Demo suggestion: a fixed time slot, not chosen for this place"
DEMO_NOTE = "Demo mode: not verified. The verifier did not reopen the source; check it on the booking page."

ROLES = ("researcher", "verifier")
HTTP = None                 # httpx client for the agent tools' source calls; None = each source opens its own
MAX_DELIVERIES = 3          # deliveries per session, the last one included
MAX_RECONNECTS = 3          # times a dropped event stream is reopened
PAGE_CHARS = 30_000         # page text read_page sends an agent; the code's source check keeps the whole page
ERRORS_SENT = 40            # delivery errors sent back at once
SETUP = "run scripts/create_agents.py once (.venv/bin/python -m scripts.create_agents)"
STOPWORDS = set("""the and for you can want wants find one some with our please something suddenly like would could
there this that what where any get let near today tonight tomorrow also are have has into from more just maybe really
very nice good place places thing things need looking look try see day time who how not but all out now too its""".split())


class NotBuilt(Exception):
    """A feature planned for a later session."""


class NotReady(Exception):
    """503: agents mode is not set up (a setting or agents/agents.lock.json is missing)."""


class AgentFailed(RuntimeError):
    """An agent session ended without a usable delivery; the message says why."""


def mode():
    return "agents" if os.getenv("MODE", "demo").strip().lower() == "agents" else "demo"


# --- the samples --------------------------------------------------------------------------------------------

def _samples():
    """slug -> (destination name, experiences) for every data/samples/<slug>.json. The name comes from the file
    ("london" -> "London"): the places' own city can be wider ("Greater London")."""
    out = {}
    for path in sorted(SAMPLES_DIR.glob("*.json")):
        exps = json.loads(path.read_text(encoding="utf-8"))["experiences"]
        out[path.stem] = (path.stem.replace("-", " ").title(), exps)
    return out


def demo_destinations():
    return sorted(city for city, _ in _samples().values())


def find_sample(destination):
    """(slug, city, experiences) for a destination like "Lisbon" or "london, England"; None without a sample."""
    wanted = destination.split(",")[0].strip().lower()
    for slug, (city, exps) in _samples().items():
        aliases = {slug, city.lower()} | {e["location"]["city"].lower() for e in exps}
        if wanted in aliases:
            return slug, city, exps
    return None


def sample_rates(destination):
    """currency -> fx block, from prices the sample builder already converted (Frankfurter), so demo stays offline."""
    found = find_sample(destination)
    rates = {}
    for e in (found[2] if found else []):
        fx_block = e["price"].get("fx")
        if fx_block:
            rates.setdefault(fx_block["from"], fx_block)
    return rates


# --- research, verification and quick search ----------------------------------------------------------------

def research(profile, step, record=None, pages=None):
    """{"experiences": [...]} in the researcher's delivery shape. In agents mode `pages` (url -> text) collects the
    pages the researcher read, for the code's source check, and `record` gets the session's cost."""
    if mode() != "demo":
        return _research_with_agent(profile, step, record, {} if pages is None else pages)
    slug, city, sample = find_sample(profile["destination"])
    step("researcher", f"demo mode, no AI: reading data/samples/{slug}.json ({len(sample)} places in {city})")
    _pause()
    interests = profile["interests"]
    matching = [e for e in sample if e["category"] in interests]
    days, pace = trip_days(profile), profile["pace"]
    chosen = matching[:min(days * PACE_LIMIT[pace], MAX_ITEMS)]
    if not matching:
        step("researcher", f"nothing in the {city} sample matches {', '.join(interests)}: "
                           "try widening your interests")
    else:
        step("researcher", f"{len(matching)} places match {', '.join(interests)}; proposing {len(chosen)} "
                           f"for {days} {'day' if days == 1 else 'days'} at a {pace} pace")
    _pause()
    delivered = [_with_demo_suggestions(e, i, days, pace) for i, e in enumerate(chosen)]
    if delivered:
        step("researcher", "fixed demo suggestions for the day, the time and why each one fits")
        _pause()
    return {"experiences": delivered}


def verify(profile, experiences, step, record=None):
    """{"verdicts": [...]} in the verifier's delivery shape."""
    if mode() != "demo":
        return _verify_with_agent(profile, experiences, step, record)
    step("verifier", "demo mode: the verifier did not run, so every experience is marked not sure")
    _pause()
    return {"verdicts": [{"id": e["id"], "verdict": "not_sure", "url_read": "", "passage": "",
                          "contested_fields": [], "note": DEMO_NOTE} for e in experiences]}


def quick(profile, ask, step, record=None, pages=None):
    """0-3 options for a swap or a last-minute request (prompts/quick-search.md), in the researcher's delivery shape.
    ask: {kind: swap|quick, request, day, free_slots, budget_left, taken (ids in the trip), for (swapped item)}."""
    if mode() == "demo":
        return _demo_quick(profile, ask, step)
    settings()
    city = _city(profile, step)
    message = {k: ask[k] for k in ("request", "day", "free_slots", "budget_left")}

    def check(delivery):
        errors = checks.delivery_errors(delivery, profile, quick=True)
        if validate_delivery(delivery, quick=True):
            return errors                                   # not the right shape: nothing else can be checked
        return errors + checks.quick_errors(delivery, ask)

    tools = _source_tools(city, {} if pages is None else pages)
    return _run("researcher", "quick", _json({"profile": profile, **message}), tools,
                "deliver_experiences", check, step, record, title=f"quick search: {profile['destination']}",
                overrides={"system": quick_prompt(), "tools": agent_tools("researcher", quick=True)})


def rates(profile, experiences):
    """currency -> fx block for the prices to convert: the sample's rates in demo mode, Frankfurter in agents mode.
    A currency with no rate stays unconverted (not counted, and the price check says so)."""
    if mode() == "demo":
        return sample_rates(profile["destination"])
    out = {}
    for currency in sorted({e["price"]["currency"] for e in experiences
                            if e["price"]["amount"] is not None and e["price"]["currency"] != "EUR"}):
        try:
            out[currency] = fx.eur_rate(currency, client=HTTP)
        except SourceError:
            pass
    return out


def source_pages(experiences, pages=None):
    """url -> page text for every web quote, for the code's source check: the pages the researcher read, and any
    other quoted page read now ("" when it does not load). None in demo mode: no page is read."""
    if mode() == "demo":
        return None
    out = dict(pages or {})
    for e in experiences:
        for block in checks.web_blocks(e):
            if block["url"] not in out:
                try:
                    page = tavily.read_page(block["url"], client=HTTP)
                except SourceError:
                    page = None
                out[block["url"]] = page["text"] if page else ""
    return out


# --- agents mode: settings, prompts and tools -------------------------------------------------------------------

def settings():
    """The agents-mode settings from .env, and the ids scripts/create_agents.py wrote. NotReady names what's missing."""
    model = os.getenv("AGENT_MODEL", "").strip()
    if not model:
        raise NotReady("agents mode is not set up: AGENT_MODEL is not set (copy it from .env.example into .env)")
    caps = {"researcher": _whole("RESEARCHER_CAP_CENTS"), "verifier": _whole("VERIFIER_CAP_CENTS")}
    deadline = int(_whole("AGENT_DEADLINE_S"))
    if not LOCK.exists():
        raise NotReady(f"agents mode is not set up: agents/agents.lock.json is missing: {SETUP}")
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if "environment_id" not in lock or any(role not in lock for role in ROLES):
        raise NotReady(f"agents mode is not set up: agents/agents.lock.json is incomplete: {SETUP}")
    return {"model": model, "caps": caps, "deadline_s": deadline, "lock": lock}


def _whole(name):
    """A positive whole number setting, as a string ("100"): caps go to the API as whole US cents in a string."""
    value = os.getenv(name, "").strip()
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise NotReady(f"agents mode is not set up: {name} must be a whole number above 0 (see .env.example)")
    return value


def _client():
    import anthropic  # only agents mode needs the SDK; it reads ANTHROPIC_API_KEY itself

    return anthropic.Anthropic()


def prompt(role):
    return (PROMPTS_DIR / f"{role}.md").read_text(encoding="utf-8")


def quick_prompt():
    """The researcher's instructions followed by the quick-search differences, for one session's system override."""
    return prompt("researcher") + "\n\n" + (PROMPTS_DIR / "quick-search.md").read_text(encoding="utf-8")


def _inline(node, defs):
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline(defs[node["$ref"].rsplit("/", 1)[-1]], defs)
        return {k: _inline(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def _input_schema(schema):
    """A schema file as a custom tool's input_schema: only type, properties and required, every $ref inlined."""
    return {"type": "object", "properties": _inline(schema["properties"], schema.get("$defs", {})),
            "required": schema["required"]}


def _tool(name, description, input_schema):
    return {"type": "custom", "name": name, "description": " ".join(description.split()), "input_schema": input_schema}


def _params(properties, required):
    return {"type": "object", "properties": properties, "required": required}


DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$", "description": "YYYY-MM-DD"}


def agent_tools(role, quick=False):
    """The custom tools of an agent (what scripts/create_agents.py sends). Names never match a built-in tool's
    (web_search, web_fetch, read, ...): the API refuses those. quick=True: the quick-search delivery (0 to 3)."""
    read_page = _tool("read_page", """Reads one web page and returns its text (the first 30,000 characters;
        "truncated" says if there was more) with a source block: provider web, the url and the time it was read.
        Read a page before you take any fact from it, or to check a record against its source. To use a fact from
        the page, copy the source block and set its quote to one sentence copied word for word from the text: the code
        checks that the sentence is on the page. If the page does not load, the tool says so: do not use that page.""",
                      _params({"url": {"type": "string", "description": "The full http(s) URL of the page."}}, ["url"]))
    if role == "verifier":
        verdicts = json.loads(VERDICTS_SCHEMA.read_text(encoding="utf-8"))
        return [read_page, _tool("deliver_verdicts", """Delivers one verdict for each experience you received, all
            in one call: confirmed, contradicted (with contested_fields, and what the page says in note) or not_sure,
            with url_read and the passage you compared copied word for word (empty if the page did not load). The code
            checks that every experience has exactly one verdict and answers "Received" or the errors to fix; you have
            3 deliveries in all.""", _input_schema(verdicts))]
    categories = experiences_schema()["$defs"]["experience"]["properties"]["category"]["enum"]
    count = "0 to 3 (a quick search: never invent one to fill the list)" if quick else "10 to 15"
    return [
        _tool("search_viator", """Searches the Viator Partner API for bookable experiences in the destination on the
            trip dates, for each interest, best rated first, priced in the destination's currency. Returns a JSON list
            of records whose fact fields (name, description, category, tags, duration_min, price, opening_hours,
            months, rating, accessibility, suitable_for, booking_url, photo_url) already carry their source blocks:
            copy them unchanged. A record has no location: call find_place with its meeting_point name or its own
            name. meeting_point and notes are hints for you, not experience fields; put relevant notes in doubts.
            If it answers "Viator unavailable", carry on with search_web and find_place.""",
              _params({"destination": {"type": "string", "description": "City as in the profile, e.g. Lisbon."},
                       "interests": {"type": "array", "items": {"type": "string", "enum": categories}, "minItems": 1},
                       "start_date": DATE, "end_date": DATE}, ["destination", "interests", "start_date", "end_date"])),
        _tool("find_place", """Looks up a place by name in a city with Geoapify (OpenStreetMap data), within 30 km of
            the city centre. Returns matched_name, lat, lng, address, timezone and a source block for the location,
            plus opening_hours and accessibility when OpenStreetMap has them (each with its own source block), or a
            message that nothing reliable matched. Check that matched_name is the place you meant; if it is not, or
            nothing matched, leave the experience out: without coordinates it cannot go on the map. Copy the source
            blocks unchanged.""",
              _params({"name": {"type": "string", "description": "The place's name, e.g. Museu Nacional do Azulejo."},
                       "city": {"type": "string", "description": "The city, e.g. Lisbon."}}, ["name", "city"])),
        _tool("search_web", """Searches the web (Tavily) for experiences Viator does not have and for official pages
            with opening hours, prices, minimum ages or seasons. Returns up to 5 results with title, url and a
            snippet. A result is only a lead, never a source: do not copy a fact from a snippet; open the page with
            read_page and copy from there. Prefer official sites (the operator, museum, park, tourism board) over
            blogs and aggregators.""",
              _params({"query": {"type": "string", "description": "What to search for, e.g. 'Lisbon tile museum "
                                                                     "opening hours official site'."}}, ["query"])),
        read_page,
        _tool("deliver_experiences", f"""Delivers your final list of experiences: {count}, best fit first, each in
            exactly this shape. The code checks it (the schema, unique ids, each schedule inside the trip with end =
            start + duration_min, and for a quick search the day, the free slots and ids not already in the trip) and
            answers "Received" or the errors to fix. Fix exactly those errors and call it again; you have 3
            deliveries in all. Prices are copied as the source states them; amount_eur and fx are always null.""",
              _input_schema(delivery_schema(quick=quick))),
    ]


def _source_tools(city, pages):
    """name -> handler(input) -> (text, is_error) for the researcher's source tools. `pages` collects what was read."""
    near = (city["lat"], city["lng"])

    def search_viator(i):
        try:
            found = viator.search_viator(i["destination"], i["interests"], (i["start_date"], i["end_date"]),
                                         client=HTTP)
        except SourceAuthError as e:
            return f"Viator unavailable ({e}). Carry on with search_web and find_place.", True
        return _json(found), False

    def find_place(i):
        found = geoapify.find_place(i["name"], i["city"], near=near, client=HTTP)
        if not found:
            return f"No reliable match for {i['name']!r} in {i['city']}: leave it out, or try its official name.", False
        return _json(found), False

    def search_web(i):
        return _json(tavily.web_search(i["query"], client=HTTP)), False

    return {"search_viator": search_viator, "find_place": find_place, "search_web": search_web,
            "read_page": _read_page(pages)}


def _read_page(pages):
    def read_page(i):
        url = i["url"]
        page = tavily.read_page(url, client=HTTP)
        if not page:
            return f"The page did not load: {url}. Do not use it.", True
        pages[url] = page["text"]
        text = page["text"]
        return _json({"url": url, "text": text[:PAGE_CHARS], "truncated": len(text) > PAGE_CHARS,
                      "source": page["source"]}), False
    return read_page


def _city(profile, step):
    """The destination's city from Geoapify: its centre keeps find_place within 30 km, and it gives the timezone."""
    city = geoapify.find_city(profile["destination"], client=HTTP)
    if not city:
        raise AgentFailed(f"Geoapify found no city called {profile['destination']!r}: check the destination")
    if not profile.get("timezone"):
        profile["timezone"] = city["timezone"]
    step("code", f"{city['name']} found by Geoapify at {city['lat']:.4f}, {city['lng']:.4f} "
                 f"(timezone {city['timezone']})")
    return city


FACT_FIELDS = ("id", "name", "description", "category", "tags", "location", "duration_min", "price", "opening_hours",
               "months", "min_age", "rating", "indoor_outdoor", "accessibility", "booking_url")


def _facts(e):
    """What the verifier sees of an experience: the fact fields with their source blocks, nothing the code or the
    researcher added (prices as the source stated them, not converted)."""
    out = {k: copy.deepcopy(e[k]) for k in FACT_FIELDS if k in e}
    out["price"] = {k: v for k, v in out["price"].items() if k not in ("amount_eur", "fx")}
    return out


def _research_with_agent(profile, step, record, pages):
    settings()
    city = _city(profile, step)
    return _run("researcher", "research", _json(profile), _source_tools(city, pages), "deliver_experiences",
                lambda d: checks.delivery_errors(d, profile), step, record,
                title=f"researcher: {profile['destination']}")


def _verify_with_agent(profile, experiences, step, record):
    settings()
    if not experiences:
        return {"verdicts": []}
    ids = [e["id"] for e in experiences]
    message = {"profile": profile, "experiences": [_facts(e) for e in experiences]}
    return _run("verifier", "verify", _json(message), {"read_page": _read_page({})}, "deliver_verdicts",
                lambda d: checks.verdict_errors(d, ids), step, record, title=f"verifier: {profile['destination']}")


# --- agents mode: one session -----------------------------------------------------------------------------------

def _run(role, purpose, text, tools, deliver_name, check, step, record, *, title, overrides=None):
    """One capped session of `role`: sends `text`, answers the tool calls, returns the delivery `check` accepted.
    The session's cost goes to `record` whatever happens; AgentFailed says why nothing was delivered."""
    cfg = settings()
    lock, cap, deadline = cfg["lock"], cfg["caps"][role], cfg["deadline_s"]
    client = _client()
    agent = {"type": "agent_with_overrides", "id": lock[role]["id"], "version": lock[role]["version"],
             "model": {"id": cfg["model"]}, **(overrides or {})}
    session = client.beta.sessions.create(
        agent=agent, environment_id=lock["environment_id"], title=title,
        budget={"type": "limit", "max_list_cost": {"amount": cap, "currency": "USD"}})
    step(role, f"session {session.id} started: {cfg['model']}, cost cap ${budget.usd(cap)}, time limit {deadline} s")
    loop = _Loop(client, session.id, role, tools, deliver_name, check, step, deadline)
    try:
        loop.run(text)
    finally:
        info = _finish(client, session.id, role, purpose, cfg["model"], cap, loop)
        cost = info["list_cost"]
        step(role, f"session ended ({loop.stop}): list cost "
                   + (f"${budget.usd(cost['amount'])}" if cost else "unknown (see the Console)"))
        if record:
            record(info)
    if loop.delivered is None:
        raise AgentFailed(loop.why_failed(cap))
    return loop.delivered


def _finish(client, session_id, role, purpose, model, cap, loop):
    list_cost = active = None
    try:
        usage = client.beta.sessions.retrieve(session_id).usage
        if usage.list_cost:
            list_cost = {"amount": usage.list_cost.amount, "currency": usage.list_cost.currency}
        active = usage.active_seconds
    except Exception:   # noqa: BLE001 - the cost stays on the Console; never hide the session's own outcome
        pass
    return {"role": role, "purpose": purpose, "session_id": session_id, "model": model,
            "cap": {"amount": cap, "currency": "USD"}, "list_cost": list_cost, "active_seconds": active,
            "stop": loop.stop, "deliveries": loop.deliveries, "tool_calls": loop.tool_calls, "ended": now_iso()}


def _stream_drops():
    import anthropic
    import httpx2

    return anthropic.APIConnectionError, httpx2.TransportError, httpx2.StreamError


class _Loop:
    """Follows one session's events: answers each tool call once, keeps the accepted delivery, stops on idle (not
    waiting on us) or terminated, interrupts at the time limit, and reopens a dropped stream (history + dedupe)."""

    def __init__(self, client, session_id, role, tools, deliver_name, check, step, deadline_s):
        self.client, self.session_id, self.role, self.step = client, session_id, role, step
        self.tools, self.deliver_name, self.check, self.deadline_s = tools, deliver_name, check, deadline_s
        self.delivered, self.deliveries, self.tool_calls = None, 0, 0
        self.stop, self.error, self.timed_out = None, None, False
        self.seen, self.answered = set(), set()
        self.stream = None
        self._sending = threading.Lock()

    def run(self, text):
        timer = threading.Timer(self.deadline_s, self._time_up)
        timer.daemon = True
        timer.start()
        try:
            sent, drops = False, 0
            while not self.timed_out:
                with self.client.beta.sessions.events.stream(self.session_id) as stream:
                    self.stream = stream
                    if not sent:     # stream first, then the message: no early event is missed
                        self._send({"type": "user.message", "content": [{"type": "text", "text": text}]})
                        sent, events = True, iter(stream)
                    else:
                        events = itertools.chain(self.client.beta.sessions.events.list(self.session_id, order="asc"),
                                                 stream)
                    try:
                        for event in events:
                            if self._handle(event):
                                return
                    except _stream_drops():
                        pass
                    except Exception:   # noqa: BLE001 - closing the stream at the time limit may raise anything
                        if not self.timed_out:
                            raise
                if self.timed_out:
                    return
                drops += 1
                if drops > MAX_RECONNECTS:
                    raise AgentFailed(f"{self.role}: the event stream dropped {drops} times")
                self.step(self.role, "the event stream dropped: reconnecting")
        finally:
            timer.cancel()

    def _handle(self, event):
        """True when the session stopped (or must stop)."""
        if event.id in self.seen:
            return False
        self.seen.add(event.id)
        kind = event.type
        if kind == "agent.custom_tool_use" and event.id not in self.answered:
            self.answered.add(event.id)
            return self._answer(event)
        if kind == "session.error":
            self.error = getattr(event.error, "message", None) or str(event.error)
            self.step(self.role, f"session error: {_short(self.error)}")
        elif kind == "session.status_idle" and event.stop_reason.type != "requires_action":
            self.stop = self.stop or event.stop_reason.type
            return True
        elif kind == "session.status_terminated":
            self.stop = self.stop or "terminated"
            return True
        return False

    def _answer(self, event):
        self.tool_calls += 1
        name, data, stop = event.name, event.input, False
        self.step(self.role, _describe(name, data))
        if name == self.deliver_name:
            text, is_error, stop = self._delivery(data)
        elif name in self.tools:
            text, is_error = _call(self.tools[name], data)
        else:
            known = ", ".join([*self.tools, self.deliver_name])
            text, is_error = f"There is no tool called {name}: use one of {known}.", True
        self._send({"type": "user.custom_tool_result", "custom_tool_use_id": event.id,
                    "content": [{"type": "text", "text": text}], "is_error": is_error})
        if stop:   # no tries left: stop the agent now, so it spends nothing more
            self._send({"type": "user.interrupt"})
        return stop

    def _delivery(self, data):
        if self.delivered is not None:
            return "Already received: stop here.", False, False
        self.deliveries += 1
        n, errors = self.deliveries, self.check(data)
        if not errors:
            self.delivered = data
            self.step(self.role, f"delivery {n} accepted by the code checks")
            return "Received. Stop here: do not call any more tools.", False, False
        if n >= MAX_DELIVERIES:
            self.stop = "too_many_deliveries"
            self.step(self.role, f"delivery {n} refused: still {len(errors)} errors, no tries left")
            return f"Still {len(errors)} errors after {MAX_DELIVERIES} deliveries: stop here.", True, True
        self.step(self.role, f"delivery {n} refused by the code checks: {len(errors)} errors, "
                             f"first: {_short(errors[0])}")
        shown = errors[:ERRORS_SENT]
        more = f"\n...and {len(errors) - len(shown)} more" if len(errors) > len(shown) else ""
        return (f"{len(errors)} errors: fix exactly these and call {self.deliver_name} again "
                f"({MAX_DELIVERIES - n} tries left):\n" + "\n".join(shown) + more), True, False

    def _send(self, event):
        with self._sending:
            self.client.beta.sessions.events.send(self.session_id, events=[event])

    def _time_up(self):
        self.timed_out = True
        self.stop = self.stop or "time_limit"
        try:
            self._send({"type": "user.interrupt"})
        except Exception:   # noqa: BLE001 - the stream is closed below either way
            pass
        if self.stream is not None:
            self.stream.close()

    def why_failed(self, cap):
        reasons = {
            "budget_reached": f"{self.role} stopped at its cost cap (${budget.usd(cap)}) before delivering",
            "time_limit": f"{self.role}: no delivery within {self.deadline_s} s: the session was interrupted",
            "too_many_deliveries": f"{self.role}: the delivery still had errors after {MAX_DELIVERIES} deliveries",
        }
        if self.stop in reasons:
            return reasons[self.stop]
        if self.error:
            return f"{self.role}: the session failed: {self.error}"
        return f"{self.role}: the session ended ({self.stop}) without a delivery"


def _call(handler, data):
    try:
        return handler(data)
    except SourceError as e:      # never carries a key (backend/sources/common.py)
        return str(e), True
    except (KeyError, TypeError, ValueError) as e:
        return f"Bad input ({type(e).__name__}: {e}): check this tool's parameters.", True


def _describe(name, data):
    """One step line for a tool call, as the page shows it."""
    if name == "search_web":
        return _short(f"search_web {data.get('query')!r}")
    if name == "read_page":
        return _short(f"read_page {data.get('url')}")
    if name == "find_place":
        return _short(f"find_place {data.get('name')!r} in {data.get('city')}")
    if name == "search_viator":
        return _short(f"search_viator {data.get('destination')}: {', '.join(data.get('interests') or [])}, "
                      f"{data.get('start_date')} to {data.get('end_date')}")
    if name in ("deliver_experiences", "deliver_verdicts"):
        key = name.removeprefix("deliver_")
        items = data.get(key)
        return f"{name}: {len(items) if isinstance(items, list) else '?'} {key}"
    return _short(f"{name} {_json(data)}")


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _short(text, limit=140):
    return text if len(text) <= limit else text[:limit - 1] + "…"


# --- demo suggestions -------------------------------------------------------------------------------------------

def _demo_quick(profile, ask, step):
    """Swap: other places of the same category, at the swapped item's time. Quick: places whose name, tags or
    category share a word with the request, in the first free slot that fits. Never more than 3, never padded."""
    slug, city, sample = find_sample(profile["destination"])
    free = [e for e in sample if e["id"] not in set(ask["taken"])]
    options = []
    if ask["kind"] == "swap":
        old = ask["for"]
        found = [e for e in free if e["category"] == old["category"]][:QUICK_MAX_ITEMS]
        step("researcher", f"demo mode, no AI: {len(found)} other {old['category']} places in "
                           f"data/samples/{slug}.json")
        s = old["schedule"]
        options = [_demo_at(e, s["day"], s["start"], f"An alternative to {old['name']}") for e in found]
    else:
        words = _words(ask["request"])
        found = [e for e in free if words & _words(" ".join([e["name"], e["category"], *e["tags"]]))]
        step("researcher", f"demo mode, no AI: {len(found)} places in data/samples/{slug}.json match the words of "
                           "your request")
        for e in found:
            length = e["duration_min"] or DEFAULT_VISIT_MIN
            slot = next((f for f in ask["free_slots"] if minutes(f["end"]) - minutes(f["start"]) >= length), None)
            if slot:
                options.append(_demo_at(e, ask["day"], slot["start"], "It matches your request"))
            if len(options) == QUICK_MAX_ITEMS:
                break
    _pause()
    return {"experiences": options}


def _words(text):
    return {w for w in re.findall(r"[^\W\d_]{3,}", text.lower()) if w not in STOPWORDS}


def _with_demo_suggestions(sample_item, i, days, pace):
    return _demo_at(sample_item, i % days + 1, START_TIMES[pace][i // days], f"You picked {sample_item['category']}")


def _demo_at(sample_item, day, start, why):
    e = json.loads(json.dumps(sample_item))
    e["price"]["amount_eur"] = None              # as the agent delivers it: the code converts
    e["price"]["fx"] = None
    e["price"].setdefault("label", None)         # the samples name no price
    length = e["duration_min"] or DEFAULT_VISIT_MIN
    e["best_time"] = {"slot": _slot(start), "start": start, "reason": DEMO_REASON, "kind": "suggestion"}
    e["why_fits"] = {"text": why, "kind": "suggestion"}
    e["schedule"] = {"day": day, "start": start, "end": clock(minutes(start) + length)}
    return e


def _slot(start):
    m = minutes(start)
    return "morning" if m < 12 * 60 else "midday" if m < 14 * 60 else "afternoon" if m < 17 * 60 else "evening"


def _pause():
    if DEMO_PAUSE_S:
        time.sleep(DEMO_PAUSE_S)
