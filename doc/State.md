# State

WikiOracle conversation state is persisted as XML, validated by `data/state.xsd`, and managed by `bin/state.py`. The canonical file is `state.xml` at the project root.


## Structure

A state file has three top-level parts in order:

```
State → Client + Conversation* + Truth?
```

```xml
<?xml version="1.0" encoding="UTF-8"?>
<state>
  <client>...</client>
  <conversation>...</conversation>
  <conversation>...</conversation>
  <truth>...</truth>
</state>
```

`client` is required. Top-level `conversation` elements may repeat. `truth` is optional.


## Default state format

The state file is an XML document containing a `<truth>` section. It may be a full WikiOracle State file (with `<state>` root) or an abbreviated file with just a `<truth>` root:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<truth>
  <fact id="remote_01" title="Water is wet" DoT="1.0" time="2026-02-27T00:00:01Z">
    Water is wet.
  </fact>
  <fact id="remote_02" title="Fire is hot" DoT="0.9" time="2026-02-27T00:00:02Z">
    Fire is hot.
  </fact>
</truth>
```

## Server State
* The server persists only the TruthSet of the State, not any conversations.
* The server is stateless with respect to conversations, which means that state is always passed from (and owned by) the client.
* State files are read from `file://` within the data directory.


## Security considerations

* **URL scheme restriction**: Only `https://` and `file://` (within `ALLOWED_DATA_DIR`) are permitted
* **Max response size**: Fetched data is capped at 1 MB
* **Max entries per authority**: At most 1000 trust entries are imported per authority
* **No recursive authorities**: If a remote state file contains `<authority>` entries, they are skipped. There is no transitive fetch chain — only one level of authority delegation is supported.
* **Rate limiting**: The in-memory cache prevents excessive re-fetching within the refresh interval

## Client

Client metadata. All fields except `client_name`, `client_id`, and `ui` are required.

| Field | Type | Description |
|---|---|---|
| `version` | positive integer | State grammar version (currently `2`). |
| `schema` | string | Schema URL, normally `https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/state.xsd`. |
| `time_creation` | string (ISO 8601) | Timestamp of initial state creation. |
| `time_lastModified` | string (ISO 8601) | Timestamp of last state write. |
| `title` | string | Document or project title. |
| `client_name` | string (optional) | Display name of the client user. |
| `client_id` | string (optional) | Persistent client identifier (UUID). |
| `ui` | element (optional) | UI preferences block (see below). |

### UI preferences

The `<ui>` block inside `<client>` stores client-owned UI preferences.

| Field | Type | Description |
|---|---|---|
| `layout` | string | Layout mode (e.g. `horizontal`). |
| `theme` | string | Color theme (`system`, `light`, `dark`). |
| `model` | string | Preferred model identifier (may be empty). |
| `splitter_pct` | integer | Splitter position as a percentage (`0`--`100`). |
| `swipe_nav_horizontal` | boolean | Enable horizontal swipe navigation. |
| `swipe_nav_vertical` | boolean | Enable vertical swipe navigation. |
| `confirm_actions` | boolean | Whether to prompt before destructive actions. |

```xml
<client>
  <version>2</version>
  <schema>https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/state.xsd</schema>
  <time_creation>2026-03-07T12:00:00Z</time_creation>
  <time_lastModified>2026-03-07T12:00:00Z</time_lastModified>
  <title>My Project</title>
  <client_name>Alice</client_name>
  <client_id>a1b2c3d4-...</client_id>
  <ui>
    <layout>horizontal</layout>
    <theme>system</theme>
    <model></model>
    <splitter_pct>0</splitter_pct>
    <swipe_nav_horizontal>true</swipe_nav_horizontal>
    <swipe_nav_vertical>false</swipe_nav_vertical>
    <confirm_actions>false</confirm_actions>
  </ui>
</client>
```

Context and output format instructions have moved to `config.providers`. See [Config.md](./Config.md).

Truth is client-owned. The server persists it in stateful mode but does not originate it.

---

## Conversations

Conversations form a recursive tree. In XML, each `<conversation>` contains a required `<title>` followed by direct child `<message>` and `<conversation>` elements. In memory, `bin/state.py` still normalizes these into `messages[]` and `children[]`.

### Grammar

```
Conversation → title + (Message | Conversation)*
Message      → <message id="" role="" username="" time=""><content>...</content></message>
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

* `find_conversation(convs, id)`
* `get_ancestor_chain(convs, id)`
* `get_context_messages(convs, id)`
* `add_message_to_conversation(convs, id, msg)`
* `add_child_conversation(convs, parent_id, child)`
* `remove_conversation(convs, id)`

When a message is sent, `get_context_messages()` walks the ancestor chain from the active conversation to the root and concatenates each conversation's `messages[]` list in order.

## TruthSet

`truth` is an optional container whose children are typed truth elements. The element name is the truth kind, and metadata lives on the element itself.

### Shared truth attributes

| Attribute | Applies to | Description |
|---|---|---|
| `id` | all truth kinds | Unique truth ID. |
| `title` | all truth kinds | Human-readable label. |
| `time` | all truth kinds | Timestamp. |
| `place` | all truth kinds | Optional place label for envelope-level location metadata. |
| `DoT` | all truth kinds except `feeling` | Degree of Truth on [-1, +1]. |

### Truth kinds

| Element | Meaning |
|---|---|
| `<fact>` | Knowledge claim or observation. |
| `<feeling>` | Subjective, non-truth-evaluable statement. No `DoT` attribute. |
| `<reference>` | External citation wrapping an `<a href="...">...</a>` link record. |
| `<logic>` | Strong Kleene operator (`<and>`, `<or>`, `<not>`, `<non>`) over other truth entries. Wraps one operator child with `<ref>` or inline `<fact>`/`<feeling>` operands. |
| `<provider>` | External LLM provider definition. |
| `<authority>` | Pointer to a remote TruthSet. |

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
  <logic id="t_op1" title="Both mammals" DoT="0.0">
    <and><ref id="t_001"/><ref id="t_003"/></and>
  </logic>
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

Internally, `xml_to_state()` still normalizes each typed truth element into the
runtime representation, but on disk it remains XML:

```xml
<fact id="t_001" title="Mammals" DoT="0.9" time="2026-03-06T10:00:00Z">
  All dogs are mammals.
</fact>
```

That keeps the rest of the pipeline stable while the XML surface stays typed.

### Static vs dynamic truth

When RAG is enabled, the TruthSet is processed in two phases:

1. `static_truth` extracts evaluable content such as facts, feelings, and references.
2. `dynamic_truth` evaluates operators, providers, and authorities against that static set.

All truth entries are still available to the final provider bundle.

## Serialization

`state_to_xml(state)` serializes the internal nested tree to the XML grammar above. `xml_to_state(text)` parses it back. `atomic_write_xml(path, state)` uses a temp file, `fsync`, and `rename` for atomic writes.

### Merge

`merge_llm_states(base, incoming)` merges an imported state into the current state with collision-safe deterministic ID suffixing. `merge_many_states(base, *incoming)` chains multiple merges.


## In-memory representation

The internal runtime representation remains conversation-centric. It keeps the
per-node `selected` flags and also derives helper fields such as
`selected_conversation` and `selected_message` from persisted XML like this:

```xml
<state>
  <client>
    <version>2</version>
    <schema>https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/state.xsd</schema>
    <time_creation>2026-03-07T12:00:00Z</time_creation>
    <time_lastModified>2026-03-07T12:00:00Z</time_lastModified>
    <title>My Project</title>
    <client_name>Alice</client_name>
    <client_id>a1b2c3d4-...</client_id>
    <ui>
      <layout>horizontal</layout>
      <theme>system</theme>
      <model></model>
      <splitter_pct>0</splitter_pct>
      <swipe_nav_horizontal>true</swipe_nav_horizontal>
      <swipe_nav_vertical>false</swipe_nav_vertical>
      <confirm_actions>false</confirm_actions>
    </ui>
  </client>
  <conversation id="c_root" selected="true">
    <title>Animals</title>
    <message id="m1" role="user" username="Alice" time="..." selected="true">
      <content><Q>...</Q></content>
    </message>
    <conversation id="c_dogs" parentId="c_root">
      <title>Dog breeds</title>
    </conversation>
  </conversation>
  <truth>
    <fact id="t_001" title="Mammals" DoT="0.9">
      All dogs are mammals.
    </fact>
  </truth>
</state>
```

At runtime, `bin/state.py` normalizes that XML into conversation nodes with
`messages[]` and `children[]`, and derives helpers such as
`selected_conversation="c_root"` and `selected_message="m1"`.


## Schema

The state schema is (`data/state.xsd`)[state.xsd].

## Data model

### On disk — XML

State is persisted as XML (WikiOracle State format, validated by `data/state.xsd`). The XML surface is:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<state>
  <client>
    <version>2</version>
    <schema>https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/state.xsd</schema>
    <time_creation>2026-03-05T12:00:00Z</time_creation>
    <time_lastModified>2026-03-05T12:00:00Z</time_lastModified>
    <title>My Project</title>
    <client_name>Alice</client_name>
    <client_id>a1b2c3d4-...</client_id>
  </client>
  <conversation id="c_abc">
    <title>Animals</title>
    <message id="m1" role="user" username="Alice" time="...">
      <content><Q><fact trust="0.5">Dogs are mammals.</fact></Q></content>
    </message>
    <conversation id="c_def" parentId="c_abc">
      <title>Dogs</title>
      <message id="m2" role="assistant" username="claude" time="...">
        <content><R><fact trust="0.9">Dogs are mammals.</fact></R></content>
      </message>
    </conversation>
  </conversation>
  <truth>
    <fact id="t_001" title="Mammals" DoT="0.9" time="...">
      All dogs are mammals.
    </fact>
  </truth>
</state>
```

### In memory — nested tree

On load, conversations are normalized into a nested tree in memory. The same
shape in XML is:

```xml
<conversations>
  <conversation id="c_abc">
    <title>Animals</title>
    <messages />
    <conversations>
      <conversation id="c_def">
        <title>Dogs</title>
        <messages />
        <conversations />
      </conversation>
      <conversation id="c_ghi">
        <title>Cats</title>
        <messages />
        <conversations />
      </conversation>
    </conversations>
  </conversation>
</conversations>
```

Each **conversation** has: `id`, `title`, zero or more messages, and zero or
more child conversations.

Each **message** has: `id`, `role` (user | assistant | system), `username`, `timestamp`, `content` (XHTML).

### Grammar

```
State        → Client + Conversation* + Truth?
Conversation → title + (Message | Conversation)*
Message      → <message id="" role="" username="" time=""><content>...</content></message>
Truth        → Fact | Feeling | Reference | Logic | Provider | Authority
```

In memory, `bin/state.py` still normalizes conversations into `messages[]` and `children[]`.
