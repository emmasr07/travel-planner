# Tavily: web search for experiences Viator doesn't have, and page text so the agent can quote a sentence.
# Search hits are leads (provider "tavily"); only a page read with read_page is a source (provider "web").
# Docs: https://docs.tavily.com/
from backend.sources.common import env, fetch, source_block

PROVIDER = "tavily"
SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"


def _auth():
    return {"Authorization": "Bearer " + env("TAVILY_API_KEY")}


def web_search(query, *, max_results=5, client=None):
    """[{title, url, snippet, source}] for `query` (basic search: 1 credit)."""
    data = fetch(PROVIDER, "POST", SEARCH_URL, summary=f"POST /search query={query!r}", client=client,
                 headers=_auth(), json_body={"query": query, "search_depth": "basic", "max_results": max_results},
                 items=lambda d: [r.get("url") for r in d.get("results") or []])
    return [{"title": r.get("title"), "url": r["url"], "snippet": r.get("content"),
             "source": source_block(PROVIDER, r["url"])} for r in data.get("results") or [] if r.get("url")]


def read_page(url, *, client=None):
    """{url, text, source} for a page, or None if it didn't load. The agent fills source.quote."""
    data = fetch(PROVIDER, "POST", EXTRACT_URL, summary=f"POST /extract url={url}", client=client, headers=_auth(),
                 json_body={"urls": [url], "extract_depth": "basic", "format": "text"},
                 items=lambda d: [r.get("url") for r in d.get("results") or []])
    results = data.get("results") or []
    page = next((r for r in results if r.get("url") == url), results[0] if results else None)
    if not page or not page.get("raw_content"):
        return None
    return {"url": url, "text": page["raw_content"], "source": source_block("web", url)}
