# WikiOracle Architecture

## System overview

WikiOracle is a local-first Flask shim that sits between a browser UI and one or more upstream LLM providers. Conversations are stored as a hierarchical tree — each conversation is an ordered list of messages that may branch into child conversations.

```
Browser  ──HTTP──▸  wikioracle.py  ──HTTP──▸  Upstream LLM
                        │
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
| OpenClaw | `openclaw/` (git submodule) + `bin/openclaw_ext.py` | Multi-channel front-end (Slack/Discord/Telegram) — bridges external platforms to WikiOracle's `/chat` endpoint |
| NanoChat ext | `bin/nanochat_ext.py` | `POST /train` route mounted onto NanoChat's FastAPI app for online SFT |
| Client app | `client/wikioracle.js` | State management, API calls, message rendering, drag/context-menu interactions |
| Client config | `client/config.js` | Config global, sessionStorage persistence, normalization, legacy migration |
| Client state | `client/state.js` | State global, sessionStorage persistence |
| Client utils | `client/util.js` | Shared helpers, settings panel, config editor, context/output editors |
| Client query | `client/query.js` | Server communication layer, conversation tree helpers |
| Tree renderer | `client/tree.js` | D3.js top-down hierarchy — layout, navigation, drag-to-merge |
| Shell | `client/index.html` | Single-page app: layout, CSS, settings panel |
| Data | `data/llm_state.json` | JSON Schema for the state format (legacy) |
| State schema | `data/state.xsd` | XSD schema for XML state files (WikiOracle State) |
| Config schema | `data/config.xsd` | XSD schema for `config.xml` validation (WikiOracle Config) |
| Tests | `test/test_*.py` | Tests covering state, stateless contract, prompt bundles, authority, derived truth, DoT, sensation, online training, XML state roundtrip |

## Data model

### On disk — XML

State is persisted as XML (WikiOracle State format, validated by `data/state.xsd`). Conversations nest naturally in the XML tree — no flatten/unflatten needed:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<state>
  <header>
    <version>2</version>
    <schema>https://wikioracle.org/schemas/state/v2</schema>
    <time>2026-03-05T12:00:00Z</time>
    <title>My Project</title>
    <context><div><p>Project context</p></div></context>
  </header>
  <conversations>
    <conversation id="c_abc">
      <title>Animals</title>
      <messages>
        <message id="m1" role="user" username="Alice" time="...">
          <content><Q><fact trust="0.5">Dogs are mammals.</fact></Q></content>
        </message>
      </messages>
      <children>
        <conversation id="c_def" parentId="c_abc">
          <title>Dogs</title>
          <messages>...</messages>
          <children/>
        </conversation>
      </children>
    </conversation>
  </conversations>
  <truth>
    <entry id="t_001" title="Mammals" trust="0.9" time="...">
      <content><fact trust="0.9">All dogs are mammals.</fact></content>
    </entry>
  </truth>
</state>
```

### In memory — nested tree

On load, conversations are represented as a nested tree:

```
state.conversations = [
  { id: "c_abc", title: "Animals", messages: [...],
    children: [
      { id: "c_def", title: "Dogs", messages: [...], children: [] },
      { id: "c_ghi", title: "Cats", messages: [...], children: [] }
    ]
  }
]
```

Each **conversation** has: `id`, `title`, `messages[]`, `children[]`.

Each **message** has: `id`, `role` (user | assistant | system), `username`, `timestamp`, `content` (XHTML).

### Grammar

```
State       → Header Conversation* Trust*
Conversation → { id, title, messages: Message*, parent? }
Message     → { id, role, username, timestamp, content }
Trust       → { id, content, certainty, source?, timestamp? }
```

In the tree: `Dialogue → Conversation*`, `Conversation → Message* + Conversation*` (children).

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

### Data flow: client ↔ server

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

- `conversation_id` — append user message + LLM response to an existing conversation
- `branch_from` — create a new child conversation under the specified parent, seed it with the user message + LLM response
- Neither — create a new root-level conversation

### Chat pipeline (HME provider resolution)

The chat pipeline always sends the final query to the provider selected in the UI config (openai, anthropic, gemini, grok, etc.). The truth table is gated by the `rag` config flag: when `rag` is true, **all** `state.truth` is sent; when `rag` is false, **no** truth of any kind is sent.

When `rag` is true, the truth table is processed in two phases — static and dynamic — before it reaches the final provider:

```
st = static_truth(state.truth)      # facts & references (evaluable subset)
t  = st + dynamic_truth(st)         # operators, authorities, and providers
                                    # evaluated against st
```

`static_truth` selects the entries that the dynamic evaluation steps use as input. All `state.truth` entries (including structural ones) are still sent to the final provider — `static_truth` controls evaluation, not delivery.

In detail:

```
1. st = static_truth(state.truth)
   - Extract the evaluable subset: <fact>, <feeling>, and <reference> entries
   - These carry propositional content (claims, opinions, citations, URLs)
   - Structural entries (<provider>, <operator>, <authority>) are
     excluded from this subset (they are evaluated, not consumed)

2. dynamic_truth(st) — evaluate structural entries against st
   a. Operators (Strong Kleene): compute_derived_truth evaluates <and>,
      <or>, <not> over the truth table; derived certainty values
      propagate back into the entries they govern
   b. Authorities: <authority> entries reference remote truth tables;
      each is fetched and its entries are appended with scaled certainty
   c. Providers (HME): each <provider> entry is an external LLM endpoint;
      the server calls it with context + history + query, and the
      response becomes a source with the provider's certainty

3. Assemble the ProviderBundle
   - ALL state.truth entries are included (facts, references, operators,
     authorities, providers) — with operator-derived certainty where
     applicable
   - Authority remote entries are appended
   - Provider evaluation responses are appended
   - Conversation history, system context, and the user message complete
     the bundle

4. Call the UI-selected provider
   - The bundle is sent to whichever provider the user chose in Settings
   - This provider receives the complete truth table as evidence
```

This is the HME (Hierarchical Mixture of Experts) model: operators compute derived certainty over the static truth, authorities contribute remote knowledge, and dynamic providers act as expert consultants — all feeding into the truth table that the UI-selected provider (the "mastermind") uses to synthesise its final answer. See [HierarchicalMixtureOfExperts.md](./HierarchicalMixtureOfExperts.md) for the theoretical foundation.

## Rendering

The display layer covers HTML structure, CSS classes, D3 node shapes, optimistic UI, and state persistence.

### Context for the upstream LLM

When a message is sent, the server needs to provide conversational context to the upstream model. The function `get_context_messages(conversations, conv_id)` walks the **ancestor chain** from the active conversation up to the root, collecting all messages in chronological order.

```
Root conversation      →  messages: [m1, m2, m3]
  └── Child conv       →  messages: [m4, m5]
        └── Grandchild →  messages: [m6, m7]  ← active

Context sent to LLM: [m1, m2, m3, m4, m5, m6, m7]
```

This gives the LLM the full path of dialogue that led to the current point, without noise from sibling branches.

### Tree visualisation (D3)

`tree.js` renders the conversation tree as a top-down hierarchy using `d3.tree()`:

```
conversationsToHierarchy(state.conversations, selectedId)
    ↓
D3 hierarchy data  { id, title, messageCount, questionCount, selected, children }
    ↓
renderTree(hierarchyData, callbacks)
    ↓
SVG with nodes (rects/pills/circles) + curved links
```

The root node is a circle labelled `/`. Selected conversations render as larger labelled rectangles; others as compact pills. The selected node is highlighted with the accent colour.

### Chat view

`wikioracle.js → renderMessages()` displays the messages of the currently selected conversation:

1. Look up `selectedConvId` in the tree via `findConversation()`
2. Iterate `conv.messages`, rendering each as a `.message` div with role-based styling
3. Attach drag-to-reorder (HTML5 drag/drop) and right-click context menus to each message
4. Re-render the D3 tree in sync

When no conversation is selected (root view), a placeholder prompts the user to type.

### Rendering pipeline (end to end)

```
state.xml on disk
    ↓  [xml_to_state]
In-memory state with nested conversation tree
    ↓  [GET /state]
Client receives state JSON
    ↓  [renderMessages]
Chat panel shows selected conversation's messages
    ↓  [conversationsToHierarchy]
D3 hierarchy data
    ↓  [renderTree]
SVG tree visualisation
```

## Interactions

### Tree panel

| Gesture | Action |
|---|---|
| Click | Navigate — select that conversation, show its messages |
| Double-click | Open context menu (Branch, Delete) |
| Right-click | Open context menu (same) |
| Drag node → drop on node | Merge — append source's messages into target, remove source |

A 200ms timer disambiguates click from double-click. Context menus are appended to `document.body` with fixed positioning to avoid clipping by the tree container's `overflow: hidden`.

### Chat panel

| Gesture | Action |
|---|---|
| Right-click message | Context menu (Move up, Move down, Delete) |
| Drag message | Reorder within the conversation |

### Merge semantics

Dragging conversation A onto B:

1. Appends A's messages after B's existing messages (preserving order)
2. Re-parents A's children under B
3. Removes A from the tree

### Branching

Double-click or right-click a tree node → "Branch" creates a new empty child conversation. The next message typed seeds it. The LLM receives the full ancestor context.

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

---

## See also

- [Constitution.md](./Constitution.md) — the invariants this architecture implements.
- [Security.md](./Security.md) — CSP, CORS, API keys, and file system safety.
- [Training.md](./Training.md) — the online training pipeline (Stages 2–4) in `response.py`.
- [Logic.md](./Logic.md) — operators evaluated in the dynamic truth phase.
- [Authority.md](./Authority.md) — authority resolution in the HME pipeline.
- [Voting.md](./Voting.md) — voting protocol extending the chat pipeline.
- [Entanglement.md](./Entanglement.md) — client-owned state and data persistence policies.
- [Config.md](./Config.md) — configuration format and settings reference.
- [State.md](./State.md) — state file format, conversation tree, truth table.
- [Installation.md](./Installation.md) — deployment and runtime configuration.
