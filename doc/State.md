# State

WikiOracle conversation state is persisted as XML (WikiOracle State format), validated by `data/state.xsd`, and managed by `bin/state.py`. The canonical file is `state.xml` at the project root.

---

## Structure

A state file has three top-level sections:

```
State → Header + Conversations + Truth
```

```xml
<?xml version="1.0" encoding="UTF-8"?>
<state>
  <header>...</header>
  <conversations>...</conversations>
  <truth>...</truth>
</state>
```

---

## 1. Header

Session metadata. All fields except `selected_conversation`, `user_guid`, and `output` are required.

| Field | Type | Description |
|---|---|---|
| `version` | positive integer | State grammar version (currently `2`). |
| `schema` | string | Schema identifier URL. |
| `time` | string (ISO 8601) | Timestamp of last state write. |
| `title` | string | Document/project title. |
| `context` | XHTML | System context window sent to the LLM with every request. This is the persistent instruction block that frames all conversations. |
| `selected_conversation` | string (optional) | ID of the currently selected conversation in the UI. |
| `user_guid` | string (optional) | Persistent user GUID (matches `config.xml` `user.uid`). |
| `output` | string (optional) | Output format instructions sent to the LLM. |

```xml
<header>
  <version>2</version>
  <schema>https://wikioracle.org/schemas/state/v2</schema>
  <time>2026-03-06T12:00:00Z</time>
  <title>My Project</title>
  <context><div><p>Project context goes here.</p></div></context>
  <selected_conversation>c_abc</selected_conversation>
  <user_guid>a1b2c3d4-...</user_guid>
  <output></output>
</header>
```

### Context, truth, and output are client-owned

Context, truth, and output are **client-owned** — they flow client → server only. The server never sends them back in a chat response. In stateful mode, the server persists them to `state.xml`. On error rollback, the client reloads conversations from the server but preserves its own context, truth, and output. See [Entanglement.md](./Entanglement.md) for the data sovereignty model.

---

## 2. Conversations

Conversations form a recursive tree. Each conversation has an ordered list of messages and may contain child conversations (branches).

### Grammar

```
Conversations → Conversation*
Conversation  → { id, title, messages: Message*, children: Conversation*, parentId? }
Message       → { id, role, username, time, content }
```

### Conversation attributes

| Attribute | Required | Description |
|---|---|---|
| `id` | yes | Unique identifier (e.g. `c_abc123`). Auto-generated if missing. |
| `parentId` | no | ID of the parent conversation. Present on child nodes; absent on root conversations. |

### Conversation elements

| Element | Description |
|---|---|
| `title` | Display title (auto-derived from the first message if not set). |
| `messages` | Ordered list of messages in this conversation. |
| `children` | Child conversations (branches). Nests naturally in XML — no flatten/unflatten needed. |

### Message attributes

| Attribute | Required | Values | Description |
|---|---|---|---|
| `id` | yes | string | Unique message identifier (e.g. `m_xyz789`). |
| `role` | yes | `user` \| `assistant` \| `system` | Message author role. |
| `username` | yes | string | Display name (user's name or provider's display name). |
| `time` | yes | ISO 8601 | Message timestamp. |

### Message content

Message content is **XHTML** — a well-formed XML subset of HTML. The Sensation preprocessor (`bin/sensation.py`) wraps sentences in semantic tags:

- `<Q>` — user query (wraps user messages)
- `<R>` — response (wraps assistant messages)
- `<fact trust="0.5">` — factual claim with a trust value
- `<feeling>` — subjective statement (opinion, poetry, hedged claim)

Facts and feelings may contain child elements for spacetime grounding:
- `<place>` — geographic location
- `<time>` — temporal reference

```xml
<conversation id="c_abc" parentId="">
  <title>Animals</title>
  <messages>
    <message id="m1" role="user" username="Alice" time="2026-03-06T10:00:00Z">
      <content><Q><fact trust="0.5">Dogs are mammals.</fact></Q></content>
    </message>
    <message id="m2" role="assistant" username="claude" time="2026-03-06T10:00:05Z">
      <content><R><fact trust="0.9">Yes, dogs are mammals of the family Canidae.</fact></R></content>
    </message>
  </messages>
  <children>
    <conversation id="c_def" parentId="c_abc">
      <title>Dog breeds</title>
      <messages>...</messages>
      <children/>
    </conversation>
  </children>
</conversation>
```

### Tree operations

The conversation tree supports these operations (implemented in `bin/state.py`):

| Function | Purpose |
|---|---|
| `find_conversation(convs, id)` | Recursive tree lookup by ID. |
| `get_ancestor_chain(convs, id)` | Walk from a conversation up to the root, returning the ancestor list. |
| `get_context_messages(convs, id)` | Collect all messages from root to the given conversation, in chronological order. This is the context sent to the LLM. |
| `add_message_to_conversation(convs, id, msg)` | Append a message to a conversation. |
| `add_child_conversation(convs, parent_id, child)` | Insert a new branch under a parent. |
| `remove_conversation(convs, id)` | Delete a conversation subtree. |

### Context for the LLM

When a message is sent, `get_context_messages()` walks the ancestor chain from the active conversation to the root, collecting all messages in order:

```
Root conversation      →  messages: [m1, m2, m3]
  └── Child conv       →  messages: [m4, m5]
        └── Grandchild →  messages: [m6, m7]  ← active

Context sent to LLM: [m1, m2, m3, m4, m5, m6, m7]
```

This gives the LLM the full path of dialogue without noise from sibling branches.

---

## 3. Truth table

A flat array of truth entries. Each entry carries self-describing XHTML content and optional metadata.

### Truth entry attributes

| Attribute | Required | Description |
|---|---|---|
| `id` | yes | Unique identifier (e.g. `t_001`). |
| `title` | no | Human-readable label for display. |
| `trust` | no | Certainty on the Strong Kleene scale [-1, +1]. See [WhatIsTruth.md](./WhatIsTruth.md). |
| `time` | no | ISO 8601 timestamp. |
| `arg1` | no | First argument ID (for binary operators like `and`, `or`). |
| `arg2` | no | Second argument ID (for binary operators). |

### Truth entry types

The XHTML content tag determines the entry type:

| Tag | Type | Description |
|---|---|---|
| `<fact trust="...">` | Fact | A knowledge claim with a certainty value. Universal facts are durable truths (broad spatiotemporal extent); particular facts are time-bound observations (narrow extent). See [Entanglement.md](./Entanglement.md) §Spatiotemporal Extent. |
| `<feeling>` | Feeling | A subjective statement — opinion, preference, poetry, hedged claim. Occupies the "neither" position in the tetralemma. Excluded from training and truth merge. See [BuddhistLogic.md](./BuddhistLogic.md). |
| `<reference>` | Reference | An external source citation (URL, DOI, etc.) that grounds claims in verifiable sources. |
| `<and arg1="..." arg2="...">` | Operator | Logical conjunction under Strong Kleene semantics. See [Logic.md](./Logic.md). |
| `<or arg1="..." arg2="...">` | Operator | Logical disjunction. |
| `<not arg1="...">` | Operator | Classical negation. |
| `<non arg1="...">` | Operator | Non-affirming negation (prasajya). See [Non.md](./Non.md). |
| `<provider>` | Provider | An external LLM endpoint used as an expert consultant in the HME pipeline. Contains `<url>`, `<api_key>`, `<model>`, and `<system>` child elements. See [HierarchicalMixtureOfExperts.md](./HierarchicalMixtureOfExperts.md). |
| `<authority>` | Authority | A pointer to an external truth table. Entries are imported with scaled certainty during the dynamic truth phase. See [Authority.md](./Authority.md). |

```xml
<truth>
  <entry id="t_001" title="Mammals" trust="0.9" time="2026-03-06T10:00:00Z">
    <content><fact trust="0.9">All dogs are mammals.</fact></content>
  </entry>
  <entry id="t_002" title="Preference" trust="0.5">
    <content><feeling>I prefer cats.</feeling></content>
  </entry>
  <entry id="t_003" title="Wikipedia: Dog" trust="0.8">
    <content><reference>https://en.wikipedia.org/wiki/Dog</reference></content>
  </entry>
  <entry id="t_op1" title="Both mammals" arg1="t_001" arg2="t_003">
    <content><and arg1="t_001" arg2="t_003">Both the fact and the reference agree.</and></content>
  </entry>
</truth>
```

### Static vs dynamic truth

The truth table is processed in two phases during the chat pipeline (when RAG is enabled):

1. **Static truth** — extracts the evaluable subset: `<fact>`, `<feeling>`, and `<reference>` entries carrying propositional content.
2. **Dynamic truth** — evaluates structural entries (`<operator>`, `<authority>`, `<provider>`) against the static set. Derived certainty propagates back into the entries.

All entries — both static and structural — are sent to the final provider. See [Architecture.md](./Architecture.md) §Chat pipeline for the full flow.

---

## Serialization

`state_to_xml(state)` serializes the nested tree to XML. `xml_to_state(text)` parses it back. `atomic_write_xml(path, state)` performs atomic writes (temp file + fsync + rename) to prevent corruption.

### Merge

`merge_llm_states(base, incoming)` merges an imported state into the current state with collision-safe deterministic ID suffixing. `merge_many_states(base, *incoming)` chains multiple merges. The merge preserves conversation hierarchy and deduplicates messages by fingerprint.

---

## In-memory representation

On load, conversations are represented as a nested tree of Python dicts:

```python
state = {
    "version": 2,
    "schema": "...",
    "time": "2026-03-06T12:00:00Z",
    "title": "My Project",
    "context": "<div><p>...</p></div>",
    "conversations": [
        {
            "id": "c_abc",
            "title": "Animals",
            "messages": [
                {"id": "m1", "role": "user", "username": "Alice",
                 "time": "...", "content": "<Q>...</Q>"}
            ],
            "children": [
                {"id": "c_def", "title": "Dogs", "messages": [...], "children": []}
            ]
        }
    ],
    "truth": [
        {"id": "t_001", "title": "Mammals", "trust": 0.9,
         "content": "<fact trust=\"0.9\">All dogs are mammals.</fact>"}
    ],
    "selected_conversation": "c_abc",
    "user_guid": "a1b2c3d4-...",
    "output": ""
}
```

---

## Session portability

State files can be exported from phone or browser sessions as `llm_YYYY.MM.DD.HHMM.xml`, then merged into a local project's `state.xml` later. This provides a clean integration path with Claude Code, OpenAI Codex, or any local tooling that can read the state file for project context.

```bash
# CLI merge
python bin/wikioracle.py merge llm_2026.03.06.1200.xml llm_2026.03.05.0900.xml

# Auto-merge on startup (when WIKIORACLE_AUTO_MERGE_ON_START=true)
# imports any llm_*.xml files found in the project root
```

---

## Schema

The XML schema is defined in `data/state.xsd`. The legacy JSON schema is `data/llm_state.json`.

---

## See also

- [Architecture.md](./Architecture.md) — data model overview and rendering pipeline.
- [Config.md](./Config.md) — configuration format and settings.
- [Training.md](./Training.md) — how truth entries feed into online training.
- [Entanglement.md](./Entanglement.md) — data sovereignty, three-channel separation, persistence policy.
- [WhatIsTruth.md](./WhatIsTruth.md) — plural truth, certainty semantics, Kleene scale.
- [Logic.md](./Logic.md) — operator evaluation over the truth table.
- [Authority.md](./Authority.md) — authority entries and transitive trust.
- [Security.md](./Security.md) — state file security, symlink rejection, size limits.
