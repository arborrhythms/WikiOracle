# Security

WikiOracle is a local-first application. The Flask server binds to `127.0.0.1:8888` by default and is not intended for direct exposure to the public internet. This document covers the security considerations relevant to its architecture.

## 1. Private Data

**Conversation state** (`llm.jsonl`) contains the user's full dialogue history, system context, and trust entries. It lives on disk next to the server process.

- In **stateful mode**, state is read from and written to disk by the server. No state leaves the machine unless the user explicitly exports it.
- In **stateless mode**, state is held in `sessionStorage` and sent to the server with each request. The server does not persist it. A same-origin script context can read `sessionStorage`, so the CSP policy (see below) is the primary defence against exfiltration.

**Trust entries** may contain user-authored facts, external source references, and provider configuration. Entries with high certainty influence every LLM response via RAG retrieval.

**Exports** (`llm_*.jsonl` files) are full snapshots of state. They should be treated as sensitive if conversations contain private information.

## 2. API Keys

Provider API keys (OpenAI, Anthropic, etc.) can be configured in three places, listed in precedence order:

1. **Environment variables** (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) — recommended for any deployment beyond localhost. Keys never appear in served content.
2. **`config.yaml`** `providers.<name>.api_key` — convenient for local development but the raw YAML is served to the client via `/bootstrap` and `/config` GET endpoints. Any same-origin script context can read these keys.
3. **Trust entries** (`<provider><api_key>$ENV_VAR</api_key></provider>`) — the `$` prefix triggers env-var resolution on the server; the literal key is never stored in state.

**Recommendation:** In any deployment where the server is reachable beyond `127.0.0.1`, use environment variables exclusively. Do not place raw API keys in `config.yaml`.

The `config.server.providers` metadata (served via `/config` and `/bootstrap`) exposes only `has_key` (boolean) and `needs_key` (boolean) — never the key itself.

## 3. Identity

WikiOracle does not implement authentication. The server trusts any request from an allowed origin (configured via `WIKIORACLE_ALLOWED_ORIGINS`, defaulting to `https://127.0.0.1:8888` and `https://localhost:8888`).

- **Username** is a display label set in Settings, not an authenticated identity. It is stored in `config.yaml` and included in message metadata.
- **No sessions or tokens.** There is no login, no cookies used for auth, and no per-user isolation. If multiple users share a server instance, they share the same state.

For multi-user or public deployments, WikiOracle should sit behind a reverse proxy that handles authentication and maps users to separate state files.

## 4. Cross-Site Scripting (XSS)

WikiOracle renders user and LLM content as HTML (XHTML subset). Several layers mitigate XSS:

**Content-Security-Policy (CSP):** The server applies an enforcing CSP header to all responses:

```
default-src 'self';
script-src 'self' https://d3js.org https://cdnjs.cloudflare.com;
style-src 'self';
img-src 'self' data:;
connect-src 'self';
object-src 'none';
base-uri 'self';
frame-ancestors 'none';
form-action 'self'
```

This blocks inline scripts, inline styles, and external resource loading (except D3 and js-yaml from their CDNs). Even if malicious content is injected into a message, the browser will refuse to execute it.

**XHTML enforcement:** The system context instructs the LLM to return strictly valid XHTML. The client validates responses and repairs malformed markup via `validateXhtml()` and `repairXhtml()` before rendering.

**Input escaping:** User input is escaped via `escapeHtml()` before being inserted into optimistic UI entries. The `stripTags()` helper is used for tooltip and title text where HTML should not render.

**Residual risks:**

- LLM responses are rendered as HTML (not plain text). A sufficiently adversarial prompt could produce markup that, while blocked by CSP from executing scripts, might still create misleading UI (e.g., fake form elements via `<input>` tags). The XHTML validator does not currently strip all non-semantic HTML.
- Trust entry content is XHTML and is rendered in the trust editor and included in RAG context. Malicious trust entries could inject misleading content into prompts.
- The `/bootstrap` and `/config` endpoints serve raw `config.yaml` to the client. If `config.yaml` contains secrets and a same-origin XSS vector exists, those secrets could be read.

## 5. CORS

The server applies CORS headers only for requests whose `Origin` header matches the configured allowed origins. Preflight `OPTIONS` requests return `204` with appropriate headers. Cross-origin requests from other origins receive no CORS headers and are blocked by the browser.

## 6. File System

- **Symlink rejection:** By default (`WIKIORACLE_REJECT_SYMLINKS=true`), the server refuses to read or write state files that are symlinks, preventing path-traversal attacks via symlinked state files.
- **Static file serving** is restricted to a whitelist of safe extensions (`.html`, `.css`, `.js`, `.svg`, `.png`, `.ico`, `.json`, `.jsonl`) and path-traversal is checked (`str(fp).startswith(str(ui_dir.resolve()))`).
- **State size limit:** `max_state_bytes` (default 5 MB) prevents unbounded growth from malicious imports.

## 7. Third-party Scraping

Scraping of publicly-accessible data is inevitable. However, a network of truth prevents capture. In one sense, it cannot be captured because it is a dynamic network of trust, overlaid on people and resources that trust one another, and we chose not to trust any authoritarian sources of knowledge. On a practical level,  anyone who tries to appropriate the truth of the network entails doing so in a distributed way (which preserves the multicultural component), since monolithic capture of that truth will cause consensus to collapse it.