# Ethics

**Ethical AI through Truth Architecture in WikiOracle**

## Entanglement Policy

**No spacetime particulars $\to$ no worldline capture**

| Data type | Truth table | Train weights | Session only |
|-----------|-------------|---------------|--------------|
| universal facts | $\checkmark$ | $\checkmark$ | $\checkmark$ |
| particular facts | optional | $\checkmark$ | $\checkmark$ |
| feelings | $\times$ | $\times$ | $\checkmark$ |

This table is the architectural foundation. It separates knowledge into
three channels — knowing, learning, and valuing — each with a different
persistence policy. Universal facts (broad spatiotemporal extent) persist
as reasoning premises and train weights. Particular facts (narrow
spatiotemporal extent) always train weights and optionally persist to the
truth table when `store_particulars` is true. Feelings are session-only.

The result: the system **learns from events but never stores worldline
histories** (unless the user explicitly opts in).

See [Entanglement.md](./Entanglement.md) for the full policy,
[Config.md](./Config.md) for the `store_particulars` setting that
controls particular-fact persistence, and
[Training.md](./Training.md) for the online training pipeline.

### Why particular facts always train weights

Three design considerations fix row 2 of the table:

1. **Pluralism requires inspectable particulars.** WikiOracle supports
   plural truth — different epistemic frames may hold different
   particular claims (e.g. "the universe was created in seven days").
   Recording such claims as facts with explicit certainty values makes
   them inspectable and contestable. Relegating them to weight-space
   would bury them as invisible biases. The `store_particulars` option
   lets the user decide whether these persist in the truth table.

2. **The fact/feeling boundary is the privacy boundary.** If a user
   considers content too personal or sensitive to train on, the correct
   action is to label it a *feeling*, not a fact. Feelings are
   session-only by design — they never train weights or enter the truth
   table. The privacy boundary is therefore controlled by the user's
   choice of tag, not by the universal/particular distinction.

3. **PII detection is the safety net.** Even when `store_particulars`
   is true, the `detect_identifiability()` function filters entries
   containing PII patterns (emails, phone numbers, GPS coordinates,
   named individuals with temporal markers) before any persistence.
   This prevents worldline capture at the content level regardless of
   the user's storage preference.

The result: particular facts always carry empirical signal worth
learning from. Storage in the truth table is the user's choice.
Privacy is enforced by fact/feeling labeling and PII detection, not
by withholding training.

---

## Enforce Truth Symmetry

Statements involving value judgements are checked for asymmetric harm
under identity exchange before admission to the truth table. If a claim
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

---

## 1. Architectural ethics vs policy ethics

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

---

## 2. Global truth with local freedom (LFGC)

The design parallels the physics principle of **[Local Freedom under
Global Constraint (LFGC)](https://zenodo.org/records/18644302)**.

Physics interpretation:

    global constraints + local underdetermination

WikiOracle analogue:

    global truth constraints + human interpretive freedom

This means the system preserves a **shared knowledge structure** while
allowing individual reasoning to remain flexible.

| Domain | Constraint | Local freedom |
|--------|------------|---------------|
| physics | boundary conditions | event selection |
| knowledge | truth constraints | interpretive reasoning |
| cryptography | verification rules | selective disclosure |
| surveillance capitalism | behavioral prediction | (suppressed) |

WikiOracle aims to implement **epistemic LFGC** — freedom exists
*inside constraint geometry*.

---

## 3. Entanglement avoidance and sovereignty

The Entanglement Policy (table above) prevents worldline reconstruction.

Because surveillance capitalism relies on tracking sequences of events
tied to identity, removing spacetime anchors prevents the database from
constructing behavioral profiles.

The system therefore stores **conceptual truth** but not **identity
trajectories**.

This preserves:

-   autonomy
-   privacy
-   epistemic independence

WikiOracle separates three layers:

### Conceptual knowledge

General truths and logical relations.

### Interpretive reasoning

Client-driven reasoning over those truths.

### Personal experience

Not stored unless explicitly permitted.

Thus the system allows collective knowledge accumulation without
collective surveillance.

---

## 4. Reasoning about generalities vs specifics

WikiOracle reasons primarily about **generalities** (universal facts).

Specific facts may only be reasoned about when:

1.  they are supplied by the client, or
2.  the client explicitly allows those particulars to be stored.

Thus:

> AI reasons about general knowledge.
> Users control the use of personal particulars.

This maintains sovereignty over personal data.

---

## 5. Symmetry as a foundation of ethical reasoning

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

---

## 6. Reciprocity symmetry

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

## 7. Reversibility symmetry

Accepted conclusions must be **inspectable and reversible**.

Opaque reasoning creates hidden authority.

WikiOracle counters this by requiring:

-   explicit truth values
-   inspectable reasoning chains
-   transparent authority imports

## 8. Harm symmetry

A claim permitting harm should remain valid when applied symmetrically.

This is the core of the Truth Symmetry enforcement described above.
If swapping identity references makes a claim contradictory or
indefensible, it reveals an ethical inconsistency that the system flags.

## 9. Truth improves ethics

Ethical progress historically correlates with improved truth systems.

Examples:

-   scientific method
-   journalism standards
-   legal evidence systems

As epistemic clarity improves, harmful distortions become harder to
maintain. Thus improving truth infrastructure indirectly improves ethical
reasoning.

## 10. Ethical knowledge geometry

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

## 11. Architectural ethical primitives in WikiOracle

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

## 12. Symmetry operators

The system includes checks for:

-   reciprocity symmetry (perspective exchange)
-   reversibility symmetry (inspectable, contestable conclusions)
-   harm symmetry (identity-swap test via `detect_asymmetric_claim()`)

These checks identify logically inconsistent or discriminatory claims.

## 13. Epistemic humility

The system must allow truth states such as:

-   unknown
-   undetermined

Forcing premature conclusions can distort reasoning and produce
unethical outcomes.

## 14. Distributed governance

Ethical truth systems should not be controlled by a single authority.

Instead they should allow shared constraint setting.

This reduces the risk of epistemic monopolies.

## 15. The identity crisis and surveillance capitalism

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

## 16. Zero-Knowledge and selective disclosure

Modern cryptographic systems attempt a similar separation between
**verification** and **exposure**: prove age > 21 without revealing
birthdate. This mirrors the WikiOracle design goal: verify truth claims
without storing identity trajectories.

## 17. Ethical AI as freedom within constraint

Ethical intelligence may emerge from the balance:

    freedom + constraint

This mirrors both:

-   [LFGC](https://zenodo.org/records/18644302) physics concepts
-   philosophical traditions linking wisdom and compassion

The system does not force ethical behavior, but unethical reasoning
becomes unstable within the truth architecture.

