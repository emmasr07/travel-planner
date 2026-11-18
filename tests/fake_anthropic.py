# A fake Anthropic client for the Managed Agents calls backend/agents.py and scripts/create_agents.py make:
# client.beta.environments / agents / sessions / sessions.events. It records every call and plays a scripted agent.
# No network, no key, no cost.
#
# The agent is a list of turns. Turn 0 is played when the user.message arrives; each later turn when every tool call
# of the turn before has its user.custom_tool_result. A turn is a list of events (or a function of the client that
# returns one). A turn with tool calls ends with an idle "requires_action"; a turn without them ends with an idle
# "end_turn", unless it already ends with an idle or a terminated event. HANG plays nothing (the agent never answers).
# DROP before a turn's events breaks the open stream instead of delivering them (they stay in the history).
import itertools
import queue
from types import SimpleNamespace

import httpx2

HANG = "hang"
DROP = "drop"
_CLOSED = object()
_BROKEN = object()
STREAM_WAIT_S = 5


def tool_use(name, input):
    return {"type": "agent.custom_tool_use", "name": name, "input": input}


def idle(reason):
    return {"type": "session.status_idle", "stop_reason": SimpleNamespace(type=reason)}


def usage(cents):
    return {"type": "session.usage", "list_cost": SimpleNamespace(amount=cents, currency="USD")}


def session_error(message):
    return {"type": "session.error", "error": SimpleNamespace(type="model_overloaded_error", message=message)}


def terminated():
    return {"type": "session.status_terminated"}


class FakeStream:
    def __init__(self, client):
        self.client = client
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def close(self):
        self.closed = True
        self.client.queue.put(_CLOSED)

    def __iter__(self):
        while True:
            try:
                item = self.client.queue.get(timeout=STREAM_WAIT_S)
            except queue.Empty:
                raise AssertionError(f"the fake stream waited {STREAM_WAIT_S} s for an event") from None
            if item is _CLOSED:
                return
            if item is _BROKEN:
                raise httpx2.ReadError("the stream dropped")
            yield item


class FakeEvents:
    def __init__(self, client):
        self.client = client

    def stream(self, session_id, **kwargs):
        self.client.calls.append(("events.stream", session_id))
        stream = FakeStream(self.client)
        self.client.streams.append(stream)
        return stream

    def send(self, session_id, *, events):
        self.client.calls.append(("events.send", session_id))
        for event in events:
            self.client.receive(dict(event))
        return SimpleNamespace(data=[])

    def list(self, session_id, **kwargs):
        self.client.calls.append(("events.list", session_id))
        return list(self.client.history)


class FakeSessions:
    def __init__(self, client):
        self.client = client
        self.events = FakeEvents(client)

    def create(self, **kwargs):
        self.client.calls.append(("sessions.create", kwargs))
        self.client.created.append(kwargs)
        number = len(self.client.created)
        self.client.start_script(number - 1)
        return SimpleNamespace(id=f"sesn_test{number}", status="idle")

    def retrieve(self, session_id, **kwargs):
        self.client.calls.append(("sessions.retrieve", session_id))
        return SimpleNamespace(id=session_id, status="idle",
                               usage=SimpleNamespace(list_cost=SimpleNamespace(amount=self.client.cost, currency="USD"),
                                                     active_seconds=42.0))


class FakeAgents:
    def __init__(self, client):
        self.client = client

    def create(self, **kwargs):
        self.client.calls.append(("agents.create", kwargs))
        n = sum(1 for c in self.client.calls if c[0] == "agents.create")
        return SimpleNamespace(id=f"agent_new{n}", version=1)

    def update(self, agent_id, **kwargs):
        self.client.calls.append(("agents.update", agent_id, kwargs))
        return SimpleNamespace(id=agent_id, version=self.client.versions.get(agent_id, 1) + 1)


class FakeEnvironments:
    def __init__(self, client):
        self.client = client

    def create(self, **kwargs):
        self.client.calls.append(("environments.create", kwargs))
        return SimpleNamespace(id="env_new1")


class FakeAnthropic:
    """scripts: one agent script (list of turns) per session, in the order the sessions are created."""

    def __init__(self, *scripts, cost="37", versions=None):
        self.scripts = list(scripts)
        self.cost = cost
        self.versions = versions or {}
        self.calls, self.created, self.streams, self.sent = [], [], [], []
        self.history = []
        self.results = {}          # custom_tool_use_id -> the user.custom_tool_result we got
        self.interrupted = False
        self.queue = queue.Queue()
        self._ids = itertools.count(1)
        self._turns = []
        self._waiting = set()
        self.beta = SimpleNamespace(environments=FakeEnvironments(self), agents=FakeAgents(self),
                                    sessions=FakeSessions(self))

    # --- what the code sends ---
    def start_script(self, index):
        self._turns = list(self.scripts[index]) if index < len(self.scripts) else []
        self._waiting = set()
        self.queue = queue.Queue()

    def receive(self, event):
        self.sent.append(event)
        kind = event["type"]
        if kind == "user.message":
            assert self.streams and not self.streams[-1].closed, "send the message after the stream is open"
            self._play()
        elif kind == "user.custom_tool_result":
            self.results[event["custom_tool_use_id"]] = event
            self._waiting.discard(event["custom_tool_use_id"])
            if not self._waiting:
                self._play()
        elif kind == "user.interrupt":
            self.interrupted = True

    def result_texts(self):
        return {k: (v["content"][0]["text"], v.get("is_error", False)) for k, v in self.results.items()}

    # --- what the agent does ---
    def _event(self, spec):
        return SimpleNamespace(id=f"sevt_{next(self._ids)}", **spec)

    def _play(self):
        if not self._turns:
            return
        turn = self._turns.pop(0)
        if turn == HANG:
            return
        if callable(turn):
            turn = turn(self)
        drop = bool(turn) and turn[0] == DROP
        specs = [s for s in turn if s != DROP]
        events = [self._event(s) for s in specs]
        tools = [e for e in events if e.type == "agent.custom_tool_use"]
        ends = events and events[-1].type in ("session.status_idle", "session.status_terminated")
        if tools and not ends:
            events.append(self._event(idle("requires_action")))
        elif not ends:
            events.append(self._event(idle("end_turn")))
        self._waiting = {e.id for e in tools}
        self.history += events
        if drop:
            self.queue.put(_BROKEN)
            return
        for e in events:
            self.queue.put(e)
