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

| Gesture                  | Action                                                      |
| ------------------------ | ----------------------------------------------------------- |
| Click                    | Navigate -- select that conversation, show its messages      |
| Double-click             | Open context menu (Branch, Delete)                          |
| Right-click              | Open context menu (same)                                    |
| Drag node → drop on node | Merge -- append source's messages into target, remove source |

A 200ms timer disambiguates click from double-click. Context menus are appended to `document.body` with fixed positioning to avoid clipping by the tree container's `overflow: hidden`.

### Keyboard navigation

| Key         | Action                               |
| ----------- | ------------------------------------ |
| Arrow Up    | Navigate to parent conversation      |
| Arrow Down  | Navigate to first child conversation |
| Arrow Right | Next node in inorder traversal       |
| Arrow Left  | Previous node in inorder traversal   |

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
→ root → beta1 → final
→ beta2 → final → END
```

### Chat panel

| Gesture             | Action                                    |
| ------------------- | ----------------------------------------- |
| Right-click message | Context menu (Move up, Move down, Delete) |
| Drag message        | Reorder within the conversation           |

### Merge semantics

Dragging conversation A onto B:

1. Appends A's messages after B's existing messages (preserving order)
2. Re-parents A's children under B
3. Removes A from the tree

### Branching

Double-click or right-click a tree node → "Branch" creates a new empty child conversation. The next message typed seeds it. The LLM receives the full ancestor context.

## Settings Dialog

The Settings panel (gear icon in the sidebar) configures client identity,
provider/model selection, provider trust, layout, theme, and evaluation
preferences. The normalized config is persisted under the
`wikioracle_config` key in both `sessionStorage` and `localStorage`.
Conversation state uses the separate `wikioracle_state` key.

### Settings Controls

| Control (DOM id) | Value / default | Storage and behavior |
|---|---|---|
| Username (`setUsername`) | Text; `User` | `state.client_name`; display name attached to user messages |
| Provider (`setProvider`) | Select; shipped `WikiOracle` | `config.client.providers.default_provider`; active main provider |
| Model (`setModel`) | Select; selected provider's configured model | `config.client.providers.default_model`; explicit model override |
| Provider trust (`setProviderTrust`) | Range 0-1; `0` when absent | Browser copy of `config.server.providers.<name>.trust`; runtime trust metadata for provider-produced truth |
| Layout (`setLayout`) | Select; `horizontal` | `config.client.ui.layout`; horizontal or vertical panels |
| Theme (`setTheme`) | Select; `system` UI fallback | `config.client.ui.theme`; system, light, or dark palette |
| Temperature (`setTemp`) | Range 0-2; server evaluation default | `config.client.temperature`; sampling temperature |
| Allow URL fetching (`setUrlFetch`) | Checkbox; `false` | `config.client.url_fetch`; client evaluation preference |
| Thought-free mode (`setThoughtFree`) | Checkbox; `false` | `config.client.thought_free`; request non-discursive output and the BasicModel thought-free path |
| Confirm deletes / merges (`setConfirm`) | Checkbox; `false` | `config.client.ui.confirm_actions`; confirm destructive operations |

### Settings Persistence

| Setting family | Stateful mode | Stateless mode |
|---|---|---|
| `state.client_name` and conversations/truth | State is updated through `/state` or `/chat`; browser keeps a local copy | Browser state is authoritative and accompanies every `/chat` call |
| `config.client.*` | Saved locally, then `POST /config` replaces the client section in the writable config override | Saved only in browser storage; `POST /config` is rejected |
| `config.server.*` | Refreshed from `/config`; client POSTs cannot replace it | Included in the authoritative `runtime_config` returned by bootstrap/local storage |
| Provider metadata/model lists | Refreshed from `/config` or `/bootstrap` | Stored with the normalized config bundle |

Truth weight, concrete-fact storage, maximum truth entries, and training
parameters remain available in the XML config/editor but are not separate
controls in the current Settings panel.

## Server TruthSet Display

In debug mode, when online training is enabled, the client displays
server TruthSet entries alongside local truth entries.

| Treatment | Value |
|---|---|
| Left border | 3px accent blue |
| Badge | `SERVER` in small uppercase text |
| Opacity | 0.65 |

Server truth entries are injected from the `/chat` response's
`server_truth` field (debug mode only) and deduplicated by `id`
on each refresh.

## User Interface Strings

Canonical UI text for the WikiOracle client.
A consistency test (`test/test_ui_strings.py`) periodically checks that the
strings hard-coded in `client/util.js` match the tables below.

## Truth editor

### Dropdown labels

| Key         | Label                                         |
| ----------- | --------------------------------------------- |
| `feeling`   | `Feeling: subjective, non-verifiable claim`   |
| `fact`      | `Fact: disprovable assertion about the world` |
| `reference` | `Reference: citation with external link`      |
| `authority` | `Authority: pointer to remote TruthSet`       |
| `provider`  | `Provider: external LLM endpoint`             |

### Descriptions

| Key         | Description                                                       |
| ----------- | ----------------------------------------------------------------- |
| `feeling`   | `Feeling -- a subjective, non-verifiable claim (not penalizable).` |
| `fact`      | `Fact -- a disprovable assertion with a degree of truth.`          |
| `reference` | `Reference -- a citation linking to an external source.`           |
| `and`       | `AND -- true when all children are true (min trust).`              |
| `or`        | `OR -- true when any child is true (max trust).`                   |
| `not`       | `NOT -- negation of a child entry.`                                |
| `non`       | `NON -- non-affirming negation (weakens trust toward zero).`       |
| `provider`  | `Provider -- an LLM API endpoint.`                                 |
| `authority` | `Authority -- a remote knowledge base (XML URL).`                  |

### Templates

| Key         | Template                                                                                             |
| ----------- | ---------------------------------------------------------------------------------------------------- |
| `feeling`   | `<feeling>Subjective statement here.</feeling>`                                                      |
| `fact`      | `<fact trust="0.0">Assertion text here.</fact>`                                                      |
| `reference` | `<reference trust="0.0"><a href="https://example.com">Link text</a></reference>`                     |
| `and`       | `<logic><and><ref id=""/><ref id=""/></and></logic>`                                                 |
| `or`        | `<logic><or><ref id=""/><ref id=""/></or></logic>`                                                   |
| `not`       | `<logic><not><ref id=""/></not></logic>`                                                             |
| `non`       | `<logic><non><ref id=""/></non></logic>`                                                             |
| `provider`  | `<provider trust="0.0"><api_url>https://api.example.com</api_url><model>model_name</model></provider>` |
| `authority` | `<authority trust="0.0"><url>https://example.com/state.zip</url><key>password</key></authority>` |

### Empty state

| Key           | Text                                                         |
| ------------- | ------------------------------------------------------------ |
| `truth_empty` | `No truth entries. Add truth here or Open a new state file.` |
