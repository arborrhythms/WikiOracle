# Implication
## Three implications for WikiOracle’s truth system

WikiOracle wants to talk about “if…then…” in at least three distinct ways, because **truth-functional**, **necessary**, and **relevance-constrained** conditionals behave differently under uncertainty, provenance, and “minority-truth” coexistence.

Below are three major implication notions you can treat as separate operators in the WikiOracle truth layer.

Wikipedia links (core):
- [Implication (overview)](https://en.wikipedia.org/wiki/Implication)
- [Material conditional](https://en.wikipedia.org/wiki/Material_conditional)
- [Strict conditional](https://en.wikipedia.org/wiki/Strict_conditional)
- [Relevance logic](https://en.wikipedia.org/wiki/Relevance_logic)
- [Three-valued logic (Kleene)](https://en.wikipedia.org/wiki/Three-valued_logic)

---

## 1) Material implication (truth-functional):  A →ₘ B

### What it is
The classical “material conditional” treats `A → B` as equivalent to `¬A ∨ B`, i.e. it is **false only when A is true and B is false**, and otherwise true.

### Why WikiOracle needs it
This is the workhorse for **purely formal derivations** where you’re modeling *constraint satisfaction inside a chosen calculus* (e.g., “given these axioms, this theorem follows”). It’s cheap to compute and composes well.

### The catch (important for truth governance)
Material implication generates the “paradoxes of material implication” (e.g., a false antecedent makes the conditional true), which is often *not* what users mean by “because” or “therefore.”

### Kleene / ternary connection (Strong Kleene)
If WikiOracle tracks a ternary value set like **T / F / U(unknown/undefined)**, you can lift material implication in the standard Strong Kleene way:

- Define: `A →ₘ B := ¬A ∨ B` (same shape as classical)
- Strong Kleene truth table for implication (from the Kleene section):

| A \ B | F | U | T |
|---|---:|---:|---:|
| **F** | T | T | T |
| **U** | U | U | T |
| **T** | F | U | T |

Interpretation for WikiOracle:
- If the antecedent is **unknown**, implication is often **unknown** unless the consequent is already **true**.
- This matches a “don’t hallucinate entailment from missing premises” posture.

---

## 2) Strict implication (modal / necessity-loaded):  A →ₛ B

### What it is
Strict implication is typically modeled as **necessitating** the material conditional:
- `A →ₛ B` can be represented as `□(A →ₘ B)` (read: “necessarily, if A then B”).

This is what you reach for when you mean:
- “In *all admissible worlds/models consistent with the background theory*, A entails B.”

### Why WikiOracle needs it
WikiOracle can treat “strict” conditionals as **invariants under a declared theory or scope**, e.g.:
- Physics/engineering constraints under a specified model class.
- “Policy constraints” (deontic/epistemic modalities) where you want “must/ought/known” operators.

### How it fits a truth+trust system
Strict implication gives you a clean way to separate:
- **Local assertions** (source-anchored, defeasible)
from
- **Scope-necessary constraints** (theory-anchored, globally enforced *within* a declared frame)

In WikiOracle terms: strict implication is a good fit for **“within TrustSet S + Theory T, this conditional is forced.”**

### Ternary / Kleene connection
You can keep Kleene truth values at the *base* level, but evaluate `□(...)` over:
- a set of “accessible worlds” (models) as in Kripke semantics, or
- a set of “admissible contexts” (TrustSets / policy frames).

Operationally:
- `A →ₛ B` is **T** if every admissible context makes `A →ₘ B` designated true.
- It is **F** if some admissible context makes it non-designated (or explicitly false).
- It is **U** when admissibility itself is underspecified (common in real knowledge systems).

---

## 3) Relevant implication (relevance / anti-paradox):  A →ᵣ B

### What it is
Relevance logics were developed to block “irrelevant” implications (including many paradoxes of material and strict implication) by requiring a stronger connection between antecedent and consequent.

A motivating complaint is exactly the WikiOracle problem:
- “If (some unrelated falsehood), then (any statement)” shouldn’t become “true” just because the antecedent is false.

### Why WikiOracle needs it
WikiOracle isn’t only proving theorems; it’s mediating **explanations** and **justifications** across contested sources. Relevant implication supports:
- “Show me why B follows from A” where *why* means “shares content, terms, mechanisms, or evidence pathways.”
- Causal and mechanistic narratives where vacuous truths are actively harmful.

### How to operationalize relevance in WikiOracle (pragmatic version)
Full relevance logic semantics can be heavy, but you can implement a **relevance gate** in the truth layer:

Define `A →ᵣ B` as “`A →ₘ B` is designated true **AND** `Rel(A,B)` holds,” where `Rel(A,B)` is a computable predicate such as:
- shared entities/relations in the claim graphs,
- shared citations or overlapping evidence sets,
- nontrivial mutual information in embeddings,
- explicit “depends-on” edges in provenance.

This turns implication into a *two-channel* object:
1) truth-functional entailment (possibly ternary, Kleene-style), plus
2) relevance/provenance adequacy.

### Ternary / Kleene connection
In a ternary truth layer, relevance becomes even more useful:
- Many claims sit at **U** because evidence is incomplete.
- Relevant implication can demand that *whatever supports “A”* must also be in the dependency chain for “B,” preventing “U”-to-“T” jumps that look like “magic.”

---

## Putting all three into a WikiOracle truth API

Treat implication as a **typed operator** rather than a single symbol:

- `implies.material(A,B)` : computes ternary truth via Strong Kleene `¬A ∨ B`.
- `implies.strict(A,B, scope)` : evaluates `□(A →ₘ B)` over admissible contexts/worlds for `scope`.
- `implies.relevant(A,B, policy)` : requires both entailment + a relevance predicate (graph/provenance-based).

Practical payoff:
- **Material** for math-like derivations.
- **Strict** for “under this theory/policy frame, necessarily…”
- **Relevant** for human-facing “because/therefore” explanations where provenance and conceptual linkage matter.

---

## Extra Wikipedia links you’ll likely want nearby
- [Paradoxes of material implication](https://en.wikipedia.org/wiki/Paradoxes_of_material_implication)
- [Modal logic](https://en.wikipedia.org/wiki/Modal_logic)
- [Relevance](https://en.wikipedia.org/wiki/Relevance)

---

## Implementation notes

### Storage format

Implication entries are trust entries whose `content` field contains an `<implication>` XML block:

```json
{
  "type": "trust",
  "id": "i_syllogism_01",
  "title": "Men are mortal → Socrates is mortal",
  "certainty": 0.0,
  "content": "<implication><antecedent>t_axiom_02</antecedent><consequent>t_derived_01</consequent><type>material</type></implication>",
  "time": "2026-02-25T00:00:01Z"
}
```

Fields inside `<implication>`:
- `<antecedent>` — trust entry ID (the "if" part)
- `<consequent>` — trust entry ID (the "then" part)
- `<type>` — one of: `material`, `strict`, `relevant` (default: `material`; only `material` is currently evaluated)

The `i_` ID prefix distinguishes implication entries from trust (`t_`), message (`m_`), and conversation (`c_`) IDs.

### Derived truth engine

`compute_derived_truth()` in `bin/truth.py` evaluates all implication entries using fixed-point iteration:

1. Build a certainty lookup `{ id: certainty }` from all trust entries
2. Extract implications via `parse_implication_block()`
3. Iterate (max 100 rounds):
   - For each implication with antecedent certainty > 0: set `consequent = max(consequent, antecedent)`
   - If no values changed, stop (fixed point reached)
4. Return the complete derived certainty table

This implements modus ponens: if the antecedent is believed, the consequent is raised to at least the antecedent's certainty. Implications can only strengthen belief, never weaken it. Disbelieved antecedents (certainty ≤ 0) are vacuously true and do not propagate.

### Known limitation: material implication paradox

The `i_soft_fly_01` entry in `spec/hme.jsonl` demonstrates the paradox of material implication: the chain `t_axiom_05` (Penguins are birds, c=1.0) → `t_soft_01` (Most birds can fly) → `t_false_01` (Penguins can fly) raises the disbelieved consequent to 1.0, overriding the -0.9 stored certainty. This is a known property of material implication and motivates the planned implementation of relevant implication (`→ᵣ`), which would require a relevance predicate to prevent such vacuous entailments.

### Integration points

| File | Function |
|---|---|
| `bin/truth.py` | `parse_implication_block()`, `ensure_implication_id()`, `compute_derived_truth()` |
| `bin/prompt_bundle.py` | Excludes `<implication>` entries from RAG; uses `_derived_certainty` for ranking |
| `bin/response.py` | Calls `compute_derived_truth()` after provider responses; stores transient `_derived_certainty` |
| `html/wikioracle.js` | Trust editor UI: "Add Implication" button, antecedent/consequent dropdowns, derived certainty display |
| `spec/hme.jsonl` | Test data with syllogism, chain, and paradox implication entries |
| `tests/test_derived_truth.py` | 16 unit tests covering parsing, ID generation, modus ponens, chains, cycles, and hme.jsonl integration |
