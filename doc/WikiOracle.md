# WikiOracle
Revision: 2026.07.15

WikiOracle is a local-first orchestration layer for conversations, explicit truth, provider voting, and optional online learning. A browser client owns the interaction model; a Flask shim validates and executes each request; and one or more language-model providers supply responses or evidence.

![WikiOracle architecture](diagrams/wikioracle_architecture.svg)

## Architectural Overview

The durable interchange format is deliberately small: two schema-validated XML documents separate user/session data from runtime policy.

| Document | Canonical sections | Owner | Purpose |
|---|---|---|---|
| `state.xml` | `<header>`, recursive `<conversation>` elements, optional `<truth>` | Client/session | Identity metadata, conversation history, selection state, attachments, and the user's TruthSet |
| `config.xml` | `<server>` and optional `<client>` | Server policy plus client preferences | Runtime mode, truth policy, evaluation and training defaults, provider definitions, UI preferences, provider selection, and client API keys |

The same application supports two runtime contracts:

| Mode | State authority | Request/response contract | Writes |
|---|---|---|---|
| **Stateful** | Flask shim loads the canonical state file | The client may send truth overrides; `/chat` returns the selected conversation delta | State and client config may be written locally |
| **Stateless** | Browser supplies authoritative state and runtime config on every `/chat` call | `/chat` returns the full updated state | No state or config writes; client data remains in browser storage |

The public `wikioracle.org` deployment uses stateless mode. Local development can use either contract.

## State and Conversation Model

The state grammar is `Header + Conversation* + Truth?`. Conversations form a recursive tree in XML and may form a DAG in memory when a voting result has multiple parents.

| State unit | Required content | Important metadata | Role |
|---|---|---|---|
| Header | Version, schema URL, creation time, title | Last-modified time, client name, client ID | Identifies the portable state document |
| Conversation | Title plus ordered message/conversation children | `id`, optional `parentId`, optional `selected` | Represents a root session, branch, or merge node |
| Message | XHTML content and optional attachments | `id`, `role`, `username`, `time`, optional `selected` | Represents a user, assistant, or system turn |
| TruthSet | Zero or more typed truth entries | Entry IDs, titles, timestamps, place, and DoT where applicable | Supplies explicit evidence, rules, experts, and authorities |

Selection is persisted on conversation and message elements. Selected conversations form one root-to-node path; a selected message is unique across the state.

## TruthSet

Truth entries are typed XML elements rather than an unstructured prompt appendix.

| Element | DoT | Meaning | Evaluation behavior |
|---|---:|---|---|
| `<fact>` | Required | Verifiable claim or observation | Included as direct truth and eligible for derivation/training policy |
| `<feeling>` | None | Subjective, poetic, or otherwise non-truth-evaluable expression | May shape evaluation but is excluded from evidence scoring and training |
| `<reference>` | Required | External citation represented by one `<a href="...">` anchor | Grounds a claim in an inspectable source |
| `<logic>` | Required | `and`, `or`, `not`, or `non` over references or inline operands | Computes derived certainty using Strong Kleene/fuzzy semantics |
| `<provider>` | Required | Dynamic expert definition, optionally conversational | Produces evidence or a visible voting branch |
| `<authority>` | Required | Pointer to another state or TruthSet | Imports remote truth with certainty scaling and bounded fetching |

DoT values occupy [-1, +1]: -1 is certainly false, 0 is unknown, and +1 is certainly true. Feelings intentionally sit outside that truth lattice.

## Configuration Model

The configuration separates fields the operator controls from preferences a client can update.

| Scope | Major sections | Examples |
|---|---|---|
| `server` | Identity and mode | `server_id`, `stateless`, `url_prefix` |
| `server.truthset` | Truth policy | Symmetry checks, concrete-fact storage, truth weight |
| `server.evaluation` | Provider defaults | Temperature, maximum tokens, timeout, URL fetching, thought-free mode |
| `server.training` | Online learning | Enable switch, corpus path, DoT learning rates, clipping, anchoring, device |
| `server.providers` | Provider registry and shared prompts | Provider type, URL, model, timeout, streaming, context/output instructions |
| `client.ui` | Browser preferences | Layout, theme, divider position, swipe navigation, confirmation prompts |
| `client.providers` | Client selection and credentials | Default provider, default model, per-provider API key |
| `client.storage` | Cloud-storage preference | Optional state key; Dropbox app credentials remain server-only |

The server exposes a client-safe projection of config: Dropbox credentials and any legacy server-side provider key are removed. Client-owned API keys remain in `client.providers` because the browser settings flow owns and supplies them; they must therefore be treated as sensitive browser-accessible data.

## Conversation and Truth Pipeline

![WikiOracle request and truth lifecycle](diagrams/request_lifecycle.svg)

| Stage | Inputs | Result |
|---|---|---|
| 1. Normalize | User message, selected path, runtime config, client TruthSet | Valid XHTML, effective provider/model, direct and derived truth |
| 2. Consult | Dynamic provider entries, direct truth, prompt context | Conversation contributions and/or truth-only contributions from beta providers |
| 3. Synthesize | Selected main provider, history, TruthSet, authorities, derived logic, beta output | Final response plus extracted facts and feelings |
| 4. Persist | Updated conversation graph and truth policy | Full state in stateless mode or local state plus conversation delta in stateful mode |
| 5. Learn (optional) | Extracted truths, DoT, privacy/symmetry filters, training settings | Server truth merge and a bounded online-training step |

When no dynamic `<provider>` entries exist, the consultation stage collapses to a single call to the UI-selected provider. When conversational beta providers participate, WikiOracle records their branches and the final synthesis as a diamond in the conversation DAG.

## Provider Voting Example

The HME voting pattern distinguishes the provider that synthesizes the answer from providers that contribute evidence.

| Actor | Input | Output | Conversation visibility |
|---|---|---|---|
| User | Question | Query message | Root or selected branch |
| Beta provider | Query, direct truth, and role-specific context | Facts/feelings; optionally a conversational response | Hidden when `conversation=false`; visible as a branch when `true` |
| Alpha provider | Query, conversation history, TruthSet, derived truth, and beta contributions | Final answer plus extractable facts/feelings | Final merge node |

Cycle prevention carries a provider call chain through nested consultations. A provider already present in the ancestry remains silent, preventing recursive voting loops. See [Voting](./Voting.md) for the topology and [Implementation](./Implementation.md) for the endpoint and module reference.
