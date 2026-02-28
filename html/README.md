# WikiOracle — Client UI

Browser-based interface for the WikiOracle local LLM shim. All front-end assets live in this directory and are served by `bin/wikioracle.py`.

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
| `index.html` | Single-page app shell — layout, settings panel |
| `wikioracle.css` | Stylesheet — layout, dark mode, chat and tree panel styles |
| `config.js` | Config global, sessionStorage persistence, normalization, legacy migration |
| `state.js` | State global, sessionStorage persistence |
| `util.js` | Shared helpers — `escapeHtml`, `stripTags`, `truncate`, `tempId`, `findInTree`, settings/context/output editors |
| `query.js` | Server communication layer — `api()`, conversation tree helpers, `_buildRuntimeConfig` |
| `tree.js` | D3.js tree renderer — hierarchy layout, click/double-click/right-click navigation, drag-to-merge |
| `wikioracle.js` | Main app — XHTML validation, layout/theme, provider metadata, chat, tree navigation, init |
| `404.html` | Fallback error page |

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
| **Right-click** | Context menu (Split / Delete) |

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

The server (`bin/wikioracle.py`) serves everything in this directory for extensions matching `.html`, `.css`, `.js`, `.svg`, `.png`, `.ico`, `.json`, `.jsonl`. No build step is required — edit files and refresh.

Cache-busting is handled via query-string versions on the script tags in `index.html` (e.g. `tree.js?v=10`). Bump the version number after changes.

JS load order: `config.js → state.js → util.js → query.js → tree.js → wikioracle.js`.
