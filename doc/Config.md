# Config

WikiOracle configuration is XML loaded by `bin/config.py` and described by `data/config.xsd`. `data/config.xml` is the shipped baseline; an optional project-root `config.xml` is deep-merged over it. Scalars and lists in the override replace baseline values, while nested dictionaries merge recursively.

## Canonical Structure

| Section | Authority | Contents |
|---|---|---|
| `<server>` | Operator/server | Runtime mode, truth policy, evaluation/training defaults, URL allowlist, Dropbox app credentials, provider definitions, and shared prompts |
| `<client>` | Browser/client | UI preferences, per-session evaluation choices, provider/model selection, storage preference, and per-provider API keys |

```xml
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xsi:noNamespaceSchemaLocation="config.xsd">
  <server>...</server>
  <client>...</client>
</config>
```

The browser receives a client-safe projection. Server-only Dropbox attributes and any provider key found in `server.providers` are removed; configured provider definitions are augmented with the model choices used by the UI. Values under `client.providers`, including client-owned API keys, remain browser-visible.

## Server

### Identity and Runtime

| Field | Type | Shipped value | Description |
|---|---|---|---|
| `server_name` | String | `WikiOracle` | Human-readable server label; optional in the XSD |
| `server_id` | String | `wikioracle` | Persistent server identity; a missing ID is generated in writable mode |
| `stateless` | Boolean | `true` | Disable state/config writes and require authoritative state/config on `/chat` |
| `url_prefix` | String | Empty | Prefix applied to every route for reverse-proxy deployments |
| `truthset` | Section | See below | Truth admission and grounding policy |
| `evaluation` | Section | See below | Provider evaluation defaults |
| `training` | Section | See below | Optional continuous-learning defaults |
| `allowed_urls` | Section | See below | Outbound provider/authority allowlist |
| `dropbox` | Element | Empty credentials | Server-only Dropbox OAuth app attributes |
| `providers` | Section | Six definitions | Shared prompt fields and upstream provider definitions |

Runtime precedence for the stateless flag is CLI `--stateless`, then `server.stateless`, then `WIKIORACLE_STATELESS`. The route prefix uses CLI `--url-prefix`, then `WIKIORACLE_URL_PREFIX`.

### TruthSet Policy

| Field | Type | Default | Description |
|---|---|---:|---|
| `truth_symmetry` | Boolean | `true` | Check value claims for asymmetric harm under identity exchange |
| `store_concrete` | Boolean | `false` | Permit spatiotemporally bound facts in the server TruthSet |
| `truth_weight` | Decimal 0-1 | `0.7` | Controls whether/how strongly TruthSet sources enter the prompt and how strongly DoT gates online learning |

| `truth_weight` | RAG behavior | Online-learning behavior |
|---:|---|---|
| `0.0` | Truth sources are omitted | DoT does not gate the learning rate; EMA anchor effect is zero |
| `0.7` | Default weighted grounding | DoT substantially modulates learning and anchoring |
| `1.0` | Full grounding | Learning is fully DoT-gated and uses the configured anchor strength |

### Evaluation Defaults

| Field | Type | Default | Description |
|---|---|---:|---|
| `temperature` | Decimal 0-2 | `0.7` | Sampling temperature |
| `max_tokens` | Positive integer | `128` | Maximum response tokens requested from the main provider |
| `timeout` | Positive integer | `120` | Provider request timeout in seconds |
| `url_fetch` | Boolean | `false` | Allow URL content to be incorporated during evaluation |
| `thought_free` | Boolean | `false` | Optional server default for non-discursive output; the client has its own preference field |

The request can override provider, model, temperature, URL fetching, thought-free mode, and selected truth/training controls. Values are clamped or normalized in `process_chat()`.

### Training

Training is disabled by default and is also unavailable in stateless mode.

| Field | Type | Default | Description |
|---|---|---:|---|
| `enabled` | Boolean | `false` | Master switch for post-response truth merge and online training |
| `truth_corpus_path` | String | `data/truth.xml` | Server truth corpus path |
| `truth_max_entries` | Integer 100-10000 | `1000` | Maximum corpus entries before low-information trimming |
| `alpha_base` | Decimal | `0.01` | Base learning rate |
| `alpha_min` | Decimal | `0.001` | Minimum learning-rate floor |
| `alpha_max` | Decimal | `0.1` | Maximum learning-rate ceiling |
| `merge_rate` | Decimal | `0.1` | Moving-average rate when client truth updates an existing server entry |
| `device` | `auto`, `cpu`, `cuda` | `cpu` | Online-training device |
| `dissonance_enabled` | Boolean | `true` | Enable contradiction/dissonance handling |
| `operators_dynamic_enabled` | Boolean | `true` | Enable dynamic operator processing |
| `warmup_steps` | Positive integer | `50` | Midpoint of the sigmoid training warmup |
| `grad_clip` | Decimal > 0 | `1.0` | Maximum gradient norm |
| `anchor_decay` | Decimal 0-1 | `0.001` | EMA pull toward checkpoint parameters |

When `enabled=false`, the post-response DegreeOfTruth, server-truth merge, and online-training stages are skipped. Message-level fact/feeling parsing and response rendering still operate.

### Allowed URLs

`allowed_urls` is a repeated prefix allowlist used for authority lookups and dynamic provider endpoints.

| URL class | Rule |
|---|---|
| HTTPS | Allowed only when the full URL begins with a configured prefix |
| Loopback HTTP | Allowed only for `127.0.0.1` or `localhost`, and only when prefix-matched |
| `file://` | Denied unless an explicit `file://` prefix is allowlisted; API-key file resolution is additionally confined to its data allowlist and rejects symlinks/traversal |
| Other schemes | Denied |

### Dropbox

```xml
<dropbox app_key="..." app_secret="..."/>
```

| Attribute | Required by XSD | Exposure |
|---|---:|---|
| `app_key` | Yes | Server only; removed from `/config` and `/bootstrap` |
| `app_secret` | Yes | Server only; removed from `/config` and `/bootstrap` |

Dropbox OAuth tokens are stored in the Flask session cookie context; the encryption password supplied for a save/load operation is not stored in configuration or session state.

## Provider Definitions

Provider definitions live under `server.providers`. The element uses an explicit `<name>` child, not a `name` attribute.

### Shared Prompt Fields

| Field | Type | Purpose |
|---|---|---|
| `context` | XHTML | Shared system context |
| `output` | String | Output-format instructions |
| `truth_context` | XHTML | Role context for truth-only beta providers |
| `conversation_context` | XHTML | Role context for conversational beta providers |

### Provider Fields

| Field | Required | Description |
|---|---:|---|
| `name` | Yes | User-facing registry key used by client selection |
| `type` | Yes | Adapter type: `wikioracle`, `openai`, `anthropic`, `gemini`, `grok`, or `openrouter` |
| `username` | No | Account/display metadata |
| `url` | Yes | Upstream endpoint |
| `model` | Yes | Server default model |
| `timeout` | Yes | Per-provider timeout |
| `streaming` | Yes | Streaming capability flag |
| `api_key` | No in schema | Legacy server-side position; canonical client keys belong under `client.providers` and the server parser omits this field from definitions |

```xml
<providers>
  <context>Return strictly valid XHTML.</context>
  <output>Use conversation, fact, and feeling elements.</output>
  <provider>
    <name>OpenAI</name>
    <type>openai</type>
    <username>you@example.com</username>
    <url>https://api.openai.com/v1/chat/completions</url>
    <model>gpt-4o</model>
    <timeout>120</timeout>
    <streaming>false</streaming>
  </provider>
</providers>
```

### Shipped Providers

| Name | Type | Shipped model | Endpoint family |
|---|---|---|---|
| WikiOracle | `wikioracle` | `nanochat` | Local OpenAI-compatible endpoint |
| OpenAI | `openai` | `gpt-4o` | OpenAI chat completions |
| Anthropic | `anthropic` | `claude-sonnet-4-6` | Anthropic messages |
| Gemini | `gemini` | `gemini-2.5-flash` | Google Generative Language |
| Grok | `grok` | `grok-3-mini` | xAI OpenAI-compatible endpoint |
| OpenRouter | `openrouter` | `google/gemma-3-4b-it:free` | OpenRouter chat completions |

The model selector also receives a code-maintained list of supported choices from `_PROVIDER_MODELS`; the configured `model` remains the fallback for each provider.

## Client

### Client Fields

| Field | Type | Default | Description |
|---|---|---:|---|
| `storage` | Element | Empty | Optional `state_key` attribute reserved for client storage selection |
| `temperature` | Decimal 0-2 | `0.7` | Client evaluation preference |
| `url_fetch` | Boolean | `false` | Client URL-fetch preference |
| `thought_free` | Boolean | `false` | Client thought-free preference |
| `ui` | Section | See below | Browser layout and interaction preferences |
| `providers` | Section | See below | Provider/model selection and API keys |

### UI Preferences

| Field | Type | Default | Description |
|---|---|---:|---|
| `layout` | `horizontal`, `vertical` | `horizontal` | Main panel arrangement |
| `theme` | `system`, `light`, `dark` | `light` | Color theme |
| `divider_pos` | Integer 0-100 | `0` | Saved tree/chat divider position |
| `swipe_nav_horizontal` | Boolean | `true` | Horizontal swipe navigation |
| `swipe_nav_vertical` | Boolean | `false` | Vertical swipe navigation |
| `confirm_actions` | Boolean | `false` | Confirm destructive operations |

### Client Provider Settings

| Field | Type | Purpose |
|---|---|---|
| `default_provider` | String | Selected provider name; must match a server provider definition |
| `default_model` | String | Selected model override |
| `provider/name` | String | Provider name associated with a key |
| `provider/api_key` | String | Client-owned key for that provider |

```xml
<client>
  <temperature>0.7</temperature>
  <url_fetch>false</url_fetch>
  <thought_free>false</thought_free>
  <ui>
    <layout>horizontal</layout>
    <theme>light</theme>
    <divider_pos>0</divider_pos>
    <swipe_nav_horizontal>true</swipe_nav_horizontal>
    <swipe_nav_vertical>false</swipe_nav_vertical>
    <confirm_actions>false</confirm_actions>
  </ui>
  <providers>
    <default_provider>WikiOracle</default_provider>
    <default_model>nanochat</default_model>
    <provider>
      <name>WikiOracle</name>
      <api_key>...</api_key>
    </provider>
  </providers>
</client>
```

### Runtime Selection Precedence

| Setting | Resolution order |
|---|---|
| Provider | Request `config.provider` -> `client.providers.default_provider` |
| Model | Request `config.model` -> `client.providers.default_model` -> selected server provider `model` |
| Main-provider API key | Request/runtime client provider key -> loaded `client.providers.<name>.api_key` |
| Dynamic truth-provider key | Embedded provider-entry key (literal or allowlisted `file://`) -> matching configured provider key -> selected provider-family environment fallback where implemented |
| Temperature | Request `config.temp` -> `server.evaluation.temperature`, clamped to 0-2 |

The browser stores the normalized config in both `sessionStorage` and `localStorage` for tab-close durability. In stateful mode, `POST /config` accepts only the incoming `client` section; the server section remains authoritative on disk. Stateless servers reject config writes.

## Runtime Environment Variables

These variables configure the Flask process and its transport. XML still supplies provider definitions and model defaults.

| Variable | Default | Purpose |
|---|---|---|
| `WIKIORACLE_STATE_FILE` | `state.xml` | Canonical state path |
| `WIKIORACLE_BASE_URL` | `http://127.0.0.1:8000` | Local WikiOracle/NanoChat base URL fallback |
| `WIKIORACLE_API_PATH` | `/chat/completions` | Local upstream path |
| `WIKIORACLE_BIND_HOST` | `127.0.0.1` | Flask bind interface |
| `WIKIORACLE_BIND_PORT` | `8888` | Flask bind port |
| `WIKIORACLE_SSL_CERT` | Host-derived path under `~/.ssl` | TLS certificate |
| `WIKIORACLE_SSL_KEY` | Host-derived path under `~/.ssl` | TLS private key |
| `WIKIORACLE_TIMEOUT_S` | `120` | General provider timeout |
| `WIKIORACLE_MAX_STATE_BYTES` | `20000000` | Flask request/state size cap |
| `WIKIORACLE_MAX_CONTEXT_CHARS` | `40000` | Merge-context rewrite cap |
| `WIKIORACLE_MAX_INPUT_LEN` | `50000` | Chat-message character cap |
| `WIKIORACLE_REJECT_SYMLINKS` | `true` | Reject symlinked state files |
| `WIKIORACLE_AUTO_MERGE_ON_START` | `true` | Import adjacent `llm_*.xml/.json` files at startup |
| `WIKIORACLE_AUTO_CONTEXT_REWRITE` | `false` | Append merge deltas to context |
| `WIKIORACLE_MERGED_SUFFIX` | `.merged` | Suffix for imported files |
| `WIKIORACLE_ALLOWED_ORIGINS` | Local HTTPS origins | CORS allowlist |
| `WIKIORACLE_API_TOKEN` | Empty | Optional bearer token |
| `WIKIORACLE_SESSION_SECRET` | Derived from state path | Flask session signing secret |
| `WIKIORACLE_RATE_LIMIT_CHAT` | `30` | Chat requests per minute per IP; `0` disables the chat-specific limit |
| `WIKIORACLE_RATE_LIMIT_DEFAULT` | `120` | Default requests per minute per IP |
| `WIKIORACLE_STATELESS` | `false` fallback | Stateless fallback when CLI/XML do not decide |
| `WIKIORACLE_URL_PREFIX` | Empty | Route-prefix fallback |

`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY` are last-resort fallbacks for matching dynamic truth-provider URLs. Main provider calls use the canonical `client.providers` key flow.

## OpenClaw Extension

The `openclaw` submodule includes `extensions/wikioracle`, which invokes `bin/wo` and registers a provider, `/wo` command, and `wikioracle_query` tool.

| Field | Default | Purpose |
|---|---|---|
| `woPath` | `../bin/wo` | WikiOracle CLI path |
| `serverUrl` | `https://127.0.0.1:8888` | Flask server URL |
| `insecure` | `true` | Skip verification for the local self-signed certificate |
| `stateful` | `true` | Use the server-owned state contract |
| `stateFile` | `state.xml` | Local file used for stateless state or stateful logging |
| `token` | None | Optional bearer token |

## CLI Flags

```text
python bin/wikioracle.py [--config PATH] [--debug] [--stateless]
                         [--no-ssl] [--url-prefix PREFIX]
                         [serve | merge FILE...]
```

| Flag/command | Purpose |
|---|---|
| `--config PATH` | Load a specified configuration file |
| `--debug` | Enable verbose diagnostic output |
| `--stateless` | Disable writes and require client-owned request state/config |
| `--no-ssl` | Serve plain HTTP instead of local TLS |
| `--url-prefix PREFIX` | Prefix all application routes |
| `serve` | Start the Flask shim (default) |
| `merge FILE...` | Merge portable state files into the canonical state |

The authoritative schema is [`data/config.xsd`](../data/config.xsd).
