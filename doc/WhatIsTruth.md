# WhatIsTruth.md  
## Plural Truth and Shared Empathy in the Design of WikiOracle

Truth is not the same thing as consensus.

Different communities trust different sources.  
Different disciplines apply different standards of proof.  
Different cultures interpret the same facts through different lenses.

A healthy knowledge system does not erase these differences.  
It preserves them, makes them visible, and shows where they overlap. WikiOracle should not aim to speak with a single authoritative voice. It should aim to:

- Show what holds across many points of view.  
- Show where serious disagreement remains.  
- Explain why disagreement exists.  
- Make uncertainty explicit.  

Truth is strongest when it is transparent, not when it is uniform.

---

## The Problem With Current Model Development

Most large AI systems today are built around:

- A single global objective function.  
- Centralized data aggregation.  
- Implicit averaging over moral and cultural differences.  
- Hidden alignment rules.  
- Proprietary control of core knowledge.  

This produces predictable risks:

1. **Collapse into Consensus** – Minority viewpoints are quietly averaged away.  
2. **Preference Capture** – The loudest or most powerful groups shape the model at scale.  
3. **Epistemic Centralization** – A single model becomes an authority node, increasing dependence.  
4. **Conversion of Knowledge into Leverage** – Predictive advantage becomes economic or political dominance.  

When this happens, wisdom stops being a shared good and becomes a strategic asset.

---

## A Plural Model of Truth

WikiOracle should maintain multiple Points of View (POVs), each with its own trust map.

Each POV may:

- Trust different sources.  
- Weigh evidence differently.  
- Interpret claims differently.  

Instead of collapsing these into one answer, the system should:

- Present POV-conditioned conclusions.  
- Identify robust overlaps across perspectives.  
- Preserve live disputes.  
- Keep minority views visible and searchable.  

Distrust between communities is not a defect. It creates epistemic distance, preventing forced consensus. A plural system can remain coherent without being uniform. This model of truth is simultaneously multicultural (respecting diverse cultural frameworks), multivalent (allowing claims to carry different weights under different perspectives), and pluralistic (treating the coexistence of competing truths as a structural feature rather than a flaw).

---

## Empathy as Shared Constraint

Plural truth alone is not sufficient. Without shared constraints, disagreement can become manipulation or harm.

Empathy in architecture does not mean enforcing agreement. It means enforcing how disagreement is handled. The system must:

- Refuse to enable coercion or exploitation.  
- Surface potential harms and uncertainty.  
- Preserve dignity in tone and framing.  
- Keep outputs contestable and auditable.  

Beliefs may differ. Treatment must not.

Empathy lives in procedural safeguards — not in enforced sameness.

---

## Relation to the Wikipedia Model

Wikipedia provides an important precedent:

- Open participation.  
- Transparent citation.  
- Community moderation.  
- Distributed subject-matter authority.  

However, it still trends toward a single neutral narrative. Minority positions can be compressed into “fringe” categories, and editorial influence can cluster informally.

WikiOracle should extend the strengths of Wikipedia while going further:

- Support structured parallel POVs instead of a single neutral tone.  
- Make trust networks visible rather than implicit.  
- Model disagreement explicitly rather than smoothing it away.  

Instead of one neutral point of view, the system can offer visible points of view.

---

## Why This Is Stable

Growth in wisdom is not destabilizing when:

- Knowledge remains open and auditable.  
- No single actor can monopolize epistemic advantage.  
- Minority perspectives are preserved.  
- Shared constraints prevent harm and coercion.  

Such a system may disrupt business models that depend on opacity or information asymmetry. That disruption is corrective, not destructive.

Truth does not need to be centralized to be shared.
Empathy does not require uniform belief.

A stable knowledge commons decentralizes truth while universalizing care in how truth is expressed and applied.
That is the foundation for WikiOracle.

---

## HME: Hierarchical Mixture of Experts for Truth

WikiOracle implements a Hierarchical Mixture of Experts (HME) architecture for evaluating claims. The system operates on two file types:

- **State files** (`.jsonl`): contain conversations, trust entries, and context.
- **Config files** (`.yaml`): contain provider credentials, chat settings, and retrieval parameters.

### Certainty: Kleene Ternary Logic

Each trust entry carries a **certainty** value on the interval [-1, +1], encoding a Kleene ternary logic:

| Certainty | Meaning |
|-----------|---------|
| **+1** | Certainly true. An axiom that supports deductive reasoning. |
| **0 < c < +1** | Soft belief. Grounds fuzzy deductions with propagated certainty. |
| **0** | Ignorance. Equivalent to not making the statement at all; the entry is inert. |
| **-1 < c < 0** | Soft disbelief. Evidence against the claim. |
| **-1** | Certainly false. Active disbelief. |

Certainty propagates through deductive chains: a conclusion derived from two premises with certainties c1 and c2 inherits certainty min(c1, c2). Entries with certainty 0 contribute nothing to reasoning.

### Trust Entry Content Types

The `content` field of each trust entry is XHTML and may contain any combination of:

- `<p>` — Bare facts (e.g. "All men are mortal").
- `<a href="...">` — External source references (Wikipedia, Snopes, etc.) that the LLM may consult.
- `<provider>` — An LLM provider block that triggers HME fan-out.

### HME Pipeline

The truth table is gated by the `rag` config flag: when `rag` is true, **all** `state.truth` is sent to the final provider; when `rag` is false, **no** truth of any kind is sent. When enabled, the truth table is processed in two phases — static and dynamic:

```
st = static_truth(state.truth)      # facts & references (evaluable subset)
t  = st + dynamic_truth(st)         # operators, authorities, and providers
                                    # evaluated against st
```

`static_truth` selects the entries that the dynamic steps use as input. All `state.truth` entries (including structural ones) are still sent to the final provider — `static_truth` controls evaluation, not delivery.

When a user sends a query:

1. **Static truth**: `static_truth()` extracts the evaluable subset of `state.truth` — every `<fact>` and `<reference>` entry. Structural entries (`<provider>`, `<operator>`, `<authority>`) are excluded from this subset.

2. **Dynamic truth** — structural entries are evaluated against the static set:
   - **Operators**: `compute_derived_truth()` evaluates `<and>`, `<or>`, `<not>` over the truth table (Strong Kleene semantics). Derived certainty values propagate back into the entries they govern.
   - **Authorities**: Each `<authority>` entry references a remote truth table. It is fetched and its entries are appended with scaled certainty.
   - **Providers**: All `<provider>` entries are sorted by (-|certainty|, -timestamp, id). The highest-ranked becomes the **primary** provider; the rest are **secondaries**. Each secondary receives a RAG-free bundle (system context, conversation history, user query, output instructions) — but no truth entries, keeping secondary opinions independent. Their responses become sources with the provider's certainty.

3. **Primary synthesis**: The primary provider receives **all** `state.truth` entries (with operator-derived certainty where applicable), plus authority remote entries and provider evaluation responses, along with conversation history, system context, and the user message.

4. **Fallback**: If the primary provider fails, secondaries are tried in order.

### Syllogistic Examples

The file `spec/hme.jsonl` contains demonstration data that tests the reasoning engine:

- **Axioms** (certainty=1.0): "All men are mortal", "Socrates is a man", etc.
- **Valid deductions** (certainty=1.0): "Socrates is mortal" follows from the axioms.
- **Soft claims** (certainty=0.8): "Most birds can fly" — grounds fuzzy deductions.
- **Disbelief** (certainty=-0.9): "Penguins can fly" — known false despite soft premises.
- **External sources**: Wikipedia and Snopes links as verifiable references.
- **Provider entry**: A Claude `<provider>` block demonstrating HME fan-out.