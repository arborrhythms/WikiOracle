# State

WikiOracle state is a portable XML document managed by `bin/state.py` and described by `data/state.xsd`. The canonical local filename is `state.xml`; the shipped example is `data/state.xml`.

## Grammar

```text
State        -> Header + Conversation* + Truth?
Conversation -> title + (Message | Conversation)*
Message      -> content + attachment*
Truth        -> (Fact | Feeling | Reference | Logic | Provider | Authority)*
```

| Top-level element | Cardinality | Purpose |
|---|---:|---|
| `<header>` | Exactly one | Versioning, document identity, client label, and timestamps |
| `<conversation>` | Zero or more | Recursive conversation roots |
| `<truth>` | Zero or one | Typed TruthSet entries |

```xml
<?xml version="1.0" encoding="UTF-8"?>
<state xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:noNamespaceSchemaLocation="state.xsd">
  <header>...</header>
  <conversation id="c_root">...</conversation>
  <truth>...</truth>
</state>
```

UI preferences and provider selection are configuration, not canonical XSD state fields. They live under `<config><client>`; see [Config](./Config.md). For migration compatibility, `bin/state.py` still normalizes and round-trips a legacy runtime `ui` dictionary under the state header. That compatibility extension is not declared by `data/state.xsd` and should not be used in newly authored schema-conformant state files.

## Header

| Field | Type | Required | Description |
|---|---|---:|---|
| `version` | Positive integer | Yes | State grammar version (currently `2`) |
| `schema` | String | Yes | Schema URL or accepted `state.xsd` reference |
| `time_creation` | String | Yes | Creation timestamp |
| `time_lastModified` | String | No | Last serialized timestamp |
| `title` | String | Yes | Portable state title |
| `client_name` | String | No | Display name attached to user messages |
| `client_id` | String | No | Stable client identifier |

```xml
<header>
  <version>2</version>
  <schema>https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/state.xsd</schema>
  <time_creation>2026-07-15T10:00:00Z</time_creation>
  <time_lastModified>2026-07-15T10:05:00Z</time_lastModified>
  <title>Research session</title>
  <client_name>Alice</client_name>
  <client_id>alice-uuid-123</client_id>
</header>
```

## Conversations

Each conversation contains one `<title>` followed by any number of direct `<message>` and nested `<conversation>` children. The on-disk order preserves the order in which messages and branches appear.

### Conversation attributes

| Attribute | Required | Description |
|---|---:|---|
| `id` | Yes | Unique conversation identifier |
| `parentId` | No | Parent ID or comma-separated parent IDs for a diamond/merge node |
| `selected` | No | Boolean selection marker; selected conversations form one root-to-node path |

### Message structure

| Field/attribute | Required | Values or type | Description |
|---|---:|---|---|
| `id` | Yes | String | Unique message identifier |
| `role` | Yes | `user`, `assistant`, `system` | Message role |
| `username` | Yes | String | Display label for the author/provider |
| `time` | Yes | String | Message timestamp |
| `selected` | No | Boolean | Unique selected-message marker across the state |
| `<content>` | Yes | XHTML | Renderable message content |
| `<attachment>` | No | Repeated element | Inline data or a URL, with optional `name` and `type` |

```xml
<conversation id="c_root" selected="true">
  <title>Animals</title>
  <message id="m1" role="user" username="Alice" time="2026-07-15T10:00:01Z">
    <content><p>Are dogs mammals?</p></content>
  </message>
  <message id="m2" role="assistant" username="WikiOracle" time="2026-07-15T10:00:02Z">
    <content><p>Yes. Dogs are mammals.</p></content>
    <attachment name="taxonomy.svg" type="image/svg+xml" url="https://example.org/taxonomy.svg"/>
  </message>
  <conversation id="c_breeds" parentId="c_root" selected="true">
    <title>Dog breeds</title>
  </conversation>
</conversation>
```

### Tree and DAG behavior

| Operation | Runtime helper | Result |
|---|---|---|
| Find a node | `find_conversation()` | Recursive lookup by ID |
| Resolve context | `get_ancestor_chain()` / `get_context_messages()` | Ordered messages from root through the active node |
| Continue | `add_message_to_conversation()` | Append a message to an existing node |
| Branch | `add_child_conversation()` | Insert a child conversation |
| Delete | `remove_conversation()` | Remove a subtree |
| Vote/merge | Shared child plus multiple `parentId` values | Diamond-shaped DAG that remains navigable from each beta branch |

The serializer deduplicates a shared DAG node by ID. The `parentId` list preserves the logical multiple-parent relationship even though XML nesting has one emitted location.

## TruthSet

The optional `<truth>` element contains typed entries. Common metadata appears as attributes on each truth element.

### Common attributes

| Attribute | Applies to | Required | Description |
|---|---|---:|---|
| `id` | Every truth kind | Yes | Unique entry ID |
| `title` | Every truth kind | No | Human-readable label |
| `time` | Every truth kind | No | Timestamp |
| `place` | Every truth kind | No | Location metadata |
| `DoT` | Every kind except feeling | Yes | Degree of Truth on [-1, +1] |

### Truth kinds

| Element | Content model | Purpose |
|---|---|---|
| `<fact>` | Mixed XHTML/text | Verifiable claim or observation |
| `<feeling>` | Mixed XHTML/text | Subjective expression outside the truth lattice |
| `<reference>` | Exactly one `<a href="...">` | External citation |
| `<logic>` | One `and`, `or`, `not`, or `non` child | Strong Kleene/fuzzy derivation over `<ref>` or inline operands |
| `<provider>` | Provider-specific child fields | Dynamic expert, optionally producing a visible conversation branch |
| `<authority>` | URL plus optional refresh interval | Remote TruthSet/state source |

```xml
<truth>
  <fact id="t_dogs" title="Dogs are mammals" DoT="1.0">
    Dogs are mammals.
  </fact>
  <feeling id="t_preference" title="Preference">
    I prefer cats.
  </feeling>
  <reference id="t_reference" title="Dog reference" DoT="0.8">
    <a href="https://en.wikipedia.org/wiki/Dog">Wikipedia: Dog</a>
  </reference>
  <logic id="t_both" title="Combined support" DoT="0.8">
    <and><ref id="t_dogs"/><ref id="t_reference"/></and>
  </logic>
  <provider id="p_claude" title="Claude" DoT="0.7">
    <api_url>https://api.anthropic.com/v1/messages</api_url>
    <model>claude-sonnet-4-6</model>
    <conversation>true</conversation>
    <timeout>120</timeout>
  </provider>
  <authority id="a_remote" title="Remote knowledge" DoT="0.5">
    <url>https://example.org/state.xml</url>
    <refresh>3600</refresh>
  </authority>
</truth>
```

### Operator arity

| Operator | Operands | DoT result |
|---|---:|---|
| `and` | Two or more | Minimum operand DoT |
| `or` | Two or more | Maximum operand DoT |
| `not` | Exactly one | Negated DoT |
| `non` | Exactly one | `1 - 2 * abs(DoT)` |

See [Logic](./Logic.md) for the interpretation and completeness argument.

### Provider entry fields

| Field | Required | Meaning |
|---|---:|---|
| `api_url` | No | Dynamic provider endpoint |
| `api_key` | No | Literal key or supported indirection used by dynamic-provider resolution |
| `model` | No | Model override |
| `system` | No | XHTML system instruction |
| `authority` | No | Nested URL and optional refresh configuration |
| `conversation` | No | Whether the contribution appears as a conversation branch |
| `timeout` | No | Request timeout |
| `max_tokens` | No | Response-token cap |

## Truth Evaluation and Persistence

| Phase | Entry kinds | Behavior |
|---|---|---|
| Direct truth | Facts, feelings, references | Converted to source records for the provider bundle |
| Derived truth | Logic | Recomputes DoT from the current operand entries |
| Dynamic truth | Providers, authorities | Consults experts or imports bounded remote evidence |
| Server truth merge | Resolved facts and logic | Optional moving-average merge into `data/truth.xml` |
| Excluded from server truth | Feelings, providers, references, authorities | Must be resolved or intentionally omitted before persistence |

The server truth corpus accepts either a `<truth>` root or a `<state>` document containing `<truth>`. It is separate from the client's complete state file.

## Runtime Representation

`xml_to_state()` normalizes XML into a Python dictionary. Conversations use `messages[]` and `children[]`; truth entries use a stable envelope (`id`, `title`, `trust`, `content`, and optional metadata). Selection attributes are also exposed through helper fields such as `selected_conversation` and `selected_message`.

| XML surface | Runtime shape |
|---|---|
| Recursive `<conversation>` children | Nested `conversations[]` / `children[]` dictionaries |
| Typed truth element name | XHTML/XML in `entry["content"]` |
| `DoT` attribute | Numeric `entry["trust"]` |
| Conversation/message `selected="true"` | Per-node flags plus derived selected IDs |

## Serialization and Merge

| Function | Purpose |
|---|---|
| `state_to_xml(state)` | Serialize normalized state to typed XML |
| `xml_to_state(text)` | Parse typed XML into normalized state |
| `load_state_file(path)` | Load XML or a legacy monolithic JSON state |
| `atomic_write_xml(path, state)` | Write through a temporary file, `fsync`, and atomic rename |
| `ensure_minimal_state(state)` | Add required defaults and normalize tree/selection fields |
| `merge_llm_states(base, incoming)` | Merge portable state with deterministic collision-safe IDs |

The authoritative schema is [`data/state.xsd`](../data/state.xsd). Legacy JSON imports remain supported for migration, but newly persisted state is XML.
