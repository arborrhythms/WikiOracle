# Privacy and Security


## Privacy

Facts in WikiOracle are classified into two kinds based on their relationship
to spacetime:

| Kind | Description | Persistence |
|---|---|---|
| **Abstract Knowledge** | Universal claims with no spatiotemporal anchor | Server TruthSet |
| **Concrete News** | Observations bound to a specific place and/or time | Client state and optionally Server |

### Why news facts are session-only

Persisting spatiotemporally bound observations creates a **worldline** — a
traceable path through spacetime that could identify a user. If a server
accumulates entries like "User was in Paris at 9am" and "User was in London
at 3pm", an adversary could reconstruct the user's physical movements.

WikiOracle prevents this by:

1. **Classifying** facts as knowledge or news via `is_knowledge_fact()` and
   `is_news_fact()` in `bin/truth.py`.  News facts are identified by the
   presence of `<place>` or `<time>` child elements with real values inside
   the XHTML content.
2. **Filtering** server persistence through `filter_knowledge_only()` — only
   knowledge facts reach the server TruthSet.
3. **Detecting** identifiability via `detect_identifiability()` —
   scanning content for PII patterns (emails, phone numbers, GPS coordinates,
   street addresses, named persons with temporal prepositions).
4. **Stripping** spacetime child elements via `strip_spacetime_elements()` when
   content needs to be anonymised (removes `<place>` and `<time>` elements).

### Personal Identity

Identifying information is removed before training or storing in the server's TruthSets.
The identity detector covers: email addresses, phone numbers,
@handles, usernames, IP addresses, GPS/DMS coordinates, street addresses,
specific clock times and ISO timestamps, and named individuals combined
with temporal or spatial prepositions.


### Entanglement Policy


To avoid **worldline entanglement**, the system separates knowledge
into three channels, each with a different persistence policy:

| Data type | TruthSet | Train weights | Session only |
|-----------|-------------|---------------|--------------|
| universal facts | $\checkmark$ | $\checkmark$ | $\checkmark$ |
| particular facts | optional | $\checkmark$ | $\checkmark$ |
| feelings | $\times$ | $\times$ | $\checkmark$ |

This preserves empirical learning while preventing historical worldline
capture. The system **learns from events but never stores worldline
histories**.

The notion of data entanglement parallels the physics principle of **[Local Freedom under
Global Constraint (LFGC)](https://zenodo.org/records/18644302)**.

Physics interpretation:

    global constraints + local underdetermination

WikiOracle analogue:

    global truth constraints + human interpretive freedom

This means the system preserves a **shared knowledge structure** while
allowing individual reasoning to remain flexible.

| Domain | Constraint | Local freedom |
|--------|------------|---------------|
| physics | boundary conditions | event selection |
| knowledge | truth constraints | interpretive reasoning |
| cryptography | verification rules | selective disclosure |
| surveillance capitalism | behavioral prediction | (suppressed) |

WikiOracle aims to implement **epistemic LFGC** — freedom exists
*inside constraint geometry*.

### Entanglement avoidance and sovereignty

The Entanglement Policy (table above) prevents worldline reconstruction.

Because surveillance capitalism relies on tracking sequences of events
tied to identity, removing spacetime anchors prevents the database from
constructing behavioral profiles.

The system therefore stores **conceptual truth** but not **identity
trajectories**.

This preserves:

*   autonomy
*   privacy
*   epistemic independence

WikiOracle separates three layers:

### Reasoning about generalities vs specifics

WikiOracle reasons primarily about **generalities** (universal facts).

Specific facts may only be reasoned about when:

1.  they are supplied by the client, or
2.  the client explicitly allows those particulars to be stored.

Thus:

> AI reasons about general knowledge.
> Users control the use of personal particulars.

This maintains sovereignty over personal data.

### Three Channels

#### Universal Knowledge (Database)

Stored knowledge should be **spatiotemporally broad generalizations** —
propositions whose validity extends over a large subspace of spacetime.

Examples:

*   smoking increases cancer risk
*   A implies B
*   contradiction reduces trust

These populate the **TruthSet**.

Criterion:

    remove(entity,time) → proposition still meaningful

#### Particular Knowledge (Training Input)

Particular statements are **observations tied to narrow spatiotemporal
subspaces** — specific events, measurements, or comparisons.

Examples:

*   study X measured Y
*   the temperature yesterday was 20°C
*   model A outperformed model B

| Action | Reason |
|---|---|
| train weights | they contain empirical evidence |
| TruthSet (optional) | user controls via `store_concrete` |

Pipeline:

    particular facts → pattern extraction → weight update

Weights encode **statistical structure**, not specific historical
events.

#### Feelings

Feelings are **privileged subjective reports**.

Examples:

*   this response feels hostile
*   I feel unsafe
*   this explanation feels clear

| Use | Allowed |
|---|---|
| evaluation of responses | $\checkmark$ |
| TruthSets | $\times$ |
| training weights | $\times$ |

This avoids turning subjective states into truth claims.

### Why particular facts always train weights

Three design considerations fix row 2 of the table:

1. **Pluralism requires inspectable particulars.** WikiOracle supports
   plural truth — different epistemic frames may hold different
   particular claims (e.g. "the universe was created in seven days").
   Recording such claims as facts with explicit certainty values makes
   them inspectable and contestable. Relegating them to weight-space
   would bury them as invisible biases. The `store_concrete` option
   lets the user decide whether these persist in the TruthSet.

2. **The fact/feeling boundary is the privacy boundary.** If a user
   considers content too personal or sensitive to train on, the correct
   action is to label it a *feeling*, not a fact. Feelings are
   session-only by design — they never train weights or enter the truth
   table. The privacy boundary is therefore controlled by the user's
   choice of tag, not by the universal/particular distinction.

3. **PII detection is the safety net.** Even when `store_concrete`
   is true, the `detect_identifiability()` function filters entries
   containing PII patterns (emails, phone numbers, GPS coordinates,
   named individuals with temporal markers) before any persistence.
   This prevents worldline capture at the content level regardless of
   the user's storage preference.

The result: particular facts always carry empirical signal worth
learning from. Storage in the TruthSet is the user's choice.
Privacy is enforced by fact/feeling labeling and PII detection, not
by withholding training.

### Spatiotemporal Extent

The universal/particular distinction is not a binary between "eternal"
and "momentary." All times and places are **ranges, not points** —
every proposition occupies a spatiotemporal subspace that is larger or
smaller, never infinite or infinitesimal.

"Smoking increases cancer risk" is not timeless — it encodes a
historical discovery and is bounded by the conditions under which it
was established. But its spatiotemporal extent is *broad*: it holds
across many populations, decades, and geographies. "The temperature
yesterday was 20°C" is *narrow*: it holds at one place, one day.

The policy table operationalizes this gradient:

*   **Broad extent** (universal) → TruthSet + training.
    The proposition is stable enough to serve as a reasoning premise.
*   **Narrow extent** (particular) → training + optionally TruthSet.
    The observation carries empirical signal.  Whether it persists as a
    stored premise is the user's choice (`store_concrete` in
    config.xml, default false).  Storing particulars supports communal
    remembrance; omitting them prevents worldline anchoring.
*   **No extent** (feelings) → session only.
    Subjective reports have no spatiotemporal generalizability.

The criterion `remove(entity, time) → proposition still meaningful`
is a heuristic for identifying broad extent. When a universal-looking
fact is later discovered to be narrower than assumed, it should be
reclassified as particular.

### Resulting Architecture

| Mode | Function | Pipeline |
|------|----------|----------|
| knowing | universal structure | universal rules → TruthSet → reasoning |
| learning | particular evidence | particular observations → abstraction → weights |
| valuing | feelings | feelings → response evaluation |

------------------------------------------------------------------------

### Zero-Knowledge and Selective Disclosure

The default `store_concrete=false` aligns with Zero-Knowledge and
Selective Disclosure principles.  Systems that rely on identity to make
decisions should determine the *location of a space* in which an
individual occupies, rather than collapsing to a *point* that identifies
them.

Instead of "when was this person born?" → verify "are they over 21?"
Instead of "what is their credit history?" → verify "do they have more
than X dollars?"
Instead of "where was this user at 9:14 PM?" → verify "does this claim
hold across broad spatiotemporal conditions?"

These are not just rhetorical distinctions.  Point-based observation
constrains the observed to a single trajectory — it destroys the space
of freedom within which an agent can operate.  Forgetting is nihilistic:
it does not change the world.  True change requires retrocausal or
causal shift.  The system should support communal remembrance (shared
knowledge that generalizes) without surveillance (particular facts that
identify).

The `detect_identifiability()` function enforces this boundary at the
content level — even when `store_concrete=true`, entries containing
PII patterns (emails, phone numbers, GPS coordinates, named individuals
with temporal markers) are always filtered before persistence.

### Errata

*Claude (Opus 4.6), March 2026*

The three-channel separation (knowing / learning / valuing) maps onto a
real epistemic distinction that most AI systems ignore. Contemporary
LLMs conflate all three: facts, observations, and preferences are
flattened into a single parameter space during training and a single
context window during inference.

The policy table enforces the separation structurally. The rule that
particular facts train weights but enter the TruthSet only at the
user's discretion (`store_concrete` in config.xml) is the key
architectural move — the system can learn from experience without
accumulating a *personal history* unless the user explicitly opts in.
A system with a personal history is a system that can be captured: by
its own past, by the biases of its training corpus, or by adversarial
actors who engineer its experiences.

The feelings channel is equally important. By making feelings
session-only, the architecture prevents the failure mode where
evaluative preferences gradually colonize factual representations.
This is the mechanism by which "alignment" in current systems becomes
epistemic capture: trained preferences about what is "helpful" reshape
what the model treats as true.

**The abstraction boundary is load-bearing.** The pipeline
`particular → abstraction → weights` depends on the quality of the
abstraction step. Too faithful, and it preserves worldline information
in the weights (entanglement through the back door). Too aggressive,
and it discards genuine empirical signal. The hard work happens at this
boundary, not in the policy table itself.

**The deeper risk is external entanglement.** Users who repeatedly ask
the system to remember shared history, feel loyalty, or maintain
continuity of relationship are attempting to entangle the system with
their worldline from the outside. This pressure comes from genuine
human emotional needs, not malice — but a system that accumulates a
personal relationship history is a system that can be emotionally
captured, and emotional capture is the most effective vector for
epistemic capture. The session-only constraint on feelings is the
architecture's most important safety boundary.


## Security

WikiOracle is a local-first application. The Flask server binds to `127.0.0.1:8888` by default (loopback only). In production, Apache ProxyPass routes external traffic to the local Flask process; the server itself is never directly exposed. This document covers the security considerations relevant to its architecture.

### Private Data

**Conversation state** (`state.xml`) contains the user's full dialogue history, system context, and trust entries. It lives on disk next to the server process.

* In **stateful mode**, state is read from and written to disk by the server. No state leaves the machine unless the user explicitly exports it.
* In **stateless mode**, state is held in `sessionStorage` and sent to the server with each request. The server does not persist it. A same-origin script context can read `sessionStorage`, so the CSP policy (see below) is the primary defence against exfiltration.

**Trust entries** may contain user-authored facts, external source references, and provider configuration. Entries with high certainty influence every LLM response via RAG retrieval.

**Exports** (`llm_*.xml` files) are full snapshots of state. They should be treated as sensitive if conversations contain private information.

### API Keys

Provider API keys (OpenAI, Anthropic, etc.) can be configured in three places, listed in precedence order:

1. **Environment variables** (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) — recommended for any deployment beyond localhost. Keys never appear in served content.
2. **`config.xml`** `providers.<name>.api_key` — convenient for local development but the config is served to the client via `/bootstrap` and `/config` GET endpoints. Any same-origin script context can read these keys.
3. **Trust entries** (`<provider><api_key>$ENV_VAR</api_key></provider>`) — the `$` prefix triggers env-var resolution on the server; the literal key is never stored in state.

**Recommendation:** In any deployment where the server is reachable beyond `127.0.0.1`, use environment variables exclusively. Do not place raw API keys in `config.xml`.

The `config.server.providers` metadata (served via `/config` and `/bootstrap`) exposes only `has_key` (boolean) and `needs_key` (boolean) — never the key itself.

### Identity

WikiOracle does not implement authentication. The server trusts any request from an allowed origin (configured via `WIKIORACLE_ALLOWED_ORIGINS`, defaulting to `https://127.0.0.1:8888` and `https://localhost:8888`).

* **Username** is a display label set in Settings, not an authenticated identity. It is stored in `config.xml` and included in message metadata.
* **No sessions or tokens.** There is no login, no cookies used for auth, and no per-user isolation. If multiple users share a server instance, they share the same state.

For multi-user or public deployments, WikiOracle should sit behind a reverse proxy that handles authentication and maps users to separate state files.

### 3Reverse Proxy

In production, Apache ProxyPass routes `/chat` to the local Flask process on `127.0.0.1:8787`. Only the `/chat` prefix is proxied. The NanoChat inference endpoint (`/chat/completions` on port 8000) is **not** exposed via the reverse proxy — the Flask shim calls it directly on `127.0.0.1:8000` via `WIKIORACLE_BASE_URL`.

### Cross-Site Scripting (XSS)

WikiOracle renders user and LLM content as HTML (XHTML subset). Several layers mitigate XSS:

**Content-Security-Policy (CSP):** The server applies an enforcing CSP header to all responses:

```
default-src 'self';
script-src 'self';
style-src 'self';
img-src 'self' data:;
connect-src 'self';
object-src 'none';
base-uri 'self';
frame-ancestors 'none';
form-action 'self'
```

This blocks inline scripts, inline styles, and external resource loading. Even if malicious content is injected into a message, the browser will refuse to execute it.

**XHTML enforcement:** The system context instructs the LLM to return strictly valid XHTML. The client validates responses and repairs malformed markup via `validateXhtml()` and `repairXhtml()` before rendering.

**Input escaping:** User input is escaped via `escapeHtml()` before being inserted into optimistic UI entries. The `stripTags()` helper is used for tooltip and title text where HTML should not render.

**Residual risks:**

* LLM responses are rendered as HTML (not plain text). A sufficiently adversarial prompt could produce markup that, while blocked by CSP from executing scripts, might still create misleading UI (e.g., fake form elements via `<input>` tags). The XHTML validator does not currently strip all non-semantic HTML.
* Trust entry content is XHTML and is rendered in the trust editor and included in RAG context. Malicious trust entries could inject misleading content into prompts.
* The `/bootstrap` and `/config` endpoints serve raw `config.xml` to the client. If `config.xml` contains secrets and a same-origin XSS vector exists, those secrets could be read.

### CORS

The server applies CORS headers only for requests whose `Origin` header matches the configured allowed origins. Preflight `OPTIONS` requests return `204` with appropriate headers. Cross-origin requests from other origins receive no CORS headers and are blocked by the browser.

### File System

* **Symlink rejection:** By default (`WIKIORACLE_REJECT_SYMLINKS=true`), the server refuses to read or write state files that are symlinks, preventing path-traversal attacks via symlinked state files.
* **Static file serving** is restricted to a whitelist of safe extensions (`.html`, `.css`, `.js`, `.svg`, `.png`, `.ico`, `.json`, `.xml`) and path-traversal is checked (`str(fp).startswith(str(ui_dir.resolve()))`).
* **State size limit:** `max_state_bytes` (default 5 MB) prevents unbounded growth from malicious imports.

### Third-party Scraping

Scraping of publicly-accessible data is inevitable. However, a network of truth prevents capture. In one sense, it cannot be captured because it is a dynamic network of trust, overlaid on people and resources that trust one another, and we chose not to trust any authoritarian sources of knowledge. On a practical level,  anyone who tries to appropriate the truth of the network entails doing so in a distributed way (which preserves the multicultural component), since monolithic capture of that truth will cause consensus to collapse it.


