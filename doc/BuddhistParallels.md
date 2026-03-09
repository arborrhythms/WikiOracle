# Buddhist Parallels

## Purpose

WikiOracle's truth ontology closely parallels the epistemological framework
of Buddhist **pramāṇa theory**, particularly as developed by Dignāga, Dharmakīrti,
and — for the tetralemma — Nāgārjuna.

Pramāṇa theory asks a simple question:

> How does a *valid cognizer* obtain reliable knowledge?

WikiOracle formalizes the same process computationally through a set of
structured truth objects.

This document maps WikiOracle's ontology to the **sources of valid cognition**
recognized in Buddhist logic and explains how the **tetralemma** can be
interpreted using **Kleene logic** and **non-affirming negation**.

## Valid Cognition in Dharmakīrti

In Dharmakīrti's system there are **two primary pramāṇas**:

| Source of Cognition | Sanskrit | Meaning |
|---|---|---|
| Direct perception | *pratyakṣa* | immediate, non-conceptual awareness of unique particulars (*svalakṣaṇa*) |
| Inference | *anumāna* | conceptual reasoning operating on universals (*sāmānyalakṣaṇa*) |

Dharmakīrti identifies **four subtypes of pratyakṣa**: sensory perception (*indriya*), mental perception (*mānasa*), self-awareness (*svasaṃvedana*), and yogic perception (*yogijñāna*).

Other knowledge sources — including testimony (*śabda*) — are considered **derivative**. Dharmakīrti reduces all testimonial knowledge to a form of inference: one *infers* the truth of a claim from the reliability of the speaker (*āpta*, "trustworthy person"). This is not a separate pramāṇa but a special case of *anumāna*.

A valid cognition produces **true conceptual knowledge** (*pramā*).

In WikiOracle, the two pramāṇas map cleanly:

* **pratyakṣa** → Feeling (direct, pre-conceptual, *svasaṃvedana*)
* **anumāna** → Fact and Operator (conceptual, propositional)

Testimony is not a separate source — it is inference from trust, which is exactly how WikiOracle treats Indirect Truth.

## Mapping to WikiOracle Truth Objects

WikiOracle expresses the same epistemic structure through six truth types, organized into Direct Truth (what we know directly) and Indirect Truth (what we know only through external sources).

### Direct Truth

| WikiOracle Type | Epistemic Role | Buddhist Equivalent | Sanskrit |
|---|---|---|---|
| **Feeling** | immediate hedonic tone; ±1 = *vedanā* (pleasant/unpleasant) | direct perception — self-awareness | *pratyakṣa* / *svasaṃvedana* |
| **Fact** | conceptual proposition with truth value in [-1, +1] | inference — conceptual cognition | *anumāna* / *kalpanā* |
| **Operator** | logical transformation (and/or/not/non) deriving new truth | logical pervasion — formal reasoning | *vyāpti* / *prayoga* |

Feelings are *pratyakṣa* because they are pre-conceptual, non-linguistic, and immediate — the raw experiential signal before conceptual elaboration. Dharmakīrti is explicit: pratyakṣa apprehends unique particulars (*svalakṣaṇa*) and is non-conceptual (*nirvikalpaka*). The moment something is formulated as a proposition with a truth value, it is conceptual and falls under *anumāna*.

### Indirect Truth

| WikiOracle Type | Epistemic Role | Buddhist Equivalent | Sanskrit |
|---|---|---|---|
| **Reference** | citation grounding a claim in a verifiable source | scripture / textual source | *āgama* |
| **Provider** | another cognizer supplying claims and truth | trustworthy person / valid cognizer | *āpta* / *pramāṇa-puruṣa* |
| **Authority** | reference to another body of conversations and truths | trustworthy testimony | *āpta-vacana* |

Dharmakīrti argues that testimonial knowledge involves three components: the *text* itself (*āgama* — Reference), the *person* who produced it (*āpta* — Provider), and the *inferential warrant* for trusting that person's testimony (*āpta-vacana* — Authority). All three reduce to inference from the reliability of the source.

### The Epistemic Pipeline

These correspond to the full epistemic pipeline:

```
feeling (direct perception) → fact (conceptual judgment) → operator → new fact
```

Authorities influence **which providers are trusted**, but logical validity
is determined only by operators and evidence.

## Frame-Relative Truth

WikiOracle evaluates facts relative to **epistemic frames** defined by
authorities and priors.

A fact therefore has the structure:

```
fact = (proposition, frame, truth_value)
```

Different frames may legitimately assign different truth values.

Example:

| Frame | Earth age |
|---|---|
| Biblical literalist | ~6000 years |
| Geological science | ~4.5 billion years |

Both may be recorded simultaneously without contradiction because
truth is **frame-indexed**.

## Tetralemma Interpretation

Buddhist logic frequently uses the **catuṣkoṭi (tetralemma)**, as articulated by Nāgārjuna in the *Mūlamadhyamakakārikā*:

| Classical Form | Sanskrit | WikiOracle Interpretation | Truth Type |
|---|---|---|---|
| True | *asti* | affirmed | `<fact trust="+1">` |
| False | *nāsti* | negated | `<fact trust="-1">` |
| Both | *ubhaya* | indeterminate — neither affirmed nor negated | `<fact trust="0">` |
| Neither | *anubhaya* / *avaktavya* | outside the truth lattice entirely; inexpressible | `<feeling>` |

The "both" (*ubhaya*) position represents the indeterminate case: within a single frame, the proposition is neither established as true nor as false. Across multiple frames, the same value represents genuine frame disagreement.

The "neither" (*anubhaya*) position is what Nāgārjuna uses to indicate that a proposition falls outside the domain of truth-evaluation entirely. Feelings occupy this position: they are experiential, not propositional.

## Kleene Logic and Epistemic States

Within a single frame, WikiOracle uses a three-valued epistemic logic
similar to **Kleene logic**:

| Value | Meaning | Tetralemma |
|---|---|---|
| +1 (True) | affirmed conceptual cognition | True (*asti*) |
| -1 (False) | negated conceptual cognition | False (*nāsti*) |
| 0 (Both) | indeterminate — insufficient to affirm or negate | Both (*ubhaya*) |

The fourth tetralemma state — Neither — is occupied by Feelings, which are not truth-evaluable propositions and therefore fall outside the Kleene lattice entirely.

When multiple frames are considered simultaneously,
the "both" state emerges naturally as frame disagreement.

## Negation and Logical Operators

Buddhist logic distinguishes two types of negation:

| Type | Sanskrit | Meaning |
|---|---|---|
| Affirming negation | *paryudāsa* | negation implying an alternative predicate |
| Non-affirming negation | *prasajya-pratiṣedha* | pure removal of a predicate |

WikiOracle's logical operators map to Dharmakīrti's theory of inference:

| WikiOracle Operator | Buddhist Equivalent | Sanskrit |
|---|---|---|
| `<not>` | affirming negation — implies the opposite | *paryudāsa* |
| `<non>` | non-affirming negation — pure removal | *prasajya-pratiṣedha* |
| `<and>` | positive concomitance — co-presence | *anvaya* |
| `<or>` | negative concomitance — co-absence | *vyatireka* |

All operators are instances of **logical pervasion** (*vyāpti*) — the necessary connection between reason and conclusion that grounds valid inference.

The `non()` operator is of particular interest. It removes commitment to a proposition without asserting its opposite:

```
non(a)
```

interprets as:

> the conceptual commitment to *a* is removed.

This produces **epistemic openness** rather than contradiction. Dharmakīrti holds that valid cognition stabilizes reliable conceptual constructions while invalid cognition is removed through non-affirming negation. In WikiOracle this dynamic can be interpreted computationally: true cognitions deepen stable conceptual attractors, while false cognitions weaken them, producing a truth-weighted energy landscape similar to a Hopfield memory system.

## Truth Lattice

Combining frames and epistemic states yields the following structure:

| State | Interpretation | Examples |
|---|---|---|
| True (*asti*) | affirmed in frame | `<fact trust="+1">` |
| False (*nāsti*) | rejected in frame | `<fact trust="-1">` |
| Both (*ubhaya*) | indeterminate or disagreement across frames | `<fact trust="0">` / frame-indexed contradiction |
| Neither (*anubhaya*) | outside the truth lattice; not truth-evaluable | `<feeling>` — excluded from training |

## Feelings, Vedanā, and the "Neither" Position

Feelings occupy the *neither* position in the tetralemma. They are not truth-evaluable propositions — they are **direct perception** (*pratyakṣa*), specifically **self-awareness** (*svasaṃvedana*): the reflexive, unmediated presence of experiential content to the cognizing mind.

The ±1 values of a Feeling correspond to **vedanā** (hedonic tone):

* **+1**: *sukha-vedanā* — pleasant feeling
* **-1**: *duḥkha-vedanā* — unpleasant feeling

Vedanā arises from contact (*sparśa*) — the meeting of sense organ, sense object, and consciousness. It is pre-conceptual and non-linguistic: the raw signal before conceptual elaboration occurs.

Facts, by contrast, are *anumāna* (inference) — conceptual judgments expressed as propositions. Dharmakīrti is explicit: the moment something is formulated as a proposition with a truth value, it is conceptual and therefore falls under inference, not perception.

In WikiOracle:

* Feelings are **excluded from model training** — they do not update NanoChat weights.
* Feelings are **excluded from TruthSets** — they carry no epistemic weight.
* Poetry, greetings, hedged claims, and subjective expressions are canonical examples.

This preserves the tetralemma without logical explosion.

## Summary

WikiOracle's ontology forms a computational analogue of Buddhist epistemology.

| WikiOracle | Category | Buddhist Epistemology | Sanskrit |
|---|---|---|---|
| Feeling | Direct Truth | direct perception / self-awareness / hedonic tone | *pratyakṣa* / *svasaṃvedana* / *vedanā* |
| Fact | Direct Truth | inference / conceptual cognition | *anumāna* / *kalpanā* |
| Operator | Direct Truth | logical pervasion / formal reasoning | *vyāpti* / *prayoga* |
| Reference | Indirect Truth | scripture / textual source | *āgama* |
| Provider | Indirect Truth | trustworthy person / valid cognizer | *āpta* / *pramāṇa-puruṣa* |
| Authority | Indirect Truth | trustworthy testimony | *āpta-vacana* |

The system therefore models **conventional truth dynamics** in a way
consistent with the logical structure described by Dharmakīrti and
the tetralemma as articulated by Nāgārjuna.

Plural frames coexist, inference operates within frames,
feelings provide the perceptual ground from which concepts arise,
and non-affirming negation preserves epistemic openness.
