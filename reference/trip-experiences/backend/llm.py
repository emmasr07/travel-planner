"""The only file that talks to the model: one Claude Managed Agents session per job, or demo data when MODE=demo.

research(profile) -> experiences   the researcher reads the web and delivers 10-15 experiences with sources
verify(profile, experiences) -> verdicts   the verifier reopens each source and says confirmed / contradicted / not_sure

The agents run on Anthropic's platform; this file runs on the laptop, opens the session, streams its events, answers
the delivery tool and returns plain dicts. Agent ids come from agents/agents.lock.json (python -m agents.create_agents).
"""
import json
import os
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "agents" / "agents.lock.json"
DEMO = ROOT / "data" / "demo_research.json"

# Hard cap per session in US cents, enforced by the platform at list price: tokens, web searches ($10 per 1,000) and
# container time. What a run costs is known only afterwards, in session.usage; these caps bound it.
CAP_CENTS = {"researcher": os.getenv("RESEARCHER_CAP_CENTS", "400"), "verifier": os.getenv("VERIFIER_CAP_CENTS", "300")}
DEADLINE_S = 15 * 60
MAX_DELIVERIES = 3

Step = Callable[[str, str], None]  # (who, text): one line of the visible agent loop


class AgentFailed(RuntimeError):
    pass


def mode() -> str:
    return "agents" if os.getenv("MODE", "demo") == "agents" else "demo"


def research(profile: dict, step: Step, check: Callable[[dict], list[str]]) -> tuple[list[dict], str | None]:
    if mode() == "demo":
        return _demo("experiences", step, "researcher"), None
    payload, session_id = _run("researcher", {"profile": profile}, "deliver_experiences", check, step)
    return payload["experiences"], session_id


def verify(profile: dict, experiences: list[dict], step: Step) -> tuple[list[dict], str | None]:
    if mode() == "demo":
        return _demo("verdicts", step, "verifier"), None
    clean = [{k: v for k, v in e.items() if k in DELIVERED_FIELDS} for e in experiences]
    payload, session_id = _run("verifier", {"profile": profile, "experiences": clean}, "deliver_verdicts",
                               lambda p: [], step)
    return payload["verdicts"], session_id


DELIVERED_FIELDS = ("id", "name", "place", "category", "months", "price", "min_age", "sources")


def _run(role: str, message: dict, tool: str, check: Callable[[dict], list[str]], step: Step) -> tuple[dict, str]:
    import anthropic  # only agents mode needs the SDK and a key

    if not LOCK.exists():
        raise AgentFailed("agents/agents.lock.json is missing: run python -m agents.create_agents once")
    lock = json.loads(LOCK.read_text())
    client = anthropic.Anthropic()
    session = client.beta.sessions.create(
        agent={"type": "agent", "id": lock[role]["id"], "version": lock[role]["version"]},
        environment_id=lock["environment_id"],
        title=f"{role}: {message['profile']['destination']}",
        budget={"type": "limit", "max_list_cost": {"amount": CAP_CENTS[role], "currency": "USD"}},
    )
    step(role, f"session {session.id} started")
    delivered, attempts, started = None, 0, time.monotonic()

    def send(events: list[dict]) -> None:
        client.beta.sessions.events.send(session_id=session.id, events=events)

    # Stream first, then send: the stream only carries events that happen after it opens.
    with client.beta.sessions.events.stream(session_id=session.id) as stream:
        send([{"type": "user.message", "content": [{"type": "text", "text": json.dumps(message, ensure_ascii=False)}]}])
        for event in stream:
            if time.monotonic() - started > DEADLINE_S:
                send([{"type": "user.interrupt"}])
                raise AgentFailed(f"{role}: no delivery after {DEADLINE_S // 60} minutes")
            kind = event.type
            if kind in ("agent.tool_use", "agent.mcp_tool_use"):
                step(role, f"{event.name} {_short(event.input)}")
                if getattr(event, "evaluated_permission", None) == "ask":  # nobody watches the run: deny
                    send([{"type": "user.tool_confirmation", "tool_use_id": event.id, "result": "deny"}])
            elif kind == "agent.custom_tool_use" and event.name == tool:
                attempts += 1
                errors = check(event.input)
                if errors and attempts < MAX_DELIVERIES:
                    step(role, f"delivery {attempts} refused by the code checks: {len(errors)} errors")
                    send([{"type": "user.custom_tool_result", "custom_tool_use_id": event.id, "is_error": True,
                           "content": [{"type": "text", "text": "\n".join(errors[:40])}]}])
                else:
                    delivered = event.input
                    step(role, f"delivery {attempts} received")
                    send([{"type": "user.custom_tool_result", "custom_tool_use_id": event.id,
                           "content": [{"type": "text", "text": "Received. Stop here."}]}])
            elif kind == "session.error":
                step(role, f"error: {_short(getattr(event, 'error', event))}")
            elif kind == "session.status_idle":
                reason = event.stop_reason.type
                if reason == "requires_action":
                    continue
                if reason == "budget_reached":
                    step(role, f"stopped at the cap of {int(CAP_CENTS[role]) / 100:.2f} USD")
                break
            elif kind == "session.status_terminated":
                break

    if delivered is None:
        raise AgentFailed(f"{role}: the session ended without a delivery")
    usage = client.beta.sessions.retrieve(session.id).usage
    step(role, f"done, list cost {_short(getattr(usage, 'list_cost', usage))}")
    return delivered, session.id


def _demo(key: str, step: Step, role: str) -> list[dict]:
    data = json.loads(DEMO.read_text())
    for line in data["steps"][role]:
        time.sleep(0.6)
        step(role, line)
    return data[key]


def _short(value, limit: int = 90) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"
