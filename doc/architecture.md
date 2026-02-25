# WikiOracle Architecture

## System overview

WikiOracle is a local-first Flask shim that sits between a browser UI and one or more upstream LLM providers. Conversations are stored as a hierarchical tree — each conversation is an ordered list of messages that may branch into child conversations.

```
Browser  ──HTTP──▸  WikiOracle.py  ──HTTP──▸  Upstream LLM
                        │
                    llm.jsonl
                   (persistent state)
```

### Components

| Layer | File(s) | Role |
|---|---|---|
| Server | `WikiOracle.py` | Flask app — `/chat`, `/state`, `/merge`, `/providers` endpoints; reads/writes `llm.jsonl` |
| State library | `bin/wikioracle_state.py` | Pure-Python tree operations, JSONL serialisation, legacy migration |
| Client app | `html/wikioracle.js` | State management, API calls, message rendering, drag/context-menu interactions |
| Tree renderer | `html/d3tree.js` | D3.js top-down hierarchy — layout, navigation, drag-to-merge |
| Shell | `html/index.html` | Single-page app: layout, CSS, settings panel |
| Spec | `spec/llm_state.json` | JSON Schema for the state format |
| Tests | `tests/test_derived_truth.py` | 16 tests covering implication parsing, modus ponens, chains, cycles, hme.jsonl integration |

## Data model

### On disk — JSONL

State is persisted as line-delimited JSON. Each line is a self-typed record:

```jsonl
{"type":"header","schema":"…","date":"…","context":"…","selected_conversation":"c_abc"}
{"type":"conversation","id":"c_abc","title":"Animals","messages":[…]}
{"type":"conversation","id":"c_def","title":"Dogs","parent":"c_abc","messages":[…]}
{"type":"trust","id":"t_001","content":"…","certainty":0.9}
```

The `parent` field encodes the tree structure in flat form. Root conversations omit `parent`.

### In memory — nested tree

On load, conversations are reconstructed into a nested tree:

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
| GET | `/state` | Return current in-memory state |
| POST | `/state` | Replace state |
| POST | `/chat` | Send a message — append to existing conversation (`conversation_id`), branch (`branch_from`), or create new root |
| POST | `/merge` | Merge an imported state file into current state |
| GET | `/providers` | List available upstream LLM providers |
| GET | `/` | Serve `html/index.html` |
| GET | `/<file>` | Serve static assets from `html/` |

### Chat routing

`POST /chat` accepts:

- `conversation_id` — append user message + LLM response to an existing conversation
- `branch_from` — create a new child conversation under the specified parent, seed it with the user message + LLM response
- Neither — create a new root-level conversation

The server calls `get_context_messages()` to build the upstream prompt (see Rendering below).

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

This gives the LLM the full path of dialogue that led to the current point, without noise from sibling branches. The `message_window` preference caps how many messages are included.

### Tree visualisation (D3)

`d3tree.js` renders the conversation tree as a top-down hierarchy using `d3.tree()`:

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
llm.jsonl on disk
    ↓  [jsonl_to_state]
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

## State library (`bin/wikioracle_state.py`)

Key functions:

| Function | Purpose |
|---|---|
| `state_to_jsonl(state)` | Serialise nested tree → JSONL lines |
| `jsonl_to_state(lines)` | Parse JSONL → nested tree |
| `find_conversation(convs, id)` | Recursive tree lookup |
| `get_ancestor_chain(convs, id)` | Walk up to root, return list of ancestors |
| `get_context_messages(convs, id)` | Ancestor chain messages in order (for LLM context) |
| `add_message_to_conversation(convs, id, msg)` | Append a message |
| `add_child_conversation(convs, parent_id, child)` | Insert a new branch |
| `remove_conversation(convs, id)` | Delete a subtree |
| `ensure_minimal_state(state)` | Fill in missing fields with defaults |
