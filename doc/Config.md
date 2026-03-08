# Configuration

WikiOracle configuration lives in `config.xml` at the project root. The file is validated by `data/config.xsd` and loaded at server startup by `bin/config.py`. A template with sensible defaults ships as `data/config.xml` — copy it to the project root and fill in your values. `config.xml` is gitignored.

The configuration has five top-level sections: [User](#1-user), [Providers](#2-providers), [Chat](#3-chat), [UI](#4-ui), and [Server](#5-server). Each section is described below with its fields, defaults, and design rationale.

## 1. User

Identity metadata attached to outgoing messages.

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | `"User"` | Display name shown in chat messages. Not an authenticated identity — see [Security.md](./Security.md) §3. |
| `uid` | string | (auto) | Persistent user GUID. Leave blank to auto-generate a deterministic GUID from the display name. Used by the online training pipeline to tag authored truth entries. |

```xml
<user>
  <name>Alice</name>
  <uid></uid>
</user>
```

## 2. Providers

LLM provider definitions. Each `<provider name="key">` block configures an upstream API endpoint. The `name` attribute is the internal lookup key; `display_name` is the label shown in the chat UI on assistant messages.

| Field | Type | Default | Description |
|---|---|---|---|
| `display_name` | string | — | Human-readable label tagging assistant messages (e.g. `chatGPT`, `claude`, `gemini`). |
| `username` | string | — | API login / email associated with the provider account. |
| `url` | URI | (built-in) | API endpoint URL. Built-in defaults exist for known providers. |
| `api_key` | string | — | API key. Prefer environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`) — see [Security.md](./Security.md) §2. |
| `default_model` | string | — | Model identifier used when no model is explicitly selected (e.g. `gpt-4o`, `claude-sonnet-4-6`). |
| `timeout` | positive int | `120` | Request timeout in seconds. |
| `streaming` | boolean | `false` | Use Server-Sent Events (SSE) for streamed responses. |

### Built-in providers

| Key | Display name | Default model | Env var for API key |
|---|---|---|---|
| `wikioracle` | oracle | nanochat | (local — no key needed) |
| `openai` | chatGPT | gpt-4o | `OPENAI_API_KEY` |
| `anthropic` | claude | claude-sonnet-4-6 | `ANTHROPIC_API_KEY` |
| `gemini` | gemini | gemini-2.5-flash | `GEMINI_API_KEY` |
| `grok` | grok | grok-3-mini | `XAI_API_KEY` |

Custom providers can be added by appending `<provider name="my_key">` blocks. Any `name` not in the built-in list creates a new provider entry.

### API key precedence

1. **Environment variable** (recommended for anything beyond localhost).
2. **`config.xml`** `api_key` field — convenient for local dev, but the config is served to the client via `/bootstrap` and `/config`.
3. **Truth entry** `<provider><api_key>$ENV_VAR</api_key></provider>` — the `$` prefix triggers server-side env-var resolution; the literal key is never stored in state.

The `/config` and `/bootstrap` endpoints expose only `has_key` (boolean) — never the key itself. See [Security.md](./Security.md) §2 for details.

## 3. Chat

Chat behaviour settings controlling how the LLM produces responses and how the online training pipeline is tuned.

| Field | Type | Default | Description |
|---|---|---|---|
| `temperature` | decimal 0.0–2.0 | `0.7` | Sampling temperature. 0.0 is deterministic; 2.0 is maximum randomness. |
| `max_tokens` | positive int | `128` | Maximum tokens in the LLM response. |
| `timeout` | positive int | `120` | Request timeout in seconds. |
| `truth_weight` | decimal 0.0–1.0 | `0.7` | Controls how much DegreeOfTruth (DoT) gates the online training learning rate, and whether truth entries are sent to the provider as RAG context. See [§Truth weight and RAG](#truth-weight-and-rag) below. |
| `truth_max_entries` | positive int | `1000` | Maximum number of entries in the server truth table before trimming. Entries with `\|trust\|` closest to 0.0 are removed first. Range: 100–10000. |
| `store_particulars` | boolean | `false` | Store particular (spatiotemporally-bound) facts in the server truth table. When false, only universal facts persist. Client-side override for the server's `store_particulars`. See [Ethics.md](./Ethics.md) §Entanglement Policy. |
| `url_fetch` | boolean | `false` | Allow the assistant to fetch and incorporate content from URLs referenced in the conversation. |
| `confirm_actions` | boolean | `false` | Prompt the user for confirmation before destructive operations (deletes, merges). |

```xml
<chat>
  <temperature>0.7</temperature>
  <max_tokens>128</max_tokens>
  <timeout>120</timeout>
  <truth_weight>0.7</truth_weight>
  <truth_max_entries>1000</truth_max_entries>
  <store_particulars>false</store_particulars>
  <url_fetch>false</url_fetch>
  <confirm_actions>false</confirm_actions>
</chat>
```

### Truth weight and RAG

The `truth_weight` field (0.0–1.0) replaces the former boolean `rag` flag.  It serves a dual purpose:

1. **RAG delivery gate**: When `truth_weight > 0`, the full truth table — facts, feelings, references, operators, authorities, and providers — is assembled into the provider bundle and sent to the UI-selected provider.  When `truth_weight = 0`, no truth is sent (equivalent to the former `rag: false`).

2. **Training LR modulation**: During online training, `truth_weight` controls how much DoT gates the learning rate.  See [Training.md](./Training.md) §Training Algorithm for the formula.

**Legacy migration**: The former `rag` boolean is automatically migrated: `rag: true` → `truth_weight: 0.7`, `rag: false` → `truth_weight: 0.0`.  This migration runs in both the client (`client/config.js`) and server (`bin/response.py`).

## 4. UI

Client-side defaults for the browser interface. These are persisted in `sessionStorage` and can be changed at runtime via the Settings panel.

| Field | Type | Default | Description |
|---|---|---|---|
| `default_provider` | string | `"wikioracle"` | Provider key selected on startup. Must match a key in the `<providers>` section. |
| `layout` | `horizontal` \| `vertical` \| `flat` | `"horizontal"` | Layout mode. `horizontal` = side-by-side tree and chat panels. `vertical` = stacked. `flat` = single-panel chat only. |
| `theme` | `system` \| `light` \| `dark` | `"system"` | Colour theme. `system` follows the OS preference. |
| `splitter_pct` | integer 0–100 | `0` | Tree/chat panel splitter position as a percentage. 0 collapses the tree panel. |
| `swipe_nav_horizontal` | boolean | `true` | Enable horizontal swipe gestures (left/right) to navigate between sibling conversation branches. |
| `swipe_nav_vertical` | boolean | `false` | Enable vertical swipe gestures (up/down) to navigate between sibling branches. |

```xml
<ui>
  <default_provider>wikioracle</default_provider>
  <layout>horizontal</layout>
  <theme>system</theme>
  <splitter_pct>0</splitter_pct>
  <swipe_nav_horizontal>true</swipe_nav_horizontal>
  <swipe_nav_vertical>false</swipe_nav_vertical>
</ui>
```

## 5. Server

Runtime parameters. These values serve as defaults and are typically overridden via CLI flags at startup.

| Field | Type | Default | Description |
|---|---|---|---|
| `stateless` | boolean | `false` | Stateless mode — no disk writes. Equivalent to `--stateless` CLI flag. See [Entanglement.md](./Entanglement.md). |
| `url_prefix` | string | `""` | URL path prefix prepended to all routes (e.g. `/chat`) for reverse-proxy deployments. Equivalent to `--url-prefix`. |
| `server_id` | string | `"wikioracle"` | Stable identifier for this server instance. Used as the `source` field in server truth entries returned to the client in debug mode. Defaults to `"wikioracle"`. |
| `online_training` | section | — | Online learning subsystem. See [§5a](#5a-online-training) below. |
| `allowed_urls` | section | — | URL whitelist for authority/provider fetches. See [§5b](#5b-allowed-urls) below. |

### 5a. Online training

Controls the continuous learning pipeline (Stages 2–4). See [Training.md](./Training.md) for the full design.

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | **Master switch.** When false, the entire post-response pipeline — DegreeOfTruth computation, truth table merge, PII filtering, symmetry checking, and NanoChat training — is skipped. See [§Behavior when disabled](#behavior-when-online-training-is-disabled) below. |
| `truth_corpus_path` | string | `"data/truth.xml"` | Filesystem path to the server truth table (XML). Relative paths resolve from the project root. |
| `alpha_base` | decimal | `0.01` | Base learning rate for online training weight updates. |
| `alpha_min` | decimal | `0.001` | Minimum learning rate floor. The adaptive scheduler never reduces below this. |
| `alpha_max` | decimal | `0.1` | Maximum learning rate ceiling. The adaptive scheduler never exceeds this. |
| `merge_rate` | decimal | `0.1` | Slow-moving exponential average rate for merging newly learned entries into the canonical truth corpus. |
| `device` | `auto` \| `cpu` \| `cuda` | `"cpu"` | Compute device for training operations. `auto` selects the best available. |
| `dissonance_enabled` | boolean | `true` | Enable cognitive dissonance detection. The trainer identifies and penalises contradictions between new inputs and established truth entries. |
| `operators_dynamic_enabled` | boolean | `true` | Load custom operators. Custom operators extend the training pipeline with user-defined transformations. |
| `store_particulars` | boolean | `false` | When true, particular facts (narrow spatiotemporal extent) are stored in the truth table alongside universal facts (broad extent). When false, only universals persist — consistent with Zero-Knowledge / Selective Disclosure principles. Particular facts always train weights regardless of this setting; the fact/feeling distinction is the privacy boundary. See [Ethics.md](./Ethics.md) §Entanglement Policy. |
| `truth_symmetry` | boolean | `true` | Enforce Truth Symmetry. Claims involving value judgements are checked for asymmetric harm under identity exchange before admission to the truth table. See [Ethics.md](./Ethics.md) §5–8. |
| `warmup_steps` | positive int | `50` | Sigmoid warmup midpoint for the annealing schedule. The first ~2×`warmup_steps` interactions ramp from near-zero to full training strength, preventing early corruption. See [Training.md](./Training.md) §Sigmoid Warmup. |
| `grad_clip` | decimal > 0 | `1.0` | Maximum gradient norm for `clip_grad_norm_()`. Prevents catastrophic single-step weight changes. Lower values are more conservative. See [Training.md](./Training.md) §Gradient Clipping. |
| `anchor_decay` | decimal 0.0–1.0 | `0.001` | EMA blend-back rate toward checkpoint weights after each training step. Higher values pull the model back more aggressively toward its initial state. Modulated by `truth_weight`: `anchor_effective = anchor_decay × truth_weight`. See [Training.md](./Training.md) §EMA Weight Anchoring. |
| `truth_max_entries` | positive int | `1000` | Maximum server truth table entries before trimming. Entries with `\|trust\|` closest to 0.0 are removed first during the merge stage. Also configurable per-user via `chat.truth_max_entries`. |

```xml
<online_training>
  <enabled>false</enabled>
  <truth_corpus_path>data/truth.xml</truth_corpus_path>
  <alpha_base>0.01</alpha_base>
  <alpha_min>0.001</alpha_min>
  <alpha_max>0.1</alpha_max>
  <merge_rate>0.1</merge_rate>
  <device>cpu</device>
  <dissonance_enabled>true</dissonance_enabled>
  <operators_dynamic_enabled>true</operators_dynamic_enabled>
  <store_particulars>false</store_particulars>
  <truth_symmetry>true</truth_symmetry>
  <warmup_steps>50</warmup_steps>
  <grad_clip>1.0</grad_clip>
  <anchor_decay>0.001</anchor_decay>
  <truth_max_entries>1000</truth_max_entries>
</online_training>
```

#### Behavior when online training is disabled

When `enabled` is `false` (the default), the engine effectively treats all incoming facts as feelings. The Sensation preprocessor (`bin/sensation.py`) still classifies sentences into `<fact>` and `<feeling>` tags at the message level, but the entire post-response pipeline is skipped:

* **No DegreeOfTruth** is computed.
* **No truth merge** occurs — facts from conversation are never promoted into the truth table.
* **No PII filtering** or **symmetry checking** runs (there is nothing to filter).
* **No NanoChat training step** is dispatched.

In this mode, facts carry no more lasting weight than feelings. They are tagged in the XML for display purposes, but they are ephemeral — they do not accumulate, persist, or influence future responses via RAG. This is the safe default: the system functions as a stateless chat proxy until the operator explicitly enables truth acquisition.

### 5b. Allowed URLs

URL prefixes permitted for outbound HTTP(S) requests made by the server during authority lookups and dynamic provider fetches. Only URLs whose prefix matches one of these entries are allowed. `file://` URLs are always blocked unless explicitly whitelisted.

```xml
<allowed_urls>
  <url>https://api.openai.com/</url>
  <url>https://api.anthropic.com/</url>
  <url>https://generativelanguage.googleapis.com/</url>
  <url>https://api.x.ai/</url>
  <url>https://en.wikipedia.org/</url>
  <url>https://wikiOracle.org/</url>
  <url>https://127.0.0.1:</url>
  <url>https://localhost:</url>
  <url>http://127.0.0.1:</url>
</allowed_urls>
```

See [Security.md](./Security.md) §6 and [Authority.md](./Authority.md) for the security rationale.

## Environment variables

Runtime configuration can also be set via environment variables. These override `config.xml` values where applicable.

| Variable | Default | Purpose |
|---|---|---|
| `WIKIORACLE_STATE_FILE` | `state.xml` | Path to local state file (WikiOracle State XML). |
| `WIKIORACLE_BASE_URL` | `http://127.0.0.1:8000` | Upstream NanoChat-compatible base URL. |
| `WIKIORACLE_API_PATH` | `/chat/completions` | Upstream chat endpoint path appended to base URL. |
| `WIKIORACLE_BIND_HOST` | `127.0.0.1` | Host to bind the Flask server to. |
| `WIKIORACLE_BIND_PORT` | `8888` | Port for the Flask server. |
| `WIKIORACLE_SSL_CERT` | `~/.ssl/<hostname>.pem` | TLS certificate path. |
| `WIKIORACLE_SSL_KEY` | `~/.ssl/<hostname>-key.pem` | TLS private key path. |
| `WIKIORACLE_TIMEOUT_S` | `120` | Network timeout (seconds) for provider requests. |
| `WIKIORACLE_MAX_STATE_BYTES` | `20000000` | Hard upper bound for serialized state size. |
| `WIKIORACLE_MAX_CONTEXT_CHARS` | `40000` | Context rewrite cap for merge appendix generation. |
| `WIKIORACLE_REJECT_SYMLINKS` | `true` | Refuse symlinked state files. |
| `WIKIORACLE_AUTO_MERGE_ON_START` | `true` | Auto-import `llm_*` files at startup. |
| `WIKIORACLE_AUTO_CONTEXT_REWRITE` | `false` | Enable delta-based context append during merges. |
| `WIKIORACLE_MERGED_SUFFIX` | `.merged` | Suffix applied to files after successful import. |
| `WIKIORACLE_ALLOWED_ORIGINS` | `https://127.0.0.1:8888,...` | Comma-separated CORS allowed origins. |
| `WIKIORACLE_API_TOKEN` | (empty) | Bearer token for endpoint auth (empty = no auth). |
| `WIKIORACLE_STATELESS` | (unset) | Set truthy to disable all writes and use in-memory state. |
| `WIKIORACLE_URL_PREFIX` | (unset) | Optional reverse-proxy path prefix. |
| `OPENAI_API_KEY` | — | OpenAI API key. |
| `ANTHROPIC_API_KEY` | — | Anthropic API key. |
| `GEMINI_API_KEY` | — | Google Gemini API key. |
| `XAI_API_KEY` | — | xAI (Grok) API key. |

## OpenClaw Plugin Config

When using WikiOracle as an OpenClaw provider, the TypeScript extension
at `openclaw/extensions/wikioracle/` is configured via OpenClaw's
plugin config system.  Add the following to your OpenClaw config file
(`~/.openclaw/config.json5` or project-level):

```json5
{
  plugins: {
    entries: ["wikioracle"],
    wikioracle: {
      woPath: "/absolute/path/to/WikiOracle/bin/wo",
      serverUrl: "https://127.0.0.1:8888",
      insecure: true,
      stateful: true,
      stateFile: "state.xml",
      token: "optional-bearer-token",
    },
  },
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `woPath` | string | `"../bin/wo"` | Absolute or relative path to WikiOracle's `bin/wo` CLI. Relative paths resolve from the OpenClaw working directory. |
| `serverUrl` | string | `"https://127.0.0.1:8888"` | WikiOracle server URL. |
| `insecure` | boolean | `true` | Skip TLS certificate verification (`bin/wo -k`). Set to `false` for production deployments with valid certificates. |
| `stateful` | boolean | `true` | Use stateful mode (server owns session state). When `false`, state is serialized to the local file specified by `stateFile`. |
| `stateFile` | string | `"state.xml"` | Local state file path for stateless mode (`bin/wo -f`). Ignored in stateful mode. |
| `token` | string | (none) | Optional bearer token for WikiOracle API authentication (`bin/wo -t`). |

The full JSON Schema for the plugin config is defined in
`openclaw/extensions/wikioracle/openclaw.plugin.json`.

The extension registers three capabilities:

1. **Provider** (`wikioracle`) — selectable in OpenClaw's provider list
2. **Command** (`/wo <message>`) — direct CLI access from any channel
3. **Tool** (`wikioracle_query`) — available to OpenClaw agents

See [Training.md](./Training.md) §OpenClaw Integration for the
message flow and training pipeline details.

## CLI flags

```
python bin/wikioracle.py [--config PATH] [--debug] [--stateless] [--no-ssl] [--url-prefix PREFIX] [serve | merge FILE...]
```

| Flag | Description |
|---|---|
| `--config PATH` | Path to `config.xml` (default: project root). |
| `--debug` | Enable verbose debug logging. |
| `--stateless` | Run in stateless mode (no disk writes). |
| `--no-ssl` | Serve over plain HTTP (skip TLS). |
| `--url-prefix PREFIX` | URL path prefix (e.g. `/chat`) for reverse-proxy deployments. |
| `serve` | Run the Flask shim server (default). |
| `merge FILE...` | Merge incoming state files into the current state. |

## Schema

The XML schema is defined in `data/config.xsd`. Use it for IDE validation and autocompletion:

```xml
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xsi:noNamespaceSchemaLocation="config.xsd">
  ...
</config>
```
