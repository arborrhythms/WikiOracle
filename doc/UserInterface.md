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

