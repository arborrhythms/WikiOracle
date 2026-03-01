## Voting Protocol

The current HME fan-out is single-shot: secondary providers receive the query but not the primary's reasoning, and the primary synthesises their responses into a final answer. The voting protocol extends this to a two-round exchange where the primary's initial response steers the secondaries before the primary makes its final evaluation.

### Call sequence

```
Q                       user query
R_dom                   primary (dom) responds first — initial assessment
R_sub_1 … R_sub_n      secondaries (subs) see Q + R_dom, respond in parallel
R_dom_final             dom sees Q + R_dom + R_sub_* — final synthesis
```

The dom's initial response (`R_dom`) is appended to the conversation chain before it reaches the subs. Every sub sees the same chain — `Q, R_dom` — so the dom's reasoning acts as a shared steering signal. This is a per-sub choice: a sub that has a `<provider>` entry pointing at the dom can query it for steering; a sub without one simply answers from its own view of the facts.

### Topology

The fan-out and fan-in form a diamond:

```
        Q
        │
      R_dom
      / | \
R_sub₁ R_sub₂ … R_subₙ
      \ | /
    R_dom_final
```

This is a directed acyclic graph (DAG), not a tree — the dom node appears at both the top and bottom of the diamond. Because there may be many subs, the structure branches out and branches back in, making it technically a digraph.

### Cycle prevention

A dom must not participate in any vote that exists as a consequence of a vote it initiated. This is stronger than "don't appear as a sub in your own vote" — it covers the entire downstream call tree. If A initiates a vote and one of its subs (B) triggers a nested vote, A must not appear as a sub in B's vote either, because B's vote only exists because A's vote caused it.

The contract: when a provider is asked to participate in a vote, it walks the call chain to root. If it finds itself anywhere in that ancestry — as a dom at any level — it keeps quiet (returns no response). Silence is the correct behaviour, not an error; it simply means the provider has nothing to add that isn't already represented by its dom-role output higher in the chain.

```
A initiates vote
├── B (sub) → B initiates nested vote
│   ├── C (sub of B) — ok
│   ├── A (sub of B) — A finds itself in ancestry → keeps quiet
│   └── D (sub of B) — ok
├── C (sub) — ok
└── E (sub) — ok
```

Implementation: each vote carries a **call chain** — the ordered list of provider IDs that have acted as dom from the root vote down to the current one. Before a provider responds as a sub, it checks whether its own ID appears anywhere in the call chain. If so, it stays silent. When a sub initiates its own nested vote, it appends its ID to the chain before calling its own subs.

The call chain grows monotonically and is threaded through every invocation, so the check is a simple walk-to-root membership test. This prevents:

- **Direct cycles**: A calls B, B calls A — A sees itself in the chain
- **Transitive cycles**: A calls B, B calls C, C calls A — A sees itself in the chain
- **Deep nesting**: A calls B, B calls C, C initiates a nested vote — A and B are both excluded from C's vote

There is no "ultimate dom" — any node may take the dom role in a given vote. The cycle constraint is the only structural restriction.

### All output is truth

Voters are encouraged to express *only* truth statements in their responses. `<feeling>` is a truth type — it represents a subjective, non-verifiable claim. Prior output that has not been substantiated with evidence is treated as feeling: it carries no evidential weight and is not penalizable, but it is still a legitimate part of the truth surface.

The recognized truth types in a vote response are:

- **`<fact>`** — a verifiable claim. Lying (asserting facts that contradict available evidence) is penalised by reducing the provider's trust value. Because each `<provider>` entry carries a trust score, repeated dishonesty degrades a provider's influence on future votes.
- **`<feeling>`** — a subjective, non-verifiable statement (opinion, intuition, preference). Not falsifiable, not penalizable, but carries no evidential weight.
- **`<reference>`** — a citation to an external source. Verifiable by the dom or any downstream consumer.

```xml
<fact id="vote_01" trust="0.9" title="Socrates was mortal">
  Socrates was mortal, derived from axiom_01 ∧ axiom_02.
</fact>
<feeling id="vote_02" trust="0.5" title="Intuition about relevance">
  The penguin example feels more pedagogically useful here.
</feeling>
```

These inline truth statements enrich the trust surface available to downstream consumers. A sub that has queried the dom for steering can select which of its own trust entries are most relevant to the dom's uncertainty gaps, and surface them explicitly. Unstructured prose in a response — text outside any truth tag — is treated as unsubstantiated feeling by default.

### Relation to current architecture

The current `evaluate_providers()` in `response.py` implements the single-shot fan-out (Q → R_sub_* → R_dom). The voting protocol extends this to:

1. **Dom initial pass**: call the primary provider with the query to produce `R_dom`
2. **Sub fan-out**: call secondaries with `Q + R_dom` (modified `_build_provider_query_bundle` injects `R_dom` into the chain)
3. **Dom final pass**: call the primary again with `Q + R_dom + R_sub_*`

The cycle constraint is enforced by threading a `call_chain` (list of dom provider IDs) through `evaluate_providers()`. Before a sub responds, it checks whether its own ID appears in the chain; if so, it stays silent. A sub that initiates its own nested vote appends its ID to the chain before calling its own subs.

The output format is amended to encourage providers to append trust statements as escaped XHTML, so that the dom's final synthesis has a richer trust surface to draw from.
