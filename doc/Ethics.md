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
contradictory, it reveals an ethical inconsistency — the claim is
asymmetric and should not be admitted as fact. The system offers to
record the statement as a feeling instead, preserving the user's
expression without endorsing the claim as truth.

This is controlled by the `truth_symmetry` config option (default: true).
See [Config.md](./Config.md) §5a and the implementation in
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

| Ethical failure | Epistemic distortion |
|-----------------|---------------------|
| propaganda | false belief |
| discrimination | asymmetric reasoning |
| authoritarianism | opaque claims |
| scapegoating | category errors |

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

## Truth improves ethics

We wish to predict Truth. 
We do not wish to predict Lies.
In fact, we wish to develop an aversion to lies.
Epistemic ignorance is often desireable. 

*All lies are harmful because they undermine the dignity of others. Lies prevent people acting freely and rationally. When someone lies, he interferes with his audience’s right to receive information that is correct. Also, lies distort the ability to make informed decisions. Kant goes further and argues that lies cause broader harm by undermining a speaker’s credibility, which, in turn, causes people to distrust each other’s contentions. Kant even goes as far as to say lying is immoral, under all conditions.*
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

| Feature | Ethical effect |
|---------|---------------|
| explicit truth values | discourages propaganda |
| multiple POVs | prevents epistemic monopoly |
| no worldline storage | protects identity |
| local-first architecture | preserves autonomy |
| inspectable reasoning | prevents hidden authority |

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

| Feature | Effect |
|---------|--------|
| mass data collection | identity construction |
| behavior tracking | worldline inference |
| predictive modeling | reduced autonomy |

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

