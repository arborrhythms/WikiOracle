# Privacy and Security

## Data Ownership and Flow

WikiOracle is local-first, but "local-first" does not mean that no content is ever transmitted. The selected provider receives the prompt material required for a response, and a stateless Flask deployment receives the state/config supplied with each request.

| Data | Stateful mode | Stateless mode | Upstream exposure |
|---|---|---|---|
| Conversations | Persisted in local `state.xml`; `/chat` returns a selected delta | Browser/CLI sends authoritative state and receives full updated state | Selected path/history is included in provider prompts |
| Client TruthSet | Persisted with state; client may override truth on a chat turn | Sent with authoritative state | Enabled truth sources enter the provider bundle according to truth weight |
| Server truth corpus | Optional `data/truth.xml` on the writable server | Disabled | Used for DoT/learning policy, not sent as a raw file |
| Server policy/provider definitions | Loaded from `config.xml` | Returned as a client-safe runtime config | Effective prompts, endpoint, and selected model govern provider calls |
| Client API keys | Project config and browser storage | Browser storage/runtime config | Used by the Flask shim to authenticate provider calls |
| Dropbox OAuth tokens | Flask session | Flask session | Sent to Dropbox only |
| Encryption password | One save/load request | One save/load request | Used in memory for AES ZIP operations; not persisted by WikiOracle |

Users should assume that any conversation text, truth source, or attachment selected for a provider request can leave the local machine and be governed by that provider's own retention policy.

## Spatiotemporal Privacy

Facts are classified by their relationship to spacetime.

| Kind | Description | Default persistence policy |
|---|---|---|
| Abstract knowledge | Broad claim without a concrete place/time anchor | Eligible for server TruthSet persistence |
| Concrete news | Observation tied to a place and/or time | Remains in client state; excluded from server truth unless `store_concrete=true` |
| Feeling | Subjective/non-truth-evaluable expression | May remain in client state; excluded from server truth and training |

Persisting concrete observations can create a **worldline**: a sequence of places and times from which a person's movement or identity can be reconstructed.

| Control | Implementation | Purpose |
|---|---|---|
| Knowledge/news classification | `is_knowledge_fact()`, `is_news_fact()` | Detect real `<place>`/`<time>` content |
| Knowledge-only filter | `filter_knowledge_only()` | Exclude concrete facts when `store_concrete=false` |
| Identifiability detection | `detect_identifiability()` | Find emails, phones, handles, IPs, coordinates, addresses, specific times, and person/place-time patterns |
| Spacetime removal | `strip_spacetime_elements()` | Remove place/time child elements when anonymization is required |
| Truth symmetry | `detect_asymmetric_claim()` | Reject selected asymmetric value claims before server-truth merge |

See [Freedom](./Freedom.md) for the Entanglement Policy and its universal/particular/feeling channels.

## Credentials

### Provider API Keys

| Credential source | Runtime and exposure policy |
|---|---|
| **Client provider key** | `config.client.providers.<name>.api_key` is the canonical main-provider key in both runtime contracts. It is visible to same-origin client code and stored in browser config storage, so use it only when that browser exposure is acceptable. |
| **Dynamic provider key** | `<provider><api_key>...` is used only for that dynamic expert. It may be a literal or an allowlisted `file://` reference; avoid raw keys in portable or shared state. |
| **Server environment** | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY` are last-resort fallbacks for matching dynamic-provider URLs. They are not served directly and are preferable for server-controlled dynamic experts. |
| **Legacy server provider key** | `server.providers.api_key` is ignored by the canonical provider parser/writer and removed from the client-safe server projection. Do not rely on it. |

`/config` and `/bootstrap` remove Dropbox credentials and server-side provider keys, but they intentionally preserve `client.providers` because the browser owns those settings. A same-origin compromise can therefore read client API keys.

### Dropbox Credentials

Dropbox app credentials live on `<server><dropbox app_key="..." app_secret="..."/>` and are removed from the client-safe config. OAuth access/refresh tokens live in the signed Flask session. Session cookies use `HttpOnly`, `Secure` when TLS is active, and `SameSite=Lax`.

Encrypted uploads use AES-256 ZIP archives through `pyzipper`. State and config are separate archives; state-only sharing can generate a Dropbox link plus decryption material encoded as an authority QR. Sharing that QR is equivalent to sharing the encrypted state and its decryption key.

## Authentication and Request Controls

| Control | Default | Behavior |
|---|---|---|
| Bind interface | `127.0.0.1:8888` | Flask is loopback-only unless explicitly reconfigured |
| TLS | Enabled | Creates/uses a local certificate unless `--no-ssl` is passed |
| Bearer authentication | Disabled when token is empty | `WIKIORACLE_API_TOKEN` protects non-public endpoints |
| CSRF header | Required | Every POST must include `X-Requested-With: WikiOracle` |
| CORS | Local HTTPS origins | Headers are emitted only for an allowlisted origin |
| Rate limiting | 30 RPM for chat; 120 RPM default | In-process sliding window keyed by IP and path |
| Input length | 50,000 characters | Oversized chat messages are rejected |
| Request/state size | 20,000,000 bytes | Flask request cap and state-file guard |
| Prompt-injection guard | Enabled | `guard_input()` rejects detected injection patterns before provider calls |

Public or multi-user deployments should place WikiOracle behind an authenticated reverse proxy, isolate state/config per user, set a bearer token and explicit session secret, use a valid TLS certificate, and narrow both CORS and outbound URL allowlists.

## Reverse Proxy and Provider Isolation

The production pattern terminates TLS at a reverse proxy and forwards the configured WikiOracle route prefix to Flask on loopback. Local NanoChat (port 8000 by default) and BasicModel (port 8001 by default) remain direct Flask-to-provider dependencies and should not be exposed merely because the browser UI is public.

The same route prefix must be configured consistently in the proxy, Flask (`--url-prefix`/`WIKIORACLE_URL_PREFIX`), browser base URL, and CLI/OpenClaw clients.

## Browser Content Security

WikiOracle renders a constrained XHTML/HTML surface. The browser applies multiple defenses.

| Layer | Current control |
|---|---|
| Content Security Policy | Self-only scripts/styles/connections; data images; no objects, framing, external base, or form targets |
| Sanitization | DOMPurify-based `sanitizeHtml()` plus XHTML validation/repair |
| User input | Escaped before optimistic rendering |
| Plain-text labels | Tag stripping/escaping for titles, tooltips, and status text |
| Static assets | Only allowlisted extensions under the resolved `client/` directory |

Residual risk remains because model and TruthSet content is rendered and also reused in prompts. Malicious but non-script markup can imitate interface elements, and hostile truth content can attempt prompt injection. CSP limits code execution; it does not determine whether rendered claims are honest.

## File-System Safety

| Control | Behavior |
|---|---|
| State symlinks | Rejected by default (`WIKIORACLE_REJECT_SYMLINKS=true`) |
| State writes | Temporary file, flush, `fsync`, atomic replacement |
| Config writes | Atomic replacement with owner-only `0600` permissions |
| Imports | Filenames/path components are constrained; processed files receive the configured suffix |
| Dynamic API-key files | Restricted to the allowlisted data directory; symlinks and traversal are rejected |
| Authority fetching | Scheme/prefix allowlist, response-size cap, entry cap, refresh cache, and no recursive authority chain |

## Operational Checklist

| Deployment | Minimum posture |
|---|---|
| Local single-user | Keep loopback bind, use TLS, protect local state/config/browser profile, and do not share raw credentials |
| LAN | Valid TLS, bearer token, explicit allowed origins, strong session secret, per-user state separation |
| Public stateless | Reverse-proxy authentication, no config writes, strict outbound allowlist, no client keys unless browser exposure is accepted, provider-retention review |
| Dropbox sharing | Strong unique archive password; share authority QR only with intended recipients; revoke Dropbox links when no longer needed |

Distribution reduces the risk of one epistemic authority capturing the whole network, but it does not replace ordinary application security, credential hygiene, or provider privacy review.
