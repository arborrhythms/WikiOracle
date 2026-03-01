## Voting Protocol

The current HME fan-out is single-shot: beta providers receive the query but not the alpha's reasoning, and the alpha synthesises their responses into a final answer. The voting protocol extends this to a two-round exchange where the alpha's initial response steers the betas before the alpha makes its final evaluation.

### Call sequence

```
Q                       user query
R_alpha                 primary (alpha) responds first — initial assessment
R_beta_1 … R_beta_n    betas see Q + R_alpha, respond in parallel
R_alpha_final           alpha sees Q + R_alpha + R_beta_* — final synthesis
```

The alpha's initial response (`R_alpha`) is appended to the conversation chain before it reaches the betas. Every beta with `prelim="true"` (the default) sees the same chain — `Q, R_alpha` — so the alpha's reasoning acts as a shared steering signal. A beta with `prelim="false"` answers cold, without seeing the alpha's preliminary response.

### Topology

The fan-out and fan-in form a diamond:

```
        Q
        │
      R_alpha
      / | \
R_beta₁ R_beta₂ … R_betaₙ
      \ | /
    R_alpha_final
```

This is a directed acyclic graph (DAG), not a tree — the alpha node appears at both the top and bottom of the diamond. Because there may be many betas, the structure branches out and branches back in, making it technically a digraph.

### Cycle prevention

An alpha must not participate in any vote that exists as a consequence of a vote it initiated. This is stronger than "don't appear as a beta in your own vote" — it covers the entire downstream call tree. If A initiates a vote and one of its betas (B) triggers a nested vote, A must not appear as a beta in B's vote either, because B's vote only exists because A's vote caused it.

The contract: when a provider is asked to participate in a vote, it walks the call chain to root. If it finds itself anywhere in that ancestry — as an alpha at any level — it keeps quiet (returns no response). Silence is the correct behaviour, not an error; it simply means the provider has nothing to add that isn't already represented by its alpha-role output higher in the chain.

```
A initiates vote
├── B (beta) → B initiates nested vote
│   ├── C (beta of B) — ok
│   ├── A (beta of B) — A finds itself in ancestry → keeps quiet
│   └── D (beta of B) — ok
├── C (beta) — ok
└── E (beta) — ok
```

Implementation: each vote carries a **call chain** — the ordered list of provider IDs that have acted as alpha from the root vote down to the current one. Before a provider responds as a beta, it checks whether its own ID appears anywhere in the call chain. If so, it stays silent. When a beta initiates its own nested vote, it appends its ID to the chain before calling its own betas.

The call chain grows monotonically and is threaded through every invocation, so the check is a simple walk-to-root membership test. This prevents:

- **Direct cycles**: A calls B, B calls A — A sees itself in the chain
- **Transitive cycles**: A calls B, B calls C, C calls A — A sees itself in the chain
- **Deep nesting**: A calls B, B calls C, C initiates a nested vote — A and B are both excluded from C's vote

There is no "ultimate alpha" — any node may take the alpha role in a given vote. The cycle constraint is the only structural restriction.

### Per-beta prelim control

Each `<provider>` entry supports an optional `prelim` attribute (default `"true"`). When `prelim="true"`, the beta receives the alpha's preliminary response as a steering signal. When `prelim="false"`, the beta answers the query cold — it does not see `R_alpha` in its history.

```xml
<!-- This beta sees Q + R_alpha (steered) -->
<provider name="beta1" api_url="..." prelim="true"/>

<!-- This beta answers cold (unsteered) -->
<provider name="beta2" api_url="..." prelim="false"/>
```

This gives the alpha author fine-grained control over which betas benefit from steering and which should form independent opinions.

### All output is truth

Voters are encouraged to express *only* truth statements in their responses. `<feeling>` is a truth type — it represents a subjective, non-verifiable claim. Prior output that has not been substantiated with evidence is treated as feeling: it carries no evidential weight and is not penalizable, but it is still a legitimate part of the truth surface.

The recognized truth types in a vote response are:

- **`<fact>`** — a verifiable claim. Lying (asserting facts that contradict available evidence) is penalised by reducing the provider's trust value. Because each `<provider>` entry carries a trust score, repeated dishonesty degrades a provider's influence on future votes.
- **`<feeling>`** — a subjective, non-verifiable statement (opinion, intuition, preference). Not falsifiable, not penalizable, but carries no evidential weight.
- **`<reference>`** — a citation to an external source. Verifiable by the alpha or any downstream consumer.

```xml
<fact id="vote_01" trust="0.9" title="Socrates was mortal">
  Socrates was mortal, derived from axiom_01 ∧ axiom_02.
</fact>
<feeling id="vote_02" trust="0.5" title="Intuition about relevance">
  The penguin example feels more pedagogically useful here.
</feeling>
```

These inline truth statements enrich the trust surface available to downstream consumers. A beta that has queried the alpha for steering can select which of its own trust entries are most relevant to the alpha's uncertainty gaps, and surface them explicitly. Unstructured prose in a response — text outside any truth tag — is treated as unsubstantiated feeling by default.

### Relation to current architecture

The current `evaluate_providers()` in `response.py` implements the single-shot fan-out (Q → R_beta_* → R_alpha). The voting protocol extends this to:

1. **Alpha initial pass**: call the primary provider with the query to produce `R_alpha`
2. **Beta fan-out**: call betas with `Q + R_alpha` (modified `_build_provider_query_bundle` injects `R_alpha` into the chain, respecting each beta's `prelim` setting)
3. **Alpha final pass**: call the primary again with `Q + R_alpha + R_beta_*`

The cycle constraint is enforced by threading a `call_chain` (list of alpha provider IDs) through `evaluate_providers()`. Before a beta responds, it checks whether its own ID appears in the chain; if so, it stays silent. A beta that initiates its own nested vote appends its ID to the chain before calling its own betas.

The output format is amended to encourage providers to append trust statements as escaped XHTML, so that the alpha's final synthesis has a richer trust surface to draw from.
