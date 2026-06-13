"""websearch_server — a standalone, isolated web-search/fetch service.

Wraps Camoufox (anti-detect Firefox) behind a small task API so callers never
touch Playwright. Used by mcp-service's `web_search` tool. Runs on an isolated
network with internet egress only — it renders untrusted web content, so it has
NO route to internal services (noted, kb, arcadedb, etc.).

    POST /search  {query, max_results?}  -> {provider, query, results:[{title,url,snippet}]}
    POST /fetch   {url, max_chars?}      -> {url, chars, text}
    GET  /health
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.browser import StealthBrowser, _html_to_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("websearch")

_browser = StealthBrowser()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _browser.shutdown()


app = FastAPI(title="websearch_server", version="0.1.0", lifespan=lifespan)


class SearchIn(BaseModel):
    query: str
    max_results: int = 8


class FetchIn(BaseModel):
    url: str
    max_chars: int = 10000


@app.get("/health")
async def health():
    return JSONResponse({
        "service": "websearch_server",
        "status": "ok",
        "provider": "duckduckgo-html",
        "browser": _browser.status(),
    })


@app.post("/search")
async def search(body: SearchIn):
    q = (body.query or "").strip()
    if not q:
        return JSONResponse({"error": "query is required"}, status_code=400)
    top_n = max(1, min(int(body.max_results or 8), 25))
    try:
        results = await asyncio.to_thread(_browser.search_sync, q, top_n)
    except Exception as e:  # noqa: BLE001
        logger.exception("search failed")
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=502)
    return JSONResponse({"provider": "duckduckgo-html", "query": q, "results": results})


@app.post("/fetch")
async def fetch(body: FetchIn):
    url = (body.url or "").strip()
    if not url:
        return JSONResponse({"error": "url is required"}, status_code=400)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        html = await asyncio.to_thread(_browser.fetch_sync, url)
    except Exception as e:  # noqa: BLE001
        logger.exception("fetch failed")
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=502)
    text = _html_to_text(html)
    truncated = len(text) > body.max_chars
    if truncated:
        text = text[:body.max_chars]
    return JSONResponse({"url": url, "chars": len(text), "truncated": truncated, "text": text})
