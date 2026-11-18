"""What both agents share: the model and the web tools a role may use. One file per role sits next to this one."""

MODEL = "claude-opus-5-5"


def toolset(search: bool) -> dict:
    """The web tools the role needs and nothing else: bash and the file tools stay off, the agent reads and delivers."""
    web = {"permission_policy": {"type": "always_allow"}}
    return {
        "type": "agent_toolset_20260401",
        "default_config": {"enabled": False},
        "configs": [
            {"name": "web_search", "enabled": search, **web},
            {"name": "web_fetch", "enabled": True, "max_content_tokens": 20000, **web},
        ],
    }
