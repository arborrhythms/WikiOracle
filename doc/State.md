# State

WikiOracle conversation state is persisted as XML, validated by `data/state.xsd`, and managed by `bin/state.py`. The canonical file is `state.xml` at the project root.

---

## Structure

A state file has three top-level parts in order:

```
State → Header + Conversation* + Truth?
```

```xml
<?xml version="1.0" encoding="UTF-8"?>
<state>
  <header>...</header>
  <conversation>...</conversation>
  <conversation>...</conversation>
  <truth>...</truth>
</state>
```

`header` is required. Top-level `conversation` elements may repeat. `truth` is optional.

---

## 1. Header

Session metadata. All fields except `user_guid` and `output` are required.

| Field | Type | Description |
|---|---|---|
| `version` | positive integer | State grammar version (currently `2`). |
| `schema` | string | Schema URL, normally `https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/state.xsd`. |
| `time` | string (ISO 8601) | Timestamp of last state write. |
| `title` | string | Document or project title. |
| `context` | XHTML | Persistent context block sent with every request. |
| `user_guid` | string (optional) | Persistent user GUID. |
| `output` | string (optional) | Output-format instruction block. |

```xml
<header>
  <version>2</version>
  <schema>https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/state.xsd</schema>
  <time>2026-03-07T12:00:00Z</time>
  <title>My Project</title>
  <context><div><p>Project context goes here.</p></div></context>
  <user_guid>a1b2c3d4-...</user_guid>
  <output></output>
</header>
```

Context, truth, and output are client-owned. The server persists them in stateful mode but does not originate them.

---

## 2. Conversations

Conversations form a recursive tree. In XML, each `<conversation>` contains a required `<title>` followed by direct child `<message>` and `<conversation>` elements. In memory, `bin/state.py` still normalizes these into `messages[]` and `children[]`.

### Grammar

```
Conversation → title + (Message | Conversation)*
Message      → { id, role, username, time, content }
```

### Conversation attributes

| Attribute | Required | Description |
|---|---|---|
| `id` | yes | Unique conversation ID. |
| `parentId` | no | Parent conversation ID, or a comma-separated list of parent IDs for a merge/diamond node. Absent on root conversations. |
| `selected` | no | Boolean. Selected conversations in the file must form one root-to-node path. |

### Message attributes

| Attribute | Required | Values | Description |
|---|---|---|---|
| `id` | yes | string | Unique message identifier. |
| `role` | yes | `user` \| `assistant` \| `system` | Message author role. |
| `username` | yes | string | Display name. |
| `time` | yes | ISO 8601 | Message timestamp. |
| `selected` | no | boolean | Optional singleton message selection across the whole state file. |

### Example

```xml
<conversation id="c_root" selected="true">
  <title>Animals</title>
  <message id="m1" role="user" username="Alice" time="2026-03-06T10:00:00Z">
    <content><Q><fact trust="0.5">Dogs are mammals.</fact></Q></content>
  </message>
  <message id="m2" role="assistant" username="claude" time="2026-03-06T10:00:05Z">
    <content><R><fact trust="0.9">Yes, dogs are mammals of the family Canidae.</fact></R></content>
  </message>
  <conversation id="c_dogs" parentId="c_root" selected="true">
    <title>Dog breeds</title>
    <message id="m3" role="user" username="Alice" time="2026-03-06T10:01:00Z" selected="true">
      <content><Q><fact trust="0.5">What breeds are common?</fact></Q></content>
    </message>
  </conversation>
</conversation>
```

The XML file persists selection through `selected="true"` attributes on conversations and messages. `bin/state.py` enforces that selected conversations form a single ancestor path and that selected messages are a singleton. For runtime compatibility, the loader still derives internal helper fields like `selected_conversation` and `selected_message` from those XML flags.

### Tree operations

`bin/state.py` exposes:

- `find_conversation(convs, id)`
- `get_ancestor_chain(convs, id)`
- `get_context_messages(convs, id)`
- `add_message_to_conversation(convs, id, msg)`
- `add_child_conversation(convs, parent_id, child)`
- `remove_conversation(convs, id)`

When a message is sent, `get_context_messages()` walks the ancestor chain from the active conversation to the root and concatenates each conversation's `messages[]` list in order.

---

## 3. Truth

`truth` is an optional container whose children are typed truth elements. The element name is the truth kind, and metadata lives on the element itself.

### Shared truth attributes

| Attribute | Applies to | Description |
|---|---|---|
| `id` | all truth kinds | Unique truth ID. |
| `title` | all truth kinds | Human-readable label. |
| `time` | all truth kinds | Timestamp. |
| `place` | all truth kinds | Optional place label for envelope-level location metadata. |
| `DoT` | all truth kinds except `feeling` | Degree of Truth on [-1, +1]. |

Operator elements may also carry `arg1` and `arg2`.

### Truth kinds

| Element | Meaning |
|---|---|
| `<fact>` | Knowledge claim or observation. |
| `<feeling>` | Subjective, non-truth-evaluable statement. No `DoT` attribute. |
| `<reference>` | External citation wrapping an `<a href="...">...</a>` link record. |
| `<and>`, `<or>`, `<not>`, `<non>` | Strong Kleene operators over other truth IDs. |
| `<provider>` | External LLM provider definition. |
| `<authority>` | Pointer to a remote truth table. |

### Example

```xml
<truth>
  <fact id="t_001" title="Mammals" DoT="0.9" time="2026-03-06T10:00:00Z">
    All dogs are mammals.
  </fact>
  <feeling id="t_002" title="Preference" time="2026-03-06T10:00:01Z">
    I prefer cats.
  </feeling>
  <reference id="t_003" title="Wikipedia: Dog" DoT="0.8">
    <a href="https://en.wikipedia.org/wiki/Dog">Wikipedia: Dog</a>
  </reference>
  <and id="t_op1" title="Both mammals" DoT="0.0" arg1="t_001" arg2="t_003" />
  <provider id="p_claude" title="Claude" DoT="0.8">
    <api_url>https://api.anthropic.com/v1/messages</api_url>
    <model>claude-sonnet-4-6</model>
  </provider>
  <authority id="a_remote" title="Remote KB" DoT="0.5">
    <url>https://example.org/truth.xml</url>
    <refresh>3600</refresh>
  </authority>
</truth>
```

Internally, `xml_to_state()` still maps each truth element back to a dict shaped like:

```python
{
    "id": "t_001",
    "title": "Mammals",
    "trust": 0.9,
    "time": "2026-03-06T10:00:00Z",
    "content": "<fact>All dogs are mammals.</fact>",
}
```

That keeps the rest of the pipeline stable while the XML surface stays typed.

### Static vs dynamic truth

When RAG is enabled, the truth table is processed in two phases:

1. `static_truth` extracts evaluable content such as facts, feelings, and references.
2. `dynamic_truth` evaluates operators, providers, and authorities against that static set.

All truth entries are still available to the final provider bundle.

---

## Serialization

`state_to_xml(state)` serializes the internal nested tree to the XML grammar above. `xml_to_state(text)` parses it back. `atomic_write_xml(path, state)` uses a temp file, `fsync`, and `rename` for atomic writes.

### Merge

`merge_llm_states(base, incoming)` merges an imported state into the current state with collision-safe deterministic ID suffixing. `merge_many_states(base, *incoming)` chains multiple merges.

---

## In-memory representation

The internal Python representation remains conversation-centric. It keeps the per-node `selected` flags and also derives helper fields such as `selected_conversation` and `selected_message` for the rest of the runtime:

```python
state = {
    "version": 2,
    "schema": "https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/state.xsd",
    "time": "2026-03-07T12:00:00Z",
    "title": "My Project",
    "context": "<div><p>...</p></div>",
    "conversations": [
        {
            "id": "c_root",
            "title": "Animals",
            "selected": True,
            "messages": [
                {"id": "m1", "role": "user", "username": "Alice",
                 "time": "...", "content": "<Q>...</Q>", "selected": True}
            ],
            "children": [
                {"id": "c_dogs", "title": "Dog breeds",
                 "messages": [...], "children": []}
            ]
        }
    ],
    "truth": [
        {"id": "t_001", "title": "Mammals", "trust": 0.9,
         "content": "<fact>All dogs are mammals.</fact>"}
    ],
    "selected_conversation": "c_root",
    "selected_message": "m1",
    "user_guid": "a1b2c3d4-...",
    "output": ""
}
```

---

## Schema

The state schema is `data/state.xsd`.

---

## See also

- [Architecture.md](./Architecture.md) — data model overview and rendering pipeline.
- [Config.md](./Config.md) — configuration format and settings.
- [Training.md](./Training.md) — how truth entries feed into online training.
- [Entanglement.md](./Entanglement.md) — data sovereignty and persistence policy.
- [WhatIsTruth.md](./WhatIsTruth.md) — certainty semantics and Kleene scale.
- [Logic.md](./Logic.md) — operator evaluation over the truth table.
- [Authority.md](./Authority.md) — authority entries and transitive trust.
- [Security.md](./Security.md) — state file security, symlink rejection, and size limits.
