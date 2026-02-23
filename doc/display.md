# WikiOracle Display & Rendering

Deep-dive into how WikiOracle renders conversations in the browser. For the broader system context, see [architecture.md](architecture.md).

## Rendering pipeline

```
llm.jsonl on disk
    ↓  [jsonl_to_state]  (bin/wikioracle_state.py)
In-memory state: nested conversation tree
    ↓  [GET /state]  (WikiOracle.py)
Client receives state JSON
    ↓  [renderMessages]  (html/wikioracle.js)
Chat panel: selected conversation's messages as HTML
    ↓  [conversationsToHierarchy]  (html/d3tree.js)
D3 hierarchy data
    ↓  [renderTree]  (html/d3tree.js)
SVG tree visualisation
```

## Chat view (`renderMessages`)

The chat panel displays messages from the currently selected conversation. The rendering logic in `wikioracle.js`:

1. **Lookup**: `findConversation(state.conversations, selectedConvId)` — recursive tree search.
2. **Iterate**: each message in `conv.messages` becomes a `.message` div, styled by `role`:
   - `.message.user` — right-aligned, accent background
   - `.message.assistant` — left-aligned, neutral background
   - `.message.system` — centred, muted
3. **Metadata**: each message div shows `username · timestamp` above the content bubble.
4. **Content**: `msg.content` is XHTML, rendered as `innerHTML` in a `.msg-bubble` div.
5. **Interactions**: each message div gets drag-to-reorder handlers and a `contextmenu` listener.
6. **Placeholder**: when no conversation is selected or messages are empty, a prompt is shown.
7. **Scroll**: the chat container auto-scrolls to the bottom after render.
8. **Tree sync**: `renderMessages()` also calls `conversationsToHierarchy()` + `renderTree()` to keep the tree panel in sync.

### Message HTML structure

```html
<div class="message user" draggable="true" data-msg-idx="0" data-msg-id="m_abc123">
  <div class="msg-meta">Alice · 23/02/2026, 14:30:00</div>
  <div class="msg-bubble"><p>Hello, what do you know about cats?</p></div>
</div>
```

### Message interactions

| Gesture | Handler | Effect |
|---|---|---|
| Right-click | `_showMsgContextMenu(event, idx, total)` | Fixed-position menu: Move up, Move down, Delete |
| Drag start | `dragstart` on `.message` | Sets `dataTransfer` with source index, adds `.msg-dragging` class |
| Drag over | `dragover` on `.message` | Adds `.msg-dragover` border indicator |
| Drop | `drop` on `.message` | Calls `_moveMessage(fromIdx, toIdx)` — splices messages array |
| Delete | `_deleteMessage(msgIdx)` | Confirms, splices message; removes empty conversation if no children |

## Tree view (`renderTree`)

### Hierarchy construction

`conversationsToHierarchy(conversations, selectedId)` maps the state tree to D3-compatible data:

```javascript
{
  id: "root",           // synthetic root node
  title: "/",
  selected: true,       // true when selectedId === null
  children: [
    {
      id: "c_abc",
      title: "Animals",
      messageCount: 4,
      questionCount: 2,
      messages: [...],   // passed through for tooltip + merge count display
      selected: false,
      children: [...]
    }
  ]
}
```

### Layout

Uses `d3.tree()` with top-down orientation (root at top, branches downward):

- **Margins**: 20px top/bottom, 40px left/right
- **Separation**: 1.2× for siblings, 1.8× for cousins
- **Links**: cubic Bézier curves (`M sx,sy C sx,my tx,my tx,ty`)

### Node shapes

| Type | Shape | Size | Condition |
|---|---|---|---|
| Root | Circle | r=14 | `id === "root"` |
| Selected | Rounded rect | width by title length, h=40 | `selected === true` |
| Default | Pill (fully rounded rect) | width by title length, h=22 | Everything else |

Selected nodes show two lines: title (truncated to 26 chars) and a detail line (`N Qs, M msgs`). Default nodes show a single truncated title (20 chars).

### Colour scheme

Colours are read from CSS custom properties at render time:

| Variable | Usage |
|---|---|
| `--accent` | Selected node stroke, text |
| `--accent-light` | Selected node fill |
| `--border` | Default node stroke, link stroke |
| `--fg` | Selected title text |
| `--fg-muted` | Default title text, detail text |
| `--bg` | Default node fill |

Merge target highlighting uses amber (`#f59e0b`).

### Tree interactions

| Gesture | Timer/guard | Effect |
|---|---|---|
| Click | 200ms `_clickTimer` | Navigate: `callbacks.onNavigate(id)` |
| Double-click | Cancels `_clickTimer` | Context menu: Branch, Delete |
| Right-click | — | Context menu (same as double-click) |
| Drag start | Left button, non-root only | Raises node, sets opacity 0.7 |
| Drag move | — | Translates node to cursor; highlights nearest valid target (amber, 3px stroke) within 30px |
| Drag end (on target) | Excludes self + descendants | Confirm dialog → `callbacks.onMerge(sourceId, targetId)` |
| Hover | Suppressed during drag | Tooltip: title, Q/A count, last message preview (80 chars) |

### Context menu

The context menu is a `div.tree-context-menu` appended to `document.body` with `position: fixed`. This avoids clipping by the tree container's `overflow: hidden`.

A `_justOpened` flag with 300ms grace period prevents the document-level click handler from immediately closing the menu. The handler only fires if the click is outside the menu and the grace period has elapsed.

## Optimistic UI

When the user sends a message, `sendMessage()` performs optimistic rendering before the server responds:

1. Creates a temporary message entry with `_pending: true` (rendered at 0.6 opacity).
2. For new conversations, creates a temporary conversation with a `tempId("c_")`.
3. Appends to the DOM immediately via `renderMessages()`.
4. On server success: replaces state with the server's authoritative response, re-renders.
5. On server error: reloads state from `GET /state`, reverts optimistic additions.

## Context for the upstream LLM

`get_context_messages(conversations, conv_id)` in `bin/wikioracle_state.py`:

1. `get_ancestor_chain(conversations, conv_id)` walks from the target conversation up to the root, returning `[root, ..., parent, self]`.
2. Collects `messages` from each ancestor in order.
3. Returns a flat list: all messages from root through to the active conversation.

```
Root:       [system_msg, user_hello, asst_hello]
  └─ Child: [user_followup, asst_followup]
       └─ Active: [user_new_q]

Context = [system_msg, user_hello, asst_hello, user_followup, asst_followup, user_new_q]
```

The server's `_build_messages_for_upstream()` maps these to the provider's expected format (typically `role`/`content` pairs) and appends the new user message. The `message_window` preference truncates from the front if the context exceeds the limit.

## CSS structure

All styles are inline in `html/index.html`. Key classes:

| Class | Element | Notes |
|---|---|---|
| `.tree-container` | Tree panel wrapper | `height: 220px`, `overflow: hidden`, `position: relative` |
| `.chat-container` | Chat scroll area | `flex: 1`, `overflow-y: auto` |
| `.message` | Each message div | Flex column, role-based alignment |
| `.message.user` | User messages | Right-aligned, accent colours |
| `.message.assistant` | Assistant messages | Left-aligned, neutral colours |
| `.msg-meta` | Timestamp line | Small muted text |
| `.msg-bubble` | Content area | Padded, rounded corners |
| `.msg-dragging` | During drag | `opacity: 0.4` |
| `.msg-dragover` | Drop target | `border-top: 2px solid var(--accent)` |
| `.tree-context-menu` | Context menus (tree + messages) | `position: absolute`, shadow, rounded |
| `.ctx-item` | Menu items | Hover highlight with accent |
| `.ctx-danger` | Delete items | Red text |
| `.chat-placeholder` | Empty state prompt | Centred, muted |

## State persistence

| Mechanism | What | Where |
|---|---|---|
| Server POST `/state` | Full state after every mutation | `llm.jsonl` on disk |
| Cookie `wo_selected` | Selected conversation ID | Browser |
| Cookie `wo_prefs` | User preferences (base64url JSON) | Browser |
| `localStorage wo_token` | Auth token | Browser |

On init, the client restores `selectedConvId` from the cookie first, falling back to `state.selected_conversation` from the server.
