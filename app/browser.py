"""Persistent stealth browser (Camoufox / anti-detect Firefox).

Ported from noted's web_fetch_manager.StealthBrowser — the proven pattern —
into a standalone service. A long-running singleton: the browser launches once
and stays warm, recycling every 50 requests or 1 hour to avoid memory leaks and
tracking. A thread lock serialises access to the single page (the sync
Playwright API isn't concurrency-safe), so the FastAPI layer runs every call in
a worker thread.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import urllib.parse

logger = logging.getLogger("websearch.browser")

MAX_REQUESTS_PER_SESSION = 50
MAX_SESSION_AGE_SECONDS = 3600  # 1 hour


class StealthBrowser:
    """Singleton persistent Camoufox browser."""

    def __init__(self):
        self._browser_manager = None
        self._browser = None
        self._page = None
        self._lock = threading.Lock()
        self._request_count = 0
        self._session_start = 0.0

    def _ensure_browser(self):
        needs_refresh = (
            self._browser is None
            or self._request_count >= MAX_REQUESTS_PER_SESSION
            or (time.monotonic() - self._session_start) > MAX_SESSION_AGE_SECONDS
        )
        if not needs_refresh:
            return
        self._shutdown_browser()
        from camoufox.sync_api import Camoufox
        logger.info("Starting Camoufox browser (request_count=%d)", self._request_count)
        self._browser_manager = Camoufox(headless=True)
        self._browser = self._browser_manager.start()
        self._page = self._browser.new_page()
        self._request_count = 0
        self._session_start = time.monotonic()
        logger.info("Camoufox browser ready")

    def _shutdown_browser(self):
        # Camoufox is a context manager (no public .stop()); use __exit__ so
        # the underlying Playwright sync loop is torn down cleanly. Calling
        # .stop() leaves an orphan loop that breaks the next start().
        if self._browser_manager:
            try:
                self._browser_manager.__exit__(None, None, None)
            except Exception as e:  # noqa: BLE001
                logger.warning("Error stopping Camoufox: %s", e)
            self._browser_manager = None
            self._browser = None
            self._page = None

    def fetch_sync(self, url: str) -> str:
        with self._lock:
            self._ensure_browser()
            self._page.goto(url, timeout=20000)
            self._page.wait_for_load_state("domcontentloaded")
            self._request_count += 1
            return self._page.content()

    def search_sync(self, query: str, top_n: int = 8) -> list[dict]:
        """DuckDuckGo HTML search (JS-free results page). Each `.result` block
        has `.result__a` (title link) + `.result__snippet`. Hrefs are wrapped
        as `//duckduckgo.com/l/?uddg=<encoded-real-url>`; we unwrap them."""
        with self._lock:
            self._ensure_browser()
            search_url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
            self._page.goto(search_url, timeout=20000)
            self._page.wait_for_load_state("domcontentloaded")
            self._request_count += 1

            results: list[dict] = []
            for el in self._page.query_selector_all(".result"):
                title_el = el.query_selector(".result__a")
                if not title_el:
                    continue
                title = (title_el.inner_text() or "").strip()
                href = title_el.get_attribute("href") or ""
                snippet_el = el.query_selector(".result__snippet")
                snippet = (snippet_el.inner_text() or "").strip() if snippet_el else ""
                results.append({
                    "title": title,
                    "url": _unwrap_ddg_url(href),
                    "snippet": snippet,
                })
                if len(results) >= top_n:
                    break
            return results

    def status(self) -> dict:
        return {
            "warm": self._browser is not None,
            "request_count": self._request_count,
            "session_age_s": round(time.monotonic() - self._session_start, 1)
            if self._session_start else 0,
        }

    def shutdown(self):
        with self._lock:
            self._shutdown_browser()


def _html_to_text(html: str) -> str:
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _unwrap_ddg_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    try:
        parsed = urllib.parse.urlparse(href)
        uddg = urllib.parse.parse_qs(parsed.query).get("uddg")
        if uddg:
            return uddg[0]
    except Exception:  # noqa: BLE001
        pass
    return href
