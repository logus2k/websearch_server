# websearch_server

Standalone web-search / web-fetch service backed by **Camoufox** (anti-detect
Firefox). Wraps the browser behind a small task API so callers never touch
Playwright. Consumed by `mcp-service`'s `web_search` tool.

## Why its own container
- **Security isolation.** It renders arbitrary, untrusted web pages. It runs on
  the `mcp_internal` network only — internet egress + reachable by `mcp-service`,
  but **no route to `noted-network`** (no SSRF pivot to noted/kb/arcadedb).
- **Reuse.** A browser backs many tools (search, fetch, screenshot). One service
  serves them all, for any app.
- **Crash/resource isolation.** Browsers are memory-heavy and crash; keeping them
  out of `mcp-service` means a browser OOM can't take down the tool host.

## API
- `POST /search {query, max_results?}` → `{provider, query, results:[{title,url,snippet}]}`
- `POST /fetch  {url, max_chars?}` → `{url, chars, truncated, text}`
- `GET  /health`

Search uses DuckDuckGo's JS-free HTML endpoint, scraped via Camoufox. The browser
is a warm singleton, recycled every 50 requests / 1 hour.

## Run
```sh
docker network create mcp_internal   # once (shared with mcp-service)
docker compose up -d --build
curl -s localhost:4960/health
curl -s -XPOST localhost:4960/search -H 'content-type: application/json' \
     -d '{"query":"site reliability engineer responsibilities","max_results":5}'
```

The host port `4960` is for direct probing; in normal operation only
`mcp-service` calls it over `mcp_internal`.
