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
- **non(a)** = 1 − 2|a| — non-affirming negation. Measures epistemic openness: how much certainty room remains. Full certainty in either direction (±1) yields −1 (fully closed); ignorance (0) yields +1 (fully open). See `doc/non.md` for the Buddhist philosophical motivation.

These operators compose freely — for instance, material implication (A → B) falls out as `or(not(A), B)`.

The key insight behind `non`: Kleene logic cannot detect uncertainty; it can only transmit it. `non` introduces uncertainty as a first-class observable. If WikiOracle needs to reason about openness rather than merely propagate it, then `non` is not ornamental — it is structurally necessary. See [`doc/non.md`](non.md) for the proof and the Buddhist philosophical motivation.

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
| `html/util.js` | Trust editor UI: unified XHTML textarea with template dropdown (AND/OR/NOT/NON), IDs visible for `<child id>` references |
| `spec/hme.jsonl` | Test data with AND, OR, NOT, NON operator entries |
| `test/test_derived_truth.py` | Unit tests covering parsing, ID generation, and/or/not/non evaluation, chaining, cycles, and hme.jsonl integration |
