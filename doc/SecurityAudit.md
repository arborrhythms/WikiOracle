# Security Audit — WikiOracle

**Date:** 2026-03-01
**Scope:** WikiOracle server (`bin/`), web frontend (`html/`), NanoChat integration, deployment infrastructure (`remote.py`, `Makefile`)

This audit supplements `doc/Security.md` (design-intent documentation) with a vulnerability-focused analysis. Findings are organized by severity and cross-referenced to source files.

---

## Executive Summary

WikiOracle's local-first architecture provides a strong privacy baseline — state lives on the user's machine, TLS is on by default, and CORS restricts cross-origin access. However, the audit identified **5 high-severity**, **9 medium-severity**, and **7 low-severity** findings across the server, frontend, and deployment layers. The most impactful issues are:

1. **Stored XSS** via unsanitized `innerHTML` rendering of LLM responses
2. **SSRF** through user-controlled authority and provider URLs
3. **Arbitrary file read** via `file://` authorities when `allowed_data_dir` is unset
4. **No authentication** on any endpoint
5. **Gemini API key leaked** in URL query parameters

---

## HIGH Severity

### H1. Stored XSS via `innerHTML` of LLM/Imported Content — FIXED

| Field | Value |
|-------|-------|
| **File** | `html/wikioracle.js:584` |
| **Category** | Cross-Site Scripting (CWE-79) |

**Fix:** DOMPurify v3.2.4 integrated. `sanitizeHtml()` applies a strict whitelist of tags and attributes (no `on*` handlers, no `javascript:` URIs, no `<form>`/`<input>`/`<iframe>`). `ensureXhtml()` now routes all code paths through `sanitizeHtml()` before `innerHTML` assignment. Fallback escapes all HTML if DOMPurify is unavailable.

---

### H2. SSRF via User-Controlled Authority and Provider URLs — FIXED

| Field | Value |
|-------|-------|
| **Files** | `bin/truth.py:633–759`, `bin/response.py:1078–1134` |
| **Category** | Server-Side Request Forgery (CWE-918) |

**Fix:** `is_url_allowed()` in `config.py` enforces HTTPS-only + prefix whitelist (`allowed_urls` in config.yaml). `file://` URLs are blocked. Both authority fetches and dynamic provider calls go through this check. Only explicitly whitelisted URL prefixes (API providers, Wikipedia, WikiOracle) are permitted.

---

### H3. Arbitrary File Read via `file://` Authorities — FIXED

| Field | Value |
|-------|-------|
| **File** | `bin/truth.py:720–734`, `bin/response.py:400` |
| **Category** | Path Traversal (CWE-22) |

**Fix:** `file://` URLs are now explicitly blocked in `_fetch_authority_jsonl()`. The `is_url_allowed()` whitelist ensures only HTTPS URLs matching configured prefixes are fetched. The `allowed_data_dir` parameter is vestigial — the whitelist is the primary protection.

---

### H4. No Authentication on Any Endpoint — FIXED

| Field | Value |
|-------|-------|
| **File** | `bin/wikioracle.py:90–415` |
| **Category** | Missing Authentication (CWE-306) |

**Fix:** Bearer-token authentication added via `WIKIORACLE_API_TOKEN` environment variable. When set, all endpoints (except `/health` and OPTIONS) require `Authorization: Bearer <token>`. The frontend reads the token from `sessionStorage` and prompts the user on 401. Token is opt-in — empty token disables auth (suitable for loopback-only deployments).

---

### H5. Gemini API Key Leaked in URL Query Parameter — FIXED

| Field | Value |
|-------|-------|
| **File** | `bin/response.py:920` |
| **Category** | Credential Exposure (CWE-598) |

**Fix:** Gemini API key moved from URL query parameter to `x-goog-api-key` HTTP header, consistent with all other provider adapters.

---

## MEDIUM Severity

### M1. Default Bind to All Interfaces (0.0.0.0) — FIXED

| Field | Value |
|-------|-------|
| **File** | `bin/config.py:113` |
| **Category** | Insecure Default Configuration (CWE-1188) |

**Fix:** Default `bind_host` changed to `127.0.0.1`. The production deployment uses Apache ProxyPass to route external traffic to the local Flask process; the server itself is never directly exposed. Documentation updated accordingly.

---

### M2. HTML Injection in Provider Response Assembly — FIXED

| Field | Value |
|-------|-------|
| **File** | `bin/response.py:284–293` |
| **Category** | Improper Output Encoding (CWE-116) |

**Fix:** Both the provider name and response text are now HTML-escaped with `html.escape()` before embedding in markup. The provider name uses `quote=True` to prevent attribute breakout.

---

### M3. Missing CSRF Protection — FIXED

| Field | Value |
|-------|-------|
| **Files** | `bin/wikioracle.py` (all POST endpoints), `html/query.js:13–23` |
| **Category** | Cross-Site Request Forgery (CWE-352) |

**Fix:** Added `@app.before_request` hook that rejects POST requests missing `X-Requested-With: WikiOracle` header (returns 403). The frontend `api()` function now sends this header on every request. HTML forms cannot set custom headers, so this blocks cross-site form submissions.

---

### M4. Path Traversal in Merge Endpoint — FIXED

| Field | Value |
|-------|-------|
| **File** | `bin/wikioracle.py:320–322` |
| **Category** | Path Traversal (CWE-22) |

**Fix:** Filenames containing `..`, `/`, or `\` are now rejected in the list comprehension filter. Only bare filenames with `.jsonl`/`.json` extensions are accepted.

---

### M5. Unescaped `role` Field in Search Results — ALREADY FIXED

| Field | Value |
|-------|-------|
| **File** | `html/util.js:1221` |
| **Category** | Cross-Site Scripting (CWE-79) |

**Status:** The current code already uses `escapeHtml(r.role)`. No change needed.

---

### M6. Regex Denial-of-Service in Search — FIXED

| Field | Value |
|-------|-------|
| **File** | `html/util.js:1172–1176` |
| **Category** | Regular Expression Denial of Service (CWE-1333) |

**Fix:** Added `escapeRegExp()` utility that escapes all regex metacharacters. User input is now escaped before `new RegExp()` compilation, making search a safe literal substring match while preserving the highlight/snippet logic.

---

### M7. Insecure Deserialization via File Import — FIXED

| Field | Value |
|-------|-------|
| **File** | `html/wikioracle.js:1041–1143` |
| **Category** | Insecure Deserialization (CWE-502) |

**Fix:** Added `_validateImport()` function that validates structural integrity before merge: conversations must have `id` and `messages` array, each message must have `id`, valid `role` ("user"/"assistant"), and `content`; truth entries must have `id`, `trust` (number -1 to 1), and `content`. Throws on first violation.

---

### M8. CORS Configuration Allows Overly Broad Origins — FIXED

| Field | Value |
|-------|-------|
| **File** | `bin/config.py:143–147` |
| **Category** | Permissive CORS Policy (CWE-942) |

**Fix:** Each origin in `WIKIORACLE_ALLOWED_ORIGINS` is now validated: must start with `https://` (or `http://127.0.0.1` / `http://localhost` for local dev). Wildcard `*` is rejected. Invalid entries are logged as warnings and excluded.

---

### M9. Exception Messages Leaked to Clients — FIXED

| Field | Value |
|-------|-------|
| **File** | `bin/wikioracle.py:181,197,209,289,318,389` |
| **Category** | Information Exposure (CWE-209) |

**Fix:** All `str(exc)` responses replaced with generic error messages (e.g., "Chat request failed", "Merge failed"). Full exceptions are now logged server-side via `log.exception()`.

---

## LOW Severity

### L1. CDN Scripts Without Subresource Integrity (SRI) — PARTIALLY FIXED

| Field | Value |
|-------|-------|
| **File** | `html/index.html:109–111` |

**Fix:** D3 pinned to exact version (7.9.0) via cdnjs. All three CDN scripts (D3, js-yaml, DOMPurify) now include `crossorigin="anonymous"`. CSP `script-src` updated to remove `d3js.org` (all scripts now served from `cdnjs.cloudflare.com`). SRI `integrity` hashes should be added when deploying (requires fetching the scripts to compute hashes).

---

### L2. Self-Signed TLS with No CA Validation

| Field | Value |
|-------|-------|
| **File** | `bin/config.py:34–99` |

Auto-generated self-signed certificates provide encryption but no MITM protection since clients must accept untrusted certificates. The `--no-ssl` flag disables TLS entirely.

**Recommendation:** Document the MITM risk clearly. For production deployments, support Let's Encrypt or user-provided CA-signed certificates.

---

### L3. API Keys Stored in config.yaml on Disk

| Field | Value |
|-------|-------|
| **File** | `bin/config.py:270–271,378` |

API keys can be written to `config.yaml` via `POST /config` with no special filesystem permissions. The file is gitignored but readable by any process running as the same user.

**Recommendation:** Set restrictive permissions (0600) on `config.yaml` after writing. Prefer environment variables for key storage.

---

### L4. SSH Host Key Checking Disabled for EC2

| Field | Value |
|-------|-------|
| **File** | `remote.py:31–37` |

```python
EC2_SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
]
```

SSH host key verification is disabled for ephemeral EC2 instances. An attacker positioned between the developer and EC2 could intercept training data, model weights, or inject malicious code.

**Recommendation:** Use EC2 Instance Connect or verify host keys via the EC2 console serial output.

---

### L5. Symlink Check Race Condition (TOCTOU)

| Field | Value |
|-------|-------|
| **File** | `bin/state.py:390–393` |

```python
if reject_symlinks and path.exists() and path.is_symlink():
    raise StateValidationError("Refusing to write symlink state file")
```

There is a time-of-check-to-time-of-use race between the symlink check and the `os.replace()` on line 404. An attacker with filesystem access could swap the file with a symlink between the check and the write.

**Recommendation:** Use `O_NOFOLLOW` when opening files, or check the symlink status of the final path after `os.replace()`.

---

### L6. Unbounded Authority Cache — FIXED

| Field | Value |
|-------|-------|
| **File** | `bin/truth.py:628` |

**Fix:** Replaced unbounded `dict` with `collections.OrderedDict` capped at 64 entries. Oldest entries are evicted on overflow. Cache hits refresh LRU position.

---

### L7. Debug Mode Logs Sensitive Data

| Field | Value |
|-------|-------|
| **File** | `bin/response.py:723–727,756–760,828–836,936–942` |

When `DEBUG_MODE` is enabled, message content, API endpoints, and request details are printed to stdout/stderr. If logs are collected or shared, conversation content and operational details could be exposed.

**Recommendation:** Redact message content and API key fragments from debug output.

---

## Positive Security Measures

The codebase implements several strong security practices worth acknowledging:

| Measure | Location | Notes |
|---------|----------|-------|
| **Content-Security-Policy** | `wikioracle.py:116–126` | Enforcing CSP with restrictive defaults; blocks inline scripts |
| **Static file whitelist** | `wikioracle.py:406–413` | Only safe extensions served; path traversal checked |
| **Atomic state writes** | `state.py:390–410` | Temp file + `os.replace()` prevents corruption |
| **Symlink rejection** | `state.py:390–393` | Default-on protection against symlink attacks |
| **State size limits** | `config.py:117` | `max_state_bytes` prevents unbounded growth |
| **YAML safe loading** | `config.py:197` | `yaml.safe_load()` prevents deserialization attacks |
| **API key path restriction** | `truth.py:493–511` | `file://` key resolution locked to `~/.wikioracle/keys/` with symlink and `..` rejection |
| **CORS origin checking** | `wikioracle.py:97–115` | Restrictive default origins; proper preflight handling |
| **XHTML canonicalization** | `truth.py` | Content parsed through XML, mitigating many injection vectors |
| **Stateless mode** | `wikioracle.py:152–160` | Opt-in mode that prevents all disk writes |

---

## Recommendations Summary

### Priority 1 — Fix Before Public Deployment

| # | Action | Effort | Status |
|---|--------|--------|--------|
| ~~H1~~ | ~~Integrate DOMPurify (or equivalent) to sanitize all content before `innerHTML` assignment~~ | ~~Small~~ | **Fixed** |
| ~~H4~~ | ~~Add bearer-token authentication to state-mutating endpoints~~ | ~~Medium~~ | **Fixed** |
| ~~H5~~ | ~~Move Gemini API key from URL query parameter to `x-goog-api-key` header~~ | ~~Small~~ | **Fixed** |

### Priority 2 — Address in Near Term

| # | Action | Effort | Status |
|---|--------|--------|--------|
| ~~H2~~ | ~~Validate/restrict authority and provider URLs; block internal address ranges~~ | ~~Medium~~ | **Fixed** |
| ~~H3~~ | ~~Always pass `allowed_data_dir` to `resolve_authority_entries()`~~ | ~~Small~~ | **Fixed** |
| ~~M2~~ | ~~HTML-escape provider names and responses in HME assembly~~ | ~~Small~~ | **Fixed** |
| ~~M3~~ | ~~Add CSRF protection (custom header check or token)~~ | ~~Medium~~ | **Fixed** |
| ~~M4~~ | ~~Reject filenames with `..` or `/` in merge endpoint~~ | ~~Trivial~~ | **Fixed** |
| ~~M5~~ | ~~Apply `escapeHtml()` to `r.role` in search results~~ | ~~Trivial~~ | **Already fixed** |

### Priority 3 — Harden Over Time

| # | Action | Effort | Status |
|---|--------|--------|--------|
| ~~M1~~ | ~~Change default `bind_host` to `127.0.0.1`~~ | ~~Trivial~~ | **Fixed** |
| ~~M6~~ | ~~Escape regex special characters in search~~ | ~~Small~~ | **Fixed** |
| ~~M7~~ | ~~Validate imported state structure before merge~~ | ~~Medium~~ | **Fixed** |
| ~~M8~~ | ~~Validate CORS origins, reject wildcards~~ | ~~Small~~ | **Fixed** |
| ~~M9~~ | ~~Return generic error messages; log details server-side~~ | ~~Small~~ | **Fixed** |
| ~~L1~~ | ~~Add SRI integrity attributes to CDN scripts; pin exact versions~~ | ~~Small~~ | **Partially fixed** |
| ~~L6~~ | ~~Replace `_AUTHORITY_CACHE` dict with bounded LRU cache~~ | ~~Small~~ | **Fixed** |

---

## Documentation Discrepancy — RESOLVED

`doc/Security.md` and `bin/config.py` now both reflect `127.0.0.1` as the default bind address. Apache ProxyPass handles external traffic routing.
