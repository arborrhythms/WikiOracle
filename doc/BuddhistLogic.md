
# BuddhistLogic.md

## Purpose

WikiOracle’s truth ontology closely parallels the epistemological framework
of Buddhist **pramāṇa theory**, particularly as developed by Dignāga and Dharmakīrti.

Pramāṇa theory asks a simple question:

> How does a *valid cognizer* obtain reliable knowledge?

WikiOracle formalizes the same process computationally through a set of
structured truth objects.

This document maps WikiOracle’s ontology to the **sources of valid cognition**
recognized in Buddhist logic and explains how the **tetralemma** can be
interpreted using **Kleene logic** and **non-affirming negation**.

---

# Valid Cognition in Dharmakīrti

In Dharmakīrti’s system there are **two primary pramāṇas**:

| Source of Cognition | Sanskrit | Meaning |
|---|---|---|
| Direct perception | pratyakṣa | immediate, non-conceptual awareness |
| Inference | anumāna | conceptual reasoning from signs |

Other knowledge sources (including testimony) are considered **derivative**
because they ultimately depend on perception and inference.

A valid cognition produces **true conceptual knowledge** (*pramā*).

---

# Mapping to WikiOracle Truth Objects

WikiOracle expresses the same epistemic structure through five truth types.

| WikiOracle Type | Epistemic Role | Buddhist Equivalent |
|---|---|---|
| **Feeling** | immediate experiential signal; orthogonal to truth (neither position in tetralemma) | perception (*pratyakṣa*) — pre-conceptual |
| **Fact (knowledge)** | universal/inferential cognition | inference (*anumāna*) — conceptual judgment |
| **Fact (news)** | spatiotemporally bound observation | direct perception (*pratyakṣa*) — session-only |
| **Operator** | logical transformation between concepts | inference (*anumāna*) |
| **Authority** | trusted testimony from another knower | testimony (*āgama / śabda*) |
| **Provider** | the cognizer supplying the claim | cognizer (*pramātṛ*) |

These correspond to the full epistemic pipeline:

provider → feeling → fact → operator → new fact

Authorities influence **which providers are trusted**, but logical validity
is determined only by operators and evidence.

---

# Frame-Relative Truth

WikiOracle evaluates facts relative to **epistemic frames** defined by
authorities and priors.

A fact therefore has the structure:

fact = (proposition, frame, truth_value)

Different frames may legitimately assign different truth values.

Example:

| Frame | Earth age |
|---|---|
| Biblical literalist | ~6000 years |
| Geological science | ~4.5 billion years |

Both may be recorded simultaneously without contradiction because
truth is **frame-indexed**.

---

# Tetralemma Interpretation

Buddhist logic frequently uses the **catuṣkoṭi (tetralemma)**:

| Classical Form | WikiOracle Interpretation | Truth Type |
|---|---|---|
| True | affirmed in a frame | `<fact trust="+1">` |
| False | negated in a frame | `<fact trust="-1">` |
| Both | true in some frames and false in others | frame disagreement |
| Neither | outside the truth lattice entirely | `<feeling>` |

The “both” case represents **frame disagreement**, not logical contradiction.

---

# Kleene Logic and Epistemic States

Within a single frame WikiOracle uses a three-valued epistemic logic
similar to **Kleene logic**.

| Value | Meaning |
|---|---|
| True | supported conceptual cognition |
| False | rejected conceptual cognition |
| Unknown | insufficient knowledge |

When multiple frames are considered simultaneously,
the fourth tetralemma state (“both”) emerges naturally.

---

# Non-Affirming Negation

Buddhist logic distinguishes two types of negation:

| Type | Sanskrit | Meaning |
|---|---|---|
| Affirming negation | paryudāsa | negation implying an alternative predicate |
| Non-affirming negation | prasajyapratiṣedha | pure removal of a predicate |

WikiOracle’s **non() operator** models non-affirming negation.

It removes commitment to a proposition without asserting its opposite.

Example:

non(a)

interprets as:

> the conceptual commitment to *a* is removed.

This produces **epistemic openness** rather than contradiction. Dharmakīrti holds that valid cognition stabilizes reliable conceptual constructions while invalid cognition is removed through non-affirming negation. In WikiOracle this dynamic can be interpreted computationally: true cognitions deepen stable conceptual attractors, while false cognitions weaken them, producing a truth-weighted energy landscape similar to a Hopfield memory system.

---

# Truth Lattice

Combining frames and epistemic states yields the following structure:

| State | Interpretation | Examples |
|---|---|---|
| True | affirmed in frame | `<fact trust="+1">` |
| False | rejected in frame | `<fact trust="-1">` |
| Neither | outside the truth lattice; not truth-evaluable | `<feeling>` — excluded from training |
| Both | disagreement across frames | frame-indexed contradiction |

### Feelings and the "Neither" Position

Feelings occupy the *neither* position in the tetralemma. They are not
truth-evaluable propositions — they are pre-conceptual experiential signals
(e.g., "That's a great question!", "I hope that helps."). In WikiOracle:

- Feelings carry **no trust attribute** — they are orthogonal to the truth lattice.
- Feelings are **excluded from model training** — they do not update NanoChat weights.
- Feelings are **excluded from server persistence** — only knowledge facts are stored.
- Poetry, greetings, and subjective expressions are canonical examples.

This preserves the tetralemma without logical explosion.

---

# Summary

WikiOracle’s ontology forms a computational analogue of Buddhist epistemology.

| WikiOracle | Buddhist Epistemology |
|---|---|
| Feeling | perception (pre-conceptual; neither in tetralemma) |
| Fact (knowledge) | inferential cognition (*anumāna*) |
| Fact (news) | direct perception (*pratyakṣa*) — spatiotemporally bound |
| Operator | inference |
| Authority | testimony |
| Provider | cognizer |

The system therefore models **conventional truth dynamics** in a way
consistent with the logical structure described by Dharmakīrti.

Plural frames coexist, inference operates within frames,
and non-affirming negation preserves epistemic openness.

---

## See also

- [Non.md](./Non.md) — full formal treatment of non-affirming negation (prasajya-pratisedha).
- [Logic.md](./Logic.md) — Kleene operators and operator evaluation under Strong Kleene semantics.
- [WhatIsTruth.md](./WhatIsTruth.md) — knowledge/news distinction using anumāna/pratyakṣa.
- [Entanglement.md](./Entanglement.md) — universal/particular channels map to inferential/perceptual truth.
- [Authority.md](./Authority.md) — authorities as testimony (āgama/śabda).
- [HierarchicalMixtureOfExperts.md](./HierarchicalMixtureOfExperts.md) — providers/authorities/operators in the epistemic pipeline.
