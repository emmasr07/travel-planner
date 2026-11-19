# Shared by every source: the source block, the call log (data/sources-log.jsonl) and one HTTP helper that
# logs each call, turns 401/403 into SourceAuthError and never lets a key reach a log line or an error message.
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
LOG_PATH = ROOT / "data" / "sources-log.jsonl"
TIMEOUT = 60
MAX_RETRY_WAIT = 60

# httpx logs every request URL at INFO, and Geoapify's URL carries the key.
logging.getLogger("httpx").setLevel(logging.WARNING)


class SourceError(Exception):
    """A source call failed. The message names the provider and request, never a key."""


class SourceAuthError(SourceError):
    """401/403: the key is missing, wrong or not active yet. Stop and tell the user; don't work around it."""


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def source_block(provider, url, quote=None):
    return {"provider": provider, "url": url, "retrieved_at": now_iso(), "quote": quote}


def log_call(provider, request, status, items):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = {"at": now_iso(), "provider": provider, "request": request, "status": status, "items": list(items)}
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def env(name):
    value = os.getenv(name)
    if not value:
        raise SourceError(f"{name} is not set: add it to .env (see .env.example)")
    return value


def public_url(url, params=None):
    """The request URL as it can be shown and stored: callers pass params without the key."""
    return str(httpx.URL(url, params=params or None))


def fetch(provider, method, url, *, summary, client=None, params=None, headers=None, json_body=None, items=None,
          binary=False):
    """One logged HTTP call; returns the parsed JSON (binary=True: the bytes of an image).
    `summary` is the key-free text written to the log."""
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    try:
        for attempt in (1, 2):
            try:
                resp = client.request(method, url, params=params, headers=headers, json=json_body)
            except httpx.HTTPError as e:
                log_call(provider, summary, f"error: {type(e).__name__}", [])
                raise SourceError(f"{provider}: {summary} failed ({type(e).__name__})") from None
            if resp.status_code == 429 and attempt == 1:
                log_call(provider, summary, 429, [])
                time.sleep(_retry_wait(resp))
                continue
            break
        status = resp.status_code
        if status in (401, 403):
            log_call(provider, summary, status, [])
            raise SourceAuthError(f"{provider} returned {status} for {summary}: the key is missing, wrong or not active yet")
        if not 200 <= status < 300:
            log_call(provider, summary, status, [])
            raise SourceError(f"{provider} returned {status} for {summary}")
        if binary:
            log_call(provider, summary, status, [])
            if not resp.headers.get("content-type", "").startswith("image/"):
                raise SourceError(f"{provider}: {summary} did not return an image")
            return resp.content
        try:
            data = resp.json()
        except ValueError:
            log_call(provider, summary, status, [])
            raise SourceError(f"{provider}: {summary} did not return JSON") from None
        log_call(provider, summary, status, items(data) if items else [])
        return data
    finally:
        if own:
            client.close()


def _retry_wait(resp):
    try:
        return min(int(resp.headers.get("Retry-After", "10")), MAX_RETRY_WAIT)
    except ValueError:
        return 10
