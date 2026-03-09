# Voting

## Call sequence

```
Q                       user query
R_beta_1 … R_beta_n    betas see Q, respond in parallel
R_alpha                 alpha sees Q + R_beta_* — final synthesis
```

There is no preliminary alpha response. All betas receive the user query directly and respond in parallel, each contributing their own facts, feelings, and (optionally) a conversational response. The alpha then synthesizes the final response, informed by the full body of beta contributions.

## Topology

The fan-out and fan-in form a diamond:

```
           Q
         / | \
R_beta_1 R_beta_2 ... R_beta_n
         \ | /
        R_alpha
```

This is a directed acyclic graph (DAG), not a tree — the query fans out to all betas, whose contributions merge back into the alpha's synthesis. Because there may be many betas, the structure branches out and branches back in, making it technically a digraph.

## Per-beta conversation control

Each `<provider>` entry supports an optional `conversation` attribute (default `"false"`). This controls whether the beta participates visibly in the conversation tree or contributes only behind the scenes.

When `conversation="false"` (the default), the beta contributes only truth — `<fact>` and `<feeling>` tags. Its response is not displayed in the conversation tree; only its extracted truth entries are incorporated into the alpha's truth surface.

When `conversation="true"`, the beta participates as a visible peer. It receives the full conversation history and may return a `<conversation>` tag containing its answer, alongside any `<fact>` and `<feeling>` tags. Its conversational response appears as a branch in the conversation tree, forming the diamond topology.

```xml
<!-- This beta contributes truth only (invisible in the conversation) -->
<provider name="beta1" api_url="..." conversation="false"/>

<!-- This beta participates in the conversation (visible branch) -->
<provider name="beta2" api_url="..." conversation="true"/>
```

This gives the alpha author fine-grained control over which betas appear as conversational peers and which serve as silent truth consultants.

## Cycle prevention

An alpha must not participate in any vote that exists as a consequence of a vote it initiated. This is stronger than "don't appear as a beta in your own vote" — it covers the entire downstream call tree. If A initiates a vote and one of its betas (B) triggers a nested vote, A must not appear as a beta in B's vote either, because B's vote only exists because A's vote caused it.

The contract: when a provider is asked to participate in a vote, it walks the call chain to root. If it finds itself anywhere in that ancestry — as an alpha at any level — it keeps quiet (returns no response). Silence is the correct behaviour, not an error; it simply means the provider has nothing to add that isn't already represented by its alpha-role output higher in the chain.

```
A initiates vote
|- B (beta) -> B initiates nested vote
|  |- C (beta of B) - ok
|  |- A (beta of B) - A finds itself in ancestry -> keeps quiet
|  `- D (beta of B) - ok
|- C (beta) - ok
`- E (beta) - ok
```

Implementation: each vote carries a **call chain** — the ordered list of provider IDs that have acted as alpha from the root vote down to the current one. Before a provider responds as a beta, it checks whether its own ID appears anywhere in the call chain. If so, it stays silent. When a beta initiates its own nested vote, it appends its ID to the chain before calling its own betas.

The call chain grows monotonically and is threaded through every invocation, so the check is a simple walk-to-root membership test. This prevents:

* **Direct cycles**: A calls B, B calls A — A sees itself in the chain
* **Transitive cycles**: A calls B, B calls C, C calls A — A sees itself in the chain
* **Deep nesting**: A calls B, B calls C, C initiates a nested vote — A and B are both excluded from C's vote

There is no "ultimate alpha" — any node may take the alpha role in a given vote. The cycle constraint is the only structural restriction.

## All output is truth

Voters are encouraged to express *only* truth statements in their responses. `<feeling>` is a truth type — it represents a subjective, non-verifiable claim. Prior output that has not been substantiated with evidence is treated as feeling: it carries no evidential weight and is not penalizable, but it is still a legitimate part of the truth surface.

The recognized truth types in a vote response are:

* **`<fact>`** — a verifiable claim. Lying (asserting facts that contradict available evidence) is penalised by reducing the provider's trust value. Because each `<provider>` entry carries a trust score, repeated dishonesty degrades a provider's influence on future votes.
* **`<feeling>`** — a subjective, non-verifiable statement (opinion, intuition, preference). Not falsifiable, not penalizable, but carries no evidential weight.
* **`<reference>`** — a citation to an external source. Verifiable by the alpha or any downstream consumer.

```xml
<fact id="vote_01" trust="0.9" title="Socrates was mortal">
  Socrates was mortal, derived from axiom_01 and axiom_02.
</fact>
<feeling id="vote_02" trust="0.5" title="Intuition about relevance">
  The penguin example feels more pedagogically useful here.
</feeling>
```

A beta with `conversation="true"` may additionally return a `<conversation>` tag wrapping its main response to the query:

```xml
<conversation>I believe taxes should be raised modestly to fund infrastructure.</conversation>
<fact id="beta1_f1" trust="0.7" title="Infrastructure deficit">
  Current infrastructure spending is 40% below maintenance requirements.
</fact>
```

These inline truth statements enrich the trust surface available to the alpha. Unstructured prose in a response — text outside any truth or conversation tag — is treated as unsubstantiated feeling by default.
