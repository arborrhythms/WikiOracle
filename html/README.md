# WikiOracle — Client UI

Browser-based interface for the WikiOracle local LLM shim. All front-end assets live in this directory and are served by `WikiOracle.py`.

## Architecture

WikiOracle uses a **hierarchical conversation tree**. Each conversation contains an ordered list of messages and may have child conversations (branches). The tree is rendered as an interactive D3 visualisation alongside a standard chat view.

```
Root (/)
├── Animals  (2 msgs)
│   ├── Dogs  (2 msgs)
│   └── Cats  (2 msgs)
└── Climate  (4 msgs)
    └── Oceans  (3 msgs)
```

## Files

| File | Purpose |
|---|---|
| `index.html` | Single-page app shell — layout, CSS, settings panel |
| `reading.css` | Shared reading/layout styles for chat and tree panels |
| `wikioracle.js` | Client logic — state management, API calls, message rendering, drag/context-menu interactions |
| `d3tree.js` | D3.js tree renderer — hierarchy layout, click/double-click/right-click navigation, drag-to-merge |
| `404.html` | Fallback error page |

### Simulator scripts (legacy)

These Node.js scripts test parts of the rendering pipeline outside the browser and are kept for reference.

| Script | What it does |
|---|---|
| `simulate_rendering.js` | End-to-end rendering pipeline: JSONL parsing, graph building, path resolution, conversation grouping |
| `visualize_structure.js` | ASCII tree visualisation with branch-point analysis |
| `show_conversations.js` | Conversation segment grouping for D3 tree nodes |
| `mock_render_output.js` | Generates the HTML that the chat view would produce |

Run any of them with `node <script>.js` from this directory (no external dependencies).

## Interactions

### Tree panel

| Gesture | Action |
|---|---|
| **Click** | Navigate to that conversation (show its messages) |
| **Double-click** | Open context menu (Branch / Delete) |
| **Right-click** | Open context menu (same as double-click) |
| **Drag node → drop on node** | Merge — appends source's messages into target, removes source |

### Chat panel (messages)

| Gesture | Action |
|---|---|
| **Right-click** | Context menu (Move up / Move down / Delete) |
| **Drag message** | Reorder within the conversation |

## Data model

State is persisted as line-delimited JSON (`.jsonl`):

```
{"type":"header", "schema":"…", "date":"…", "context":"…", "selected_conversation":"c_abc"}
{"type":"conversation", "id":"c_abc", "title":"Animals", "messages":[…]}
{"type":"conversation", "id":"c_def", "title":"Dogs", "parent":"c_abc", "messages":[…]}
{"type":"trust", "id":"t_001", "content":"…", "certainty":0.9}
```

In memory, conversations are nested via `children` arrays. The `parent` field in JSONL is used only for serialisation — on load, the tree is reconstructed from parent references.

## Key concepts

**Conversation**: an ordered list of `{id, role, username, timestamp, content}` messages, plus metadata (`id`, `title`) and optional `children`.

**Selected conversation**: the conversation whose messages are displayed in the chat panel. Stored in state and persisted via cookie for session restore.

**Branching**: creating a new child conversation from an existing one. The child starts empty; the first message sent becomes its seed.

**Merging**: dragging conversation A onto B appends A's messages after B's (preserving order), re-parents A's children under B, then removes A.

**Context for upstream LLM**: `get_context_messages()` walks the ancestor chain from the active conversation up to the root, collecting all messages in order. This gives the LLM the full conversational path without sibling noise.

## Development

The server (`WikiOracle.py`) serves everything in this directory for extensions matching `.html`, `.css`, `.js`, `.svg`, `.png`, `.ico`, `.json`, `.jsonl`. No build step is required — edit files and refresh.

Cache-busting is handled via query-string versions on the script tags in `index.html` (e.g. `d3tree.js?v=10`). Bump the version number after changes.
