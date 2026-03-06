# Logic

## Logical operators in WikiOracle's truth system

WikiOracle's truth layer supports four logical connectives — **and**, **or**, **not**, **non** — evaluated under Strong Kleene semantics on a continuous certainty scale [-1, +1]. These operators let you compose existing trust entries into derived propositions whose certainty is computed automatically.

Wikipedia links (core):
- [Three-valued logic (Kleene)](https://en.wikipedia.org/wiki/Three-valued_logic)
- [Material conditional](https://en.wikipedia.org/wiki/Material_conditional)
- [Logical connective](https://en.wikipedia.org/wiki/Logical_connective)
- [Relevance logic](https://en.wikipedia.org/wiki/Relevance_logic)

---

## Strong Kleene evaluation

WikiOracle extends Strong Kleene logic from discrete {T, U, F} to a continuous scale [-1, +1], where +1 is full belief, -1 is full disbelief, and 0 is maximally uncertain.

The four operators:

- **and(a, b, …)** = min(certainty_a, certainty_b, …) — conjunction is only as strong as the weakest operand.
- **or(a, b, …)** = max(certainty_a, certainty_b, …) — disjunction takes the strongest operand.
- **not(a)** = −certainty_a — negation flips the sign (affirming negation).
- **non(a)** = 1 − 2|a| — non-affirming negation. Measures epistemic openness: how much certainty room remains. Full certainty in either direction (±1) yields −1 (fully closed); ignorance (0) yields +1 (fully open). See `doc/Non.md` for the Buddhist philosophical motivation.

These operators compose freely — for instance, material implication (A → B) falls out as `or(not(A), B)`.

The key insight behind `non`: Kleene logic cannot detect uncertainty; it can only transmit it. `non` introduces uncertainty as a first-class observable. If WikiOracle needs to reason about openness rather than merely propagate it, then `non` is not ornamental — it is structurally necessary. See [`doc/Non.md`](Non.md) for the proof and the Buddhist philosophical motivation.

---

## Storage format (unified XHTML)

All trust entries use a unified XHTML format where the root element carries `id`, `certainty`, and `title` attributes. Operator entries use `<and>`, `<or>`, `<not>`, or `<non>` root tags with `<child id="..."/>` self-closing children:

```json
{
  "type": "truth",
  "id": "op_socrates_mortal",
  "title": "Socrates is mortal (AND of axioms)",
  "certainty": 0.0,
  "content": "<and id=\"op_socrates_mortal\" certainty=\"0.0\" title=\"Socrates is mortal (AND of axioms)\"><child id=\"axiom_01\"/><child id=\"axiom_02\"/></and>",
  "time": "2026-02-25T00:00:01Z"
}
```

```json
{
  "type": "truth",
  "id": "op_not_penguin_fly",
  "title": "Penguins cannot fly (NOT)",
  "certainty": 0.0,
  "content": "<not id=\"op_not_penguin_fly\" certainty=\"0.0\" title=\"Penguins cannot fly (NOT)\"><child id=\"false_01\"/></not>",
  "time": "2026-02-25T00:00:04Z"
}
```

Rules:
- `<and>` and `<or>` require 2 or more `<child>` children.
- `<not>` and `<non>` require exactly 1 `<child>` child.
- Each `<child id="..."/>` must name an existing trust entry ID.
- IDs are bare (no prefixes). UUIDs or human-readable slugs are both acceptable.
- The `id` and `certainty` on the root element are canonical; envelope fields are synced from them during normalization.

---

## Derived truth engine

`compute_derived_truth()` in `bin/truth.py` evaluates all operator entries using fixed-point iteration:

1. Build a certainty lookup `{ id: certainty }` from all trust entries.
2. Extract operators via `parse_operator_block()`.
3. Iterate (max 100 rounds):
   - For each operator entry, compute its certainty from its operands (and/or/not/non).
   - If no values changed (within ε = 1e-9), stop (fixed point reached).
4. Return the complete derived certainty table.

Operators derive their **own** entry's certainty from their operands. They do not modify other entries. This is a side-effect-free model: an operator's certainty is always a deterministic function of its referenced operands.

### Chaining and cycles

Operators can reference other operator entries, forming chains (e.g., an OR whose operands include an AND). Fixed-point iteration handles this naturally. Cycles terminate because min/max/negate are monotone or contracting on [-1, +1] — the iteration converges or hits the 100-round cap.

---

## Feelings — outside the truth lattice

Feelings (`<feeling>` entries) are **not** part of the truth lattice.  They occupy the *neither* position in the Buddhist tetralemma — they are pre-conceptual experiential signals that are neither true nor false.

- Feelings carry **no trust attribute**.  They are orthogonal to the certainty scale.
- Feelings are **excluded from operator evaluation** — they cannot appear as operands of `<and>`, `<or>`, `<not>`, or `<non>`.
- Feelings are **excluded from model training** — they do not contribute to DegreeOfTruth or update NanoChat weights.
- Feelings are **excluded from server persistence** — only knowledge facts, operators, authorities, and references are stored.

Examples of feelings: greetings ("Hello!"), encouragement ("That's a great question!"), poetry, and subjective expressions without an IS-predicate.

---

## Fact kinds — knowledge vs news

Facts are classified into two kinds based on spatiotemporal binding:

| Kind | Binding | Persistence | Buddhist Equivalent |
|---|---|---|---|
| **knowledge** | universal / no spacetime anchor | server truth table | *anumāna* (inference) |
| **news** | bound to a specific place and/or time | session-only | *pratyakṣa* (direct perception) |

The classification is stored in the `kind` attribute of `<fact>` tags:

```xml
<fact trust="0.9" kind="knowledge">Water contains hydrogen and oxygen.</fact>
<fact trust="0.7" kind="news" spacetime="Paris, 2026-03-05">The Eiffel Tower is lit up tonight.</fact>
```

Knowledge facts are persisted to the server truth table (`truth.xml`) because they represent universal claims.  News facts are session-only because they are spatiotemporally bound — persisting them risks "worldline capture" where an observer could reconstruct a user's physical trajectory through time and space.

The `detect_identifiability()` function in `bin/truth.py` provides an additional safety layer by scanning content for PII patterns (email addresses, phone numbers, GPS coordinates, street addresses, etc.) that could identify a user through spatiotemporal observation.

---

## Future directions

The current operator set covers propositional logic under Strong Kleene semantics. Planned extensions:

- **Nested composition** — allowing operator tags within operator tags in a single content string, reducing multi-entry boilerplate for compound expressions.
- **Implication encodings** — the current operators already express material implication via `or(not(A), B)`. Richer conditionals (strict implication, relevance-gated implication) may follow if use cases warrant them.

---

## Integration points

| File | Function |
|---|---|
| `bin/truth.py` | `parse_operator_block()`, `ensure_operator_id()`, `compute_derived_truth()`, `_eval_operator()` |
| `bin/response.py` | Excludes operator entries from RAG via `_has_operator_tag()`; uses `_derived_certainty` for ranking |
| `client/util.js` | Trust editor UI: unified XHTML textarea with template dropdown (AND/OR/NOT/NON), IDs visible for `<child id>` references |
| `test/hme.xml` | Test data with AND, OR, NOT, NON operator entries |
| `test/test_derived_truth.py` | Unit tests covering parsing, ID generation, and/or/not/non evaluation, chaining, cycles, and hme.xml integration |

---

## See also

- [Non.md](./Non.md) — full treatment of non-affirming negation: Buddhist motivation, fuzzy interpretation, completeness proof.
- [HierarchicalMixtureOfExperts.md](./HierarchicalMixtureOfExperts.md) — operators as part of the HME pipeline.
- [WhatIsTruth.md](./WhatIsTruth.md) — Kleene certainty semantics and plural truth model.
- [BuddhistLogic.md](./BuddhistLogic.md) — tetralemma, fact kinds (anumāna/pratyakṣa), feelings as "neither" position.
- [Entanglement.md](./Entanglement.md) — knowledge vs news classification corresponds to universal/particular channels.
- [Training.md](./Training.md) — feelings excluded from training; fact classification affects persistence.
