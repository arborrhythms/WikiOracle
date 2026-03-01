# Non: non-affirming negation

WikiOracle has two negation operators with distinct epistemic roles:

| Operator | Formula | Effect |
|----------|---------|--------|
| `not(a)` | −a | Flips belief to disbelief (and vice versa). Affirming negation. |
| `non(a)` | 1 − 2\|a\| | Measures epistemic openness on [-1, +1]. Non-affirming negation. |

`not` is straightforward: if you believe a claim at +0.9, `not` yields −0.9 — you now disbelieve it with equal strength. This is *affirming* negation: it asserts the contrary.

`non` does something fundamentally different. It erases the sign — the direction of commitment — and returns a value on the same [-1, +1] scale that measures how open or closed the epistemic state is:

| Input a | \|a\| | non(a) = 1 − 2\|a\| | Reading |
|---------|-------|----------------------|---------|
| ±1.0 | 1.0 | −1.0 | Full certainty → fully closed |
| ±0.9 | 0.9 | −0.8 | Strong certainty → strongly closed |
| ±0.7 | 0.7 | −0.4 | |
| ±0.5 | 0.5 | 0.0 | Moderate certainty → neither open nor closed |
| ±0.3 | 0.3 | 0.4 | |
| ±0.1 | 0.1 | 0.8 | Weak certainty → strongly open |
| 0.0 | 0.0 | 1.0 | Ignorance → fully open |

Three properties stand out:

1. **Symmetry**: non(+a) = non(−a). Belief and disbelief of equal strength produce the same openness.
2. **non(0) = +1**: Ignorance is maximum openness.
3. **non(±1) = −1**: Full certainty is fully closed.

The ±0.5 boundary is where `non` crosses zero: certainty below half-strength reads as open, above half-strength reads as closed.

The formula is the standard affine rescaling of the fuzzy complement: `1 − |a|` maps certainty strength to openness on [0, 1]; the rescaling `2x − 1` maps that onto [-1, +1], making `non` composable with the other operators.

---

## Precedent in Buddhist logic

Indian and Tibetan Buddhist philosophers identified two forms of negation:

- **Paryudasa-pratisedha** (affirming negation) — negates a predicate while implying a positive alternative. "The pot is not blue" implies it is some other color. This maps to `not`.

- **Prasajya-pratisedha** (non-affirming negation) — simply removes an attribution without positing anything in its place. "Phenomena lack inherent existence" does not assert they have some other kind of existence. This maps to `non`.

The distinction is central to Madhyamaka philosophy. When Nagarjuna argues that phenomena are "empty" (shunya), he intends prasajya — the removal of a false attribution, not the assertion of a new property called "emptiness." Emptiness itself is empty. The negation is supposed to leave nothing behind for the mind to grasp.

Chandrakirti and later commentators insisted that this kind of negation resists formalization: any definition of "a negation that posits nothing" risks becoming a positive assertion in its own right. Tsongkhapa's attempt — "a negation whose negandum is removed without anything posited in its place" — drew criticism from Gorampa precisely on these grounds: the definition itself seems to affirm something about what remains. The act of saying "nothing is posited" posits something. Buddhist logicians spent centuries circling this recursion without landing on a formulation that satisfied all parties.

---

## Why 1 − 2|a| is the right formula

**1. Symmetry of extremes.** non(+0.9) = non(−0.9) = −0.8. Strong belief and strong disbelief are treated identically. This maps precisely to the Madhyamaka rejection of both eternalism (strong positive assertion) and nihilism (strong negative assertion) as extreme views. Both are certainties; prasajya treats them the same.

**2. Ignorance yields maximum openness.** non(0) = +1. The non-affirming negation of "I don't know" is maximum openness. This resonates with the Madhyamaka teaching that not-knowing, when held correctly, is not a deficit but a clearing. The old formula mapped 0 → 0, treating ignorance as inert.

---

## Fuzzy logic interpretation

In standard fuzzy logic on [0, 1], the complement of a membership value a is 1 − a. WikiOracle's certainty scale [-1, +1] encodes both direction (sign) and strength (magnitude). The operation `1 − 2|a|` applies the standard fuzzy complement to the *strength* of certainty (via `1 − |a|`), then rescales back to [-1, +1] (via `2x − 1`). This is the natural fuzzy-logical reading of "negate the commitment without asserting the opposite":

- Fuzzy affirming negation (`not`): negate the *value* — flip the sign, preserve the magnitude. You get the complementary claim.
- Fuzzy non-affirming negation (`non`): negate the *strength* — take the fuzzy complement of |a|, rescaled to the certainty range. You get a measure of openness, not a complementary claim.

---

## Relation to the Madhyamaka problem

WikiOracle's `non` does not solve Chandrakirti's problem. It translates it.

Prasajya-pratisedha is supposed to be a negation that posits nothing — not even a measurement, not even a degree. `non(a) = 1 − 2|a|` models *degree of epistemic openness*. That is a formal quantity, not a metaphysical void. The formula avoids the recursion that plagued Buddhist logicians because it is extensional — defined by what it computes, not by what it means to negate without affirming. But this is a change of domain, not a resolution. The philosophical question of whether a truly positionless negation can be formalized remains open. What WikiOracle provides is a metric translation that preserves the key structural features (sign erasure, symmetry of extremes, openness of ignorance) while operating in a domain where those features can be computed and composed.

---

## Expressive necessity: why {and, or, not} is incomplete without non

This section shows that `non` is not merely a philosophical ornament. It is *necessary* for the logic to express certain functions, and *sufficient* (together with {and, or, not}) to express a large and natural class.

### The regularity barrier

In Strong Kleene logic, the operators {and, or, not} have a structural constraint: they are all **regular** (also called **normal**). A function f is regular if, when every input is set to the middle value U (certainty = 0), the output is also U.

Check:
- and(0, 0) = min(0, 0) = 0 ✓
- or(0, 0) = max(0, 0) = 0 ✓
- not(0) = −0 = 0 ✓

Composition preserves regularity: if f and g are regular, so is f ∘ g. Therefore *every* function expressible from {and, or, not} is regular.

But non(0) = +1 ≠ 0. So `non` is **not** regular.

**Theorem.** `non` cannot be expressed using {and, or, not} alone.

*Proof.* Every function in the clone generated by {and, or, not} is regular. `non` is not regular. ∎

This is the formal analogue of a structural distinction that Buddhist logicians identified but could not formalize in their own terms.

### What non adds: the detection functions

In discrete ternary logic ({T, U, F} = {+1, 0, −1}), `non` acts as a **detector for uncertainty**:

- non(T) = non(+1) = −1 = F
- non(U) = non(0) = +1 = T
- non(F) = non(−1) = −1 = F

That is: non(x) = T if and only if x = U. This is the detection function **J_U**.

From J_U and the existing operators, we can construct the other two detectors:

- **J_T(x)** = and(x, not(non(x))): detects whether x = T.
  - x=T: and(T, not(F)) = and(T, T) = T ✓
  - x=U: and(U, not(T)) = and(U, F) = F ✓
  - x=F: and(F, not(F)) = and(F, T) = F ✓

- **J_F(x)** = and(not(x), not(non(x))): detects whether x = F.
  - x=T: and(F, not(F)) = and(F, T) = F ✓
  - x=U: and(U, not(T)) = and(U, F) = F ✓
  - x=F: and(T, not(F)) = and(T, T) = T ✓

With J_T, J_U, and J_F available, we can build **case expressions**: "if x = T then A, if x = U then B, if x = F then C" for any constants A, C ∈ {T, F}:

    or(and(J_T(x), A), or(and(J_U(x), B), and(J_F(x), C)))

### The completeness result

**Theorem.** {and, or, not, non} can express every function f: {T, U, F}^n → {T, F}.

*Proof sketch.* Given any f whose output is always definite (T or F), express it as a disjunction over all input tuples where f returns T. Each such tuple can be detected using J_T, J_U, J_F on individual variables, combined with `and`. The disjunction of these detections yields f. ∎

The one thing {and, or, not, non} *cannot* produce is U as output from definite inputs — because all four operators, given inputs in {T, F}, produce outputs in {T, F}. This is arguably correct: U represents genuine uncertainty, and should not be manufactured from certain data.

---

## What this actually is

The four operators constitute a two-axis epistemic algebra:

- **Axis 1: belief polarity** — handled by `not`. Flips the sign; preserves magnitude. Operates on the direction of commitment.
- **Axis 2: commitment strength** — handled by `non`. Erases the sign; inverts magnitude. Operates on how strongly anything is held, regardless of direction.

`and` and `or` combine values along both axes simultaneously (min and max over signed certainty). `not` and `non` decompose the axes: one rotates direction, the other measures grip.

The formal results above establish three things:

1. `non` is not derivable from the classical ternary operators {and, or, not}. It breaks the regularity barrier.
2. Adding `non` yields bivalent functional completeness: {and, or, not, non} can express every function f: {T, U, F}^n → {T, F}.
3. `non` enables *detection* of uncertainty rather than mere propagation. Without it, Kleene logic can pass uncertainty through but can never see it.

This is a genuine structural enrichment of Strong Kleene logic.
