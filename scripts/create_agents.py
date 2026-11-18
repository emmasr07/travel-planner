"""Creates (first run) or updates (later runs) the researcher and the verifier on Claude Managed Agents, and the
environment their sessions run in, then writes their ids to agents/agents.lock.json, which backend/agents.py reads.

    .venv/bin/python -m scripts.create_agents        (Windows: .venv/Scripts/python -m scripts.create_agents)

Run it by hand, once, and again after changing prompts/researcher.md, prompts/verifier.md or the tools in
backend/agents.py. The server never runs it: agents are created once, sessions every run. Needs ANTHROPIC_API_KEY and
AGENT_MODEL in .env. It makes no model calls, so it costs nothing.
"""
import json
import os

from backend import agents

# Every tool is a custom tool answered by our backend, so the sandbox needs no network at all: limited, no hosts.
ENVIRONMENT = {"name": "travel-planner", "config": {"type": "cloud", "networking": {"type": "limited"}}}
NAMES = {"researcher": "Travel planner: researcher", "verifier": "Travel planner: verifier"}


def definitions(model):
    return {role: {"name": NAMES[role], "model": model, "system": agents.prompt(role), "tools": agents.agent_tools(role)}
            for role in agents.ROLES}


def main(client=None):
    model = os.getenv("AGENT_MODEL", "").strip()
    if not model:
        raise SystemExit("AGENT_MODEL is not set: copy it from .env.example into .env")
    client = client or agents._client()
    lock = json.loads(agents.LOCK.read_text(encoding="utf-8")) if agents.LOCK.exists() else {}

    def save():
        agents.LOCK.parent.mkdir(parents=True, exist_ok=True)
        agents.LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    if "environment_id" not in lock:
        lock["environment_id"] = client.beta.environments.create(**ENVIRONMENT).id
        save()
        print("environment created:", lock["environment_id"])

    for role, definition in definitions(model).items():
        if role in lock:   # this script owns the agents: update without a version check
            agent = client.beta.agents.update(lock[role]["id"], **definition)
            print(f"{role}: updated {agent.id}, now version {agent.version}")
        else:
            agent = client.beta.agents.create(**definition)
            print(f"{role}: created {agent.id}, version {agent.version}")
        lock[role] = {"id": agent.id, "version": agent.version}
        save()
    print("written:", agents.LOCK)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    main()
