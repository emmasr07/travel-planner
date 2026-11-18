"""Run once, and again after changing agents/researcher.py or agents/verifier.py: creates (or updates) the environment and the two agents
on Claude Managed Agents and writes their ids to agents/agents.lock.json, which backend/llm.py reads.

    python -m agents.create_agents

Needs ANTHROPIC_API_KEY in .env. It never runs inside the web server: agents are created once, sessions every run.
"""
import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from agents.researcher import RESEARCHER
from agents.verifier import VERIFIER

LOCK = Path(__file__).with_name("agents.lock.json")
AGENTS = {"researcher": RESEARCHER, "verifier": VERIFIER}

# The web tools must reach any site of any destination, which cannot be listed in advance, so networking is
# unrestricted. No other tool is enabled (agents/shared.py, toolset): nothing runs in the container that could use the egress.
# For a closed list of sites: {"type": "limited", "allowed_hosts": [...]} plus allowed_domains on the web tools.
ENVIRONMENT = {"name": "trip-experiences", "config": {"type": "cloud", "networking": {"type": "unrestricted"}}}


def main() -> None:
    load_dotenv()
    client = anthropic.Anthropic()
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}

    if "environment_id" not in lock:
        lock["environment_id"] = client.beta.environments.create(**ENVIRONMENT).id
        print("environment created", lock["environment_id"])

    for role, definition in AGENTS.items():
        if role in lock:
            agent = client.beta.agents.update(lock[role]["id"], **definition)
            print(f"{role}: updated, version {agent.version}")
        else:
            agent = client.beta.agents.create(**definition)
            print(f"{role}: created {agent.id}, version {agent.version}")
        lock[role] = {"id": agent.id, "version": agent.version}

    LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    print("written", LOCK)


if __name__ == "__main__":
    main()
