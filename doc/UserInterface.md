# User Interface


## Rendering

The display layer covers HTML structure, CSS classes, D3 node shapes, optimistic UI, and state persistence.

### Context for the upstream LLM

When a message is sent, the server needs to provide conversational context to the upstream model. The function `get_context_messages(conversations, conv_id)` walks the **ancestor chain** from the active conversation up to the root, collecting all messages in chronological order.

```
Root conversation      ->  messages: [m1, m2, m3]
  |- Child conv        ->  messages: [m4, m5]
     `- Grandchild     ->  messages: [m6, m7]  <- active

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
Client receives state payload
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

### Keyboard navigation

| Key | Action |
|---|---|
| Arrow Up | Navigate to parent conversation |
| Arrow Down | Navigate to first child conversation |
| Arrow Right | Next node in inorder traversal |
| Arrow Left | Previous node in inorder traversal |

Keyboard events are ignored when a text input, textarea, or select
element has focus, or when the context overlay is active.

#### Diamond traversal

A diamond (DAG merge) occurs when a conversation has multiple parents
(e.g. the final synthesis in an HME vote that merges two beta
branches):

```
        root
       /    \
     beta1  beta2
       \    /
        final      ← parentId: [beta1, beta2]
```

Arrow Right / Arrow Left perform standard tree preorder traversal.
In a DAG the same node appears under multiple parents; it is visited
**once per parent** so that each parent's subtree is a complete
reading path:

```
→  root  →  beta1  →  final  →  beta2  →  final  →  END
```

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

## Settings Dialog

The Settings panel (gear icon in the sidebar) lets users configure
chat behaviour and online training parameters at runtime.  Settings
are persisted in `sessionStorage` (with a `localStorage` fallback for
tab-close durability) under the `wikioracle_config` key.

### Settings Controls

| Control | ID | Type | Config path | Default | Description |
|---------|-----|------|-------------|---------|-------------|
| Username | `setUsername` | text | `user.name` | `"User"` | Display name shown in chat messages. |
| Provider | `setProvider` | select | `ui.default_provider` | `"wikioracle"` | Active LLM provider. |
| Layout | `setLayout` | select | `ui.layout` | `"flat"` | Panel layout mode (`horizontal`, `vertical`, `flat`). |
| Theme | `setTheme` | select | `ui.theme` | `"system"` | Colour theme (`system`, `light`, `dark`). |
| Temperature | `setTemperature` | range (0–2) | `chat.temperature` | `0.7` | Sampling temperature for the LLM. |
| Max tokens | `setMaxTokens` | number | `chat.max_tokens` | `128` | Maximum tokens in the LLM response. |
| Timeout | `setTimeout` | number | `chat.timeout` | `120` | Request timeout in seconds. |
| Truth weight | `setTruthWeight` | range (0–1) | `chat.truth_weight` | `0.7` | How much DoT gates the learning rate. See below. |
| Max truth entries | `setTruthMaxEntries` | number | `chat.truth_max_entries` | `1000` | Maximum entries in the server truth table before trimming. |
| Store particular facts | `setStoreParticulars` | checkbox | `chat.store_particulars` | `false` | Store spatiotemporally-bound facts (news) in the server truth table. |
| Fetch URLs | `setUrlFetch` | checkbox | `chat.url_fetch` | `false` | Allow the assistant to fetch URL content. |
| Confirm actions | `setConfirmActions` | checkbox | `chat.confirm_actions` | `false` | Require confirmation before destructive operations. |

### Truth Weight Slider

The **truth weight** slider (0.0–1.0, step 0.05) replaces the former
"Use Truth Table" checkbox.  It controls two things simultaneously:

1. **RAG delivery**: When `truth_weight > 0`, the truth table is sent
   to the provider as grounding evidence (the former `rag: true`
   behavior).  When `truth_weight = 0`, no truth is sent.

2. **Training modulation**: During online training, `truth_weight`
   controls how much DegreeOfTruth gates the learning rate:

   * `truth_weight = 0.0`: Vanilla SFT — trains on everything at full
     learning rate regardless of DoT.  No EMA anchor pull.
   * `truth_weight = 0.7`: Default — DoT significantly gates learning,
     with moderate anchor pull toward checkpoint.
   * `truth_weight = 1.0`: Fully DoT-gated — zero DoT means zero
     learning.  Full anchor pull toward checkpoint.

The slider displays its current numeric value next to the control via
the `#setTruthWeightVal` span, updated live on input events.

### Max Truth Entries

Controls the maximum size of the server truth table.  When the table
exceeds this limit, entries with `|trust|` closest to 0.0 (lowest
information value) are trimmed during the merge stage.  Range:
100–10000, step 100.

### Store Particular Facts

When enabled, spatiotemporally-bound facts (those with `<place>` or
`<time>` child elements carrying real values) are stored in the server
truth table alongside universal facts.  When disabled (default), only
universal facts persist — consistent with Zero-Knowledge / Selective
Disclosure principles.

This setting is a client-side override for the server's
`store_particulars` config.  The client value takes precedence when
sent in the query payload.

### Legacy Migration

The config system automatically migrates the former boolean `rag` flag
to the new `truth_weight`:

* `rag: true` → `truth_weight: 0.7`
* `rag: false` → `truth_weight: 0.0`

This migration runs in both `client/config.js` (client-side) and
`bin/response.py` (server-side) to handle configs from before the
migration.

## Server Truth Table Display

In debug mode, when online training is enabled, the client displays
server truth table entries alongside local truth entries.  Server
entries are visually distinguished with:

* A blue left border (3px, accent colour)
* A "SERVER" badge in small uppercase text
* Reduced opacity (0.65)

Server truth entries are injected from the `/chat` response's
`server_truth` field and tagged with `_server_origin: true` in local
state.  They are **automatically stripped from the truth table before
sending queries** to prevent loopback — the server should never
receive its own truth entries back from the client.

## User Interface Strings

Canonical UI text for the WikiOracle client.
A consistency test (`test/test_ui_strings.py`) periodically checks that the
strings hard-coded in `client/util.js` match the tables below.

## Truth editor

### Dropdown labels

| Key | Label |
|---|---|
| `feeling` | `Feeling: subjective, non-verifiable claim` |
| `fact` | `Fact: disprovable assertion about the world` |
| `reference` | `Reference: citation with external link` |
| `authority` | `Authority: pointer to remote truth table` |
| `provider` | `Provider: external LLM endpoint` |
| `not` | `NOT: negation of a truth entry` |
| `non` | `NON: non-affirming weakening toward zero` |
| `or` | `OR: true when any child is true (max)` |
| `and` | `AND: true when all children are true (min)` |

### Descriptions

| Key | Description |
|---|---|
| `feeling` | `Feeling — a subjective, non-verifiable claim (not penalizable).` |
| `fact` | `Fact — a disprovable assertion with a degree of truth.` |
| `reference` | `Reference — a citation linking to an external source.` |
| `and` | `AND — true when all children are true (min trust).` |
| `or` | `OR — true when any child is true (max trust).` |
| `not` | `NOT — negation of a child entry.` |
| `non` | `NON — non-affirming negation (weakens trust toward zero).` |
| `provider` | `Provider — an LLM API endpoint.` |
| `authority` | `Authority — a remote knowledge base (XML URL).` |

### Templates

| Key | Template |
|---|---|
| `feeling` | `<feeling>Subjective statement here.</feeling>` |
| `fact` | `<fact DoT="0.0">Assertion text here.</fact>` |
| `reference` | `<reference DoT="0.0"><a href="https://example.com">Link text</a></reference>` |
| `and` | `<and DoT="0.0" arg1="" arg2=""/>` |
| `or` | `<or DoT="0.0" arg1="" arg2=""/>` |
| `not` | `<not DoT="0.0" arg1=""/>` |
| `non` | `<non DoT="0.0" arg1=""/>` |
| `provider` | `<provider DoT="0.0"><api_url>https://api.example.com</api_url><model>model_name</model></provider>` |
| `authority` | `<authority DoT="0.0"><url>https://example.com/kb.xml</url></authority>` |

### Empty state

| Key | Text |
|---|---|
| `truth_empty` | `No truth entries. Add truth here or Open a new state file.` |

