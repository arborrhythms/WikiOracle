# Implementation

## System overview

WikiOracle is a local-first Flask shim that sits between a browser UI and one or more upstream LLM providers. Conversations are stored as a hierarchical tree — each conversation is an ordered list of messages that may branch into child conversations.

```
Browser  --HTTP-->  wikioracle.py  --HTTP-->  Upstream LLM
                        |
                    state.xml
                   (persistent state)
```

### Components

| Layer | File(s) | Role |
|---|---|---|
| Server | `bin/wikioracle.py` | Flask app — `/chat`, `/state`, `/merge`, `/config`, `/bootstrap` endpoints; reads/writes `state.xml` |
| Config | `bin/config.py` | Config dataclass, XML loader, provider registry, schema-driven XML writer, normalization |
| State library | `bin/state.py` | Pure-Python tree operations, XML serialisation, merge with deterministic ID suffixing |
| Response | `bin/response.py` | Chat pipeline, provider coordination, state I/O, online training pipeline (Stages 2–4) |
| Truth | `bin/truth.py` | Trust processing, authority resolution, operator engine (and/or/not), DegreeOfTruth, spacetime fact classification, PII detection |
| Sensation | `bin/sensation.py` | Preprocessing: Korzybski IS detection, XML tagging (`<fact>`/`<feeling>`/`<Q>`/`<R>` with `<place>`/`<time>` child elements), corpus conversion |
| OpenClaw | `openclaw/` (git submodule) + `openclaw/extensions/wikioracle/` | Multi-channel front-end (Slack/Discord/Telegram) — TypeScript extension routes messages through `bin/wo` CLI to WikiOracle's full pipeline |
| NanoChat ext | `bin/nanochat_ext.py` | `POST /train` route mounted onto NanoChat's FastAPI app for online SFT |
| Client app | `client/wikioracle.js` | State management, API calls, message rendering, drag/context-menu interactions |
| Client config | `client/config.js` | Config global, sessionStorage persistence, normalization, legacy migration |
| Client state | `client/state.js` | State global, sessionStorage persistence |
| Client utils | `client/util.js` | Shared helpers, settings panel, config editor, context/output editors |
| Client query | `client/query.js` | Server communication layer, conversation tree helpers |
| Tree renderer | `client/tree.js` | D3.js top-down hierarchy — layout, navigation, drag-to-merge |
| Shell | `client/index.html` | Single-page app: layout, CSS, settings panel |
| State schema | `data/state.xsd` | XSD schema for XML state files (WikiOracle State) |
| Config schema | `data/config.xsd` | XSD schema for `config.xml` validation (WikiOracle Config) |
| Tests | `test/test_*.py` | Tests covering state, stateless contract, prompt bundles, authority, derived truth, DoT, sensation, online training, XML state roundtrip |


## Server endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/server_info` | Stateless flag + url_prefix |
| GET | `/bootstrap` | One-shot seed for stateless clients (state + config) |
| GET | `/info` | State/schema/provider metadata for diagnostics |
| GET | `/state` | Return current in-memory state |
| POST | `/state` | Replace state |
| GET | `/state_size` | State file size in bytes (progress bar) |
| POST | `/chat` | Send a message — append to existing conversation, branch, or create new root |
| POST | `/merge` | Merge an imported state file into current state |
| GET | `/config` | Normalized config (includes provider metadata and defaults) |
| POST | `/config` | Accept full config dict; write config.xml to disk |
| GET | `/` | Serve `client/index.html` |
| GET | `/<file>` | Serve static assets from `client/` |

### Data flow: client <-> server

Truth, context, and output are **client-owned**. They flow client → server only; the server never sends them back in a chat response.

```
POST /chat request:   client sends truth + context + output + message
POST /chat response:  server returns text + conversation delta
                      (no truth, no context, no output)
```

In stateful mode, the server persists the full state (including the client-supplied truth) to `state.xml`. On error rollback, the client reloads conversations from the server but preserves its own truth, context, and output.

In stateless mode, the server has no disk — the client sends and receives the full state.

### Chat routing

`POST /chat` accepts:

* `conversation_id` — append user message + LLM response to an existing conversation
* `branch_from` — create a new child conversation under the specified parent, seed it with the user message + LLM response
* Neither — create a new root-level conversation

## Reducing Inferential Truth to Facts and Feelings

The chat pipeline always sends the final query to the provider selected in the
UI config. The `rag` flag decides whether `state.truth` participates at all:
when `rag` is false, no truth entries are sent; when `rag` is true, the server
reduces inferential structure to propositional entries plus derived certainty
before the final synthesis step. When dynamic `<provider>` entries exist, the
UI-selected provider acts as the alpha and the ranked provider entries act as
beta experts.

```
st = static_truth(state.truth)      # facts, feelings, references
t  = st + dynamic_truth(st)         # operators, authorities, providers
```

Structural entries such as `<provider>`, `<operator>`, and `<authority>` are
not treated as propositions; they are evaluated against the static set and
contribute their results back to the final bundle.

When a user sends a query:

1. **Static truth**: `static_truth()` extracts the evaluable subset of
   `state.truth`: facts, feelings, and references.
2. **Dynamic truth**: `dynamic_truth(st)` evaluates structural entries against
   that subset.
   * **Operators**: `compute_derived_truth()` evaluates `<and>`, `<or>`, and
     `<not>` with Strong Kleene semantics and propagates derived certainty.
   * **Authorities**: `<authority>` entries fetch remote truth tables and
     append their entries with scaled certainty.
   * **Providers**: ranked `<provider>` entries are queried as beta experts.
     Each beta receives the query bundle, conversation history, output
     instructions, and optionally the alpha's preliminary response as a
     steering signal.
3. **Final synthesis**: the alpha receives all original `state.truth` entries,
   operator-derived certainty, authority entries, beta responses,
   conversation history, system context, and the user message.
4. **Single-call case**: when there are no dynamic `<provider>` entries, the
   flow collapses to one call to the UI-selected provider.

This is the HME (Hierarchical Mixture of Experts) model: operators compute
derived certainty over the static truth, authorities contribute remote
knowledge, and dynamic providers act as expert consultants while the
UI-selected provider synthesizes the final answer. Provider credentials remain
separate: each provider uses its own key, whether configured in `config.xml`
or embedded in the truth entry. See
[Voting.md](./Voting.md) for the
theoretical foundation.

## State library (`bin/state.py`)

Key functions:

| Function | Purpose |
|---|---|
| `state_to_xml(state)` | Serialise nested tree → XML string |
| `xml_to_state(text)` | Parse XML → nested tree |
| `atomic_write_xml(path, state)` | Atomic XML file write (temp + fsync + rename) |
| `load_state_file(path)` | Load state from XML file |
| `find_conversation(convs, id)` | Recursive tree lookup |
| `get_ancestor_chain(convs, id)` | Walk up to root, return list of ancestors |
| `get_context_messages(convs, id)` | Ancestor chain messages in order (for LLM context) |
| `add_message_to_conversation(convs, id, msg)` | Append a message |
| `add_child_conversation(convs, parent_id, child)` | Insert a new branch |
| `remove_conversation(convs, id)` | Delete a subtree |
| `ensure_minimal_state(state)` | Fill in missing fields with defaults |
