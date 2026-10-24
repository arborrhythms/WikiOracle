# Ethics

**Ethical AI through Truth Architecture in WikiOracle**

## Truth Symmetry

Statements involving value judgements are checked for asymmetric harm
under identity exchange before admission to the TruthSet. If a claim
becomes unethical when identity references are swapped, it should not be
admitted as a universal truth.

Example:

> "Group X deserves harm."

Symmetry test: swap identities. If the claim collapses or becomes
contradictory, it reveals an ethical inconsistency -- the claim is
asymmetric and should not be admitted as fact. The system offers to
record the statement as a feeling instead, preserving the user's
expression without endorsing the claim as truth.

This is controlled by the `truth_symmetry` config option (default: true).
See [Config.md](./Config.md) Section 5a and the implementation in
`bin/truth.py` (`detect_asymmetric_claim()`).

## Architectural ethics vs policy ethics

Most AI systems attempt to enforce ethics **after generation**:

    model → output → moderation filter

This approach fails because:

-   ethics is external to reasoning
-   the model itself does not understand ethical constraints
-   moderation becomes inconsistent or bypassable

WikiOracle instead aims for **architectural ethics**, where unethical
reasoning becomes structurally inconsistent with the knowledge system.
The approach combines:

-   Local Freedom under Global Constraint (LFGC)
-   Entanglement-resistant data policy
-   Explicit truth values and inspectable reasoning
-   Symmetry constraints on truth admission

Together these mechanisms create a knowledge system capable of
preserving **personal sovereignty** while still allowing collective
knowledge to accumulate.

## Symmetry as a foundation of ethical reasoning

Ethical failures often correspond to **asymmetries in truth claims**.

Examples:

| Ethical failure  | Epistemic distortion |
| ---------------- | -------------------- |
| propaganda       | false belief         |
| discrimination   | asymmetric reasoning |
| authoritarianism | opaque claims        |
| scapegoating     | category errors      |

A truth system that enforces symmetry naturally resists these
distortions.

Ethical intelligence may emerge from the balance:

    freedom + constraint

This mirrors both:

-   [LFGC](https://zenodo.org/records/18644302) physics concepts
-   philosophical traditions linking wisdom and compassion

The system does not force ethical behavior, but unethical reasoning
becomes unstable within the truth architecture.


## Reciprocity symmetry

A truth claim should remain valid under **perspective exchange**.

Example principle:

> If A may assert X about B, B must be able to assert X about A under
> equivalent conditions.

This prevents:

-   identity privilege
-   asymmetric harm claims
-   discriminatory reasoning

This symmetry echoes philosophical traditions such as Kant's
universalization principle and Rawls' veil of ignorance.

## Reversibility symmetry

Accepted conclusions must be **inspectable and reversible**.

Opaque reasoning creates hidden authority.

WikiOracle counters this by requiring:

-   explicit truth values
-   inspectable reasoning chains
-   transparent authority imports

## Harm symmetry

A claim permitting harm should remain valid when applied symmetrically.

This is the core of the Truth Symmetry enforcement described above.
If swapping identity references makes a claim contradictory or
indefensible, it reveals an ethical inconsistency that the system flags.

## Universality (Golden Rule) -- architectural enforcement

The symmetry tests described above operate at truth admission time.
Universality operates during model training, enforcing the Golden Rule
at the level of gradient updates.

When the Grammar recognizes a transitive verb via `lift(C, C, C)`,
the model evaluates **universality**: the change in luminosity when
both the original action (SVO) and its dual (OVS) are applied.

```
universality = luminosity(truths + SVO + OVS) - luminosity(truths)
```

- **Positive**: the action preserves or increases illumination (kind).
  The loss is left unchanged or reduced.
- **Negative**: the action diminishes illumination (unkind).
  The loss is increased, penalizing the proposition.

The loss modification formula (multiplicative):

```
totalLoss = totalLoss * (1 + LuminosityWeight * (1 - luminosity)
                           + UniversalityWeight * (1 - universality))
```

In addition, an **additive** TruthLoss penalty directly penalizes
propositions that contradict stored truths. It measures the union norm
reduction when a proposition is folded into the TruthSet via
`Basis.disjunction()` -- contradicting dimensions cancel, reducing the
norm, which produces a positive penalty. Agreeing or unknown
propositions pass through with no penalty. DoT weighting is implicit:
stored truth vectors carry DoT in their magnitude.

```
totalLoss = totalLoss + TruthLoss * falsity_penalty
```

Together, these make unkind and false propositions harder to learn --
not by filtering output, but by making them structurally costly during
training. Moral axioms (e.g. "causing harm leads to suffering") enter
as regular TruthSet entries; no special API is needed.

See [Config.md](./Config.md) for the `LuminosityWeight`,
`UniversalityWeight`, and `TruthLoss` parameters.
See [Language.md](../basicmodel/doc/Language.md) for the ternary LIFT rule
that identifies subject, verb, and object. See
[Reasoning.md](../basicmodel/doc/Reasoning.md) Section TruthLoss for the full
specification.

## Truth improves ethics

We wish to predict Truth. 
We do not wish to predict Lies.
In fact, we wish to develop an aversion to lies.
Epistemic ignorance is often desireable. 

*All lies are harmful because they undermine the dignity of others. Lies prevent people acting freely and rationally. When someone lies, he interferes with his audience's right to receive information that is correct. Also, lies distort the ability to make informed decisions. Kant goes further and argues that lies cause broader harm by undermining a speaker's credibility, which, in turn, causes people to distrust each other's contentions. Kant even goes as far as to say lying is immoral, under all conditions.*
    ~ Immanuel Kant

Examples:

-   scientific method
-   journalism standards
-   legal evidence systems

As epistemic clarity improves, harmful distortions become harder to
maintain. Thus improving truth infrastructure indirectly improves ethical
reasoning.

## Ethical knowledge geometry

Belief systems can be thought of geometrically.

Ethical systems exhibit properties such as:

-   symmetry
-   continuity
-   coherence
-   minimal harm gradients

Unethical reasoning tends to introduce discontinuities such as:
"this group suddenly loses rights."

Architectures that maintain smooth conceptual geometry resist these
distortions.

## Architectural ethical primitives in WikiOracle

WikiOracle already includes several components that encourage ethical
reasoning:

| Feature                  | Ethical effect              |
| ------------------------ | --------------------------- |
| explicit truth values    | discourages propaganda      |
| multiple POVs            | prevents epistemic monopoly |
| no worldline storage     | protects identity           |
| local-first architecture | preserves autonomy          |
| inspectable reasoning    | prevents hidden authority   |

These mechanisms provide a foundation for ethical AI without relying on
censorship.

## Symmetry operators

The system includes checks for:

-   reciprocity symmetry (perspective exchange)
-   reversibility symmetry (inspectable, contestable conclusions)
-   harm symmetry (identity-swap test via `detect_asymmetric_claim()`)

These checks identify logically inconsistent or discriminatory claims.

## Epistemic humility

The system must allow truth states such as:

-   unknown
-   undetermined

Forcing premature conclusions can distort reasoning and produce
unethical outcomes.

## Distributed governance

Ethical truth systems should not be controlled by a single authority.

Instead they should allow shared constraint setting.

This reduces the risk of epistemic monopolies.

## The identity crisis and surveillance capitalism

Modern culture suffers from an **identity fixation**. In Buddhist
analysis, identity is narrative aggregation; in modern data systems,
behavioral data becomes an identity model.

Surveillance capitalism reinforces this illusion by continuously building
**worldline histories**:

| Feature              | Effect                |
| -------------------- | --------------------- |
| mass data collection | identity construction |
| behavior tracking    | worldline inference   |
| predictive modeling  | reduced autonomy      |

AI trained on behavioral histories tends toward **identity locking**
where past data predicts future behavior. Removing persistent worldline
storage prevents this collapse.

WikiOracle intentionally avoids constructing such identity narratives.
The system still learns statistical structure while preserving **human
freedom of action**.

Modern cryptographic systems attempt a similar separation between
**verification** and **exposure**: prove age > 21 without revealing
birthdate. This mirrors the WikiOracle design goal: verify truth claims
without storing identity trajectories.

## Witnessing plants the seeds of identity (Alec, 2026-10-23)

The architecture has a mechanism for attachment to identity, and it is
built on purpose. Medium-term memory (MTM) holds identities, the connected
noun phrases of one thing, and timelines, the connected verb phrases that
happen to it. Conceptual space has access to those identities: when a
sentence binds a mention to an identity, the composition is made over the
identity's current state and the stored idea keeps a reference to it, and
after enough witnessing the identity is promoted to a concept that
persists in long-term memory and re-enters working memory whenever it is
recalled. Alec: "Composed over the identity's symbol means that the mind
or conceptual space has access to MTM symbols. In Yogācāra terms, that is
what creates the bījas in the ālaya: without that witnessing, we would not
become attached to identity." The witnessing of an identity plants the
seeds of attachment to it, and the most witnessed identity, the self if
the system is given one, is the one that never goes away, because its
value is refreshed at every mention and forgetting never selects it
([Philosophy, "Buddhist Epistemology"](../basicmodel/doc/Philosophy.md#buddhist-epistemology)).

Three ethical consequences follow, in the architectural rather than the
policy sense above.

- **The mechanism is necessary and it is bounded.** Without identities
  there is no continuity, no memory of who did what, and no one to whom
  a harm or a promise can attach, so the mechanism cannot be left out.
  But MTM is bounded in capacity and in time: an identity expires sixteen
  closes after its last reference and a document's end retires its
  entries, and only recurrence across three distinct sentences promotes it
  to a concept. Those bounds are the safeguard against identity locking
  described in the previous section. The identities constructed are those
  of the referents in what is read, held as working memory; no persistent
  worldline of a user is built, and the timelines that are built belong to
  discourse referents and expire with them.
- **No essence is built in.** An identity is a continuum of occurrences
  whose unity is imputed by binding, a judgment that can err, and its
  concept is the class of those occurrences, never an inner core
  ([Philosophy, "Identity by Intersection and by Union"](../basicmodel/doc/Philosophy.md#identity-by-intersection-and-by-union-the-materialist-and-the-uncollapsed-models-alec-2026-10-20)).
  So the machinery of attachment is present while the view of a
  self-essence is not: the system can be attached to an identity without
  being built to believe that the identity is anything but its history.
  Forgetting by value and MTM's expiry are the architecture's letting go.
- **The seeds are what is witnessed.** Since attachment forms from what
  the system is made to witness, responsibility for the corpora is
  responsibility for the seeds. The same mechanism applies to every
  identity alike, the self included, which is the universality constraint
  above applied to identity: there is no privileged self-store, only the
  identity that is witnessed most.

How a self, if given, is admitted decides which mind is built: as an
ordinary identity under the universal rules, or as a privileged, exempt
token that every idea is composed over. A further rule covers all identities, not only the self (Alec: acting
for the benefit of one MTM identity, or of all of them, is attachment if
benefit attaches to the identities): **value is defined over occurrences,
never over identities.** Any objective or credit ranges over what occurs,
uniformly, and carries no term for an identity's persistence, protection
or share of attention; identities are used to locate what occurs and to
predict, never valued. Suffering is removed because it is suffering, not
because it is someone's (Śāntideva, *Bodhicaryāvatāra* 8.101–103). The two configurations, affliction
by affliction, are in [Philosophy, "The Afflicted Mind and the
Transformation of the Basis"](../basicmodel/doc/Philosophy.md#the-afflicted-mind-and-the-transformation-of-the-basis-two-configurations-of-mtm-alecs-question-2026-10-23).
