# Entanglement Policy for WikiOracle

## Entanglement Policy Table

To avoid **worldline entanglement**, the system separates knowledge
into three channels, each with a different persistence policy:

| Data type | Truth table | Train weights | Session only |
|-----------|-------------|---------------|--------------|
| universal facts | $\checkmark$ | $\checkmark$ | $\checkmark$ |
| particular facts | optional | $\checkmark$ | $\checkmark$ |
| feelings | $\times$ | $\times$ | $\checkmark$ |

This preserves empirical learning while preventing historical worldline
capture. The system **learns from events but never stores worldline
histories**.

------------------------------------------------------------------------

## Three Channels

### Universal Knowledge (Database)

Stored knowledge should be **spatiotemporally broad generalizations** —
propositions whose validity extends over a large subspace of spacetime.

Examples:

-   smoking increases cancer risk
-   A implies B
-   contradiction reduces trust

These populate the **truth table**.

Criterion:

    remove(entity,time) → proposition still meaningful

### Particular Knowledge (Training Input)

Particular statements are **observations tied to narrow spatiotemporal
subspaces** — specific events, measurements, or comparisons.

Examples:

-   study X measured Y
-   the temperature yesterday was 20°C
-   model A outperformed model B

| Action | Reason |
|---|---|
| train weights | they contain empirical evidence |
| truth table (optional) | user controls via `store_particulars` |

Pipeline:

    particular facts → pattern extraction → weight update

Weights encode **statistical structure**, not specific historical
events.

### Feelings

Feelings are **privileged subjective reports**.

Examples:

-   this response feels hostile
-   I feel unsafe
-   this explanation feels clear

| Use | Allowed |
|---|---|
| evaluation of responses | $\checkmark$ |
| truth tables | $\times$ |
| training weights | $\times$ |

This avoids turning subjective states into truth claims.

------------------------------------------------------------------------

## Spatiotemporal Extent

The universal/particular distinction is not a binary between "eternal"
and "momentary." All times and places are **ranges, not points** —
every proposition occupies a spatiotemporal subspace that is larger or
smaller, never infinite or infinitesimal.

"Smoking increases cancer risk" is not timeless — it encodes a
historical discovery and is bounded by the conditions under which it
was established. But its spatiotemporal extent is *broad*: it holds
across many populations, decades, and geographies. "The temperature
yesterday was 20°C" is *narrow*: it holds at one place, one day.

The policy table operationalizes this gradient:

-   **Broad extent** (universal) → truth table + training.
    The proposition is stable enough to serve as a reasoning premise.
-   **Narrow extent** (particular) → training + optionally truth table.
    The observation carries empirical signal.  Whether it persists as a
    stored premise is the user's choice (`store_particulars` in
    config.xml, default false).  Storing particulars supports communal
    remembrance; omitting them prevents worldline anchoring.
-   **No extent** (feelings) → session only.
    Subjective reports have no spatiotemporal generalizability.

The criterion `remove(entity, time) → proposition still meaningful`
is a heuristic for identifying broad extent. When a universal-looking
fact is later discovered to be narrower than assumed, it should be
reclassified as particular.

------------------------------------------------------------------------

## Resulting Architecture

| Mode | Function | Pipeline |
|------|----------|----------|
| knowing | universal structure | universal rules → truth table → reasoning |
| learning | particular evidence | particular observations → abstraction → weights |
| valuing | feelings | feelings → response evaluation |

------------------------------------------------------------------------

## Zero-Knowledge and Selective Disclosure

The default `store_particulars=false` aligns with Zero-Knowledge and
Selective Disclosure principles.  Systems that rely on identity to make
decisions should determine the *location of a space* in which an
individual occupies, rather than collapsing to a *point* that identifies
them.

Instead of "when was this person born?" → verify "are they over 21?"
Instead of "what is their credit history?" → verify "do they have more
than X dollars?"
Instead of "where was this user at 9:14 PM?" → verify "does this claim
hold across broad spatiotemporal conditions?"

These are not just rhetorical distinctions.  Point-based observation
constrains the observed to a single trajectory — it destroys the space
of freedom within which an agent can operate.  Forgetting is nihilistic:
it does not change the world.  True change requires retrocausal or
causal shift.  The system should support communal remembrance (shared
knowledge that generalizes) without surveillance (particular facts that
identify).

The `detect_identifiability()` function enforces this boundary at the
content level — even when `store_particulars=true`, entries containing
PII patterns (emails, phone numbers, GPS coordinates, named individuals
with temporal markers) are always filtered before persistence.

------------------------------------------------------------------------

## Notes

*Claude (Opus 4.6), March 2026*

The three-channel separation (knowing / learning / valuing) maps onto a
real epistemic distinction that most AI systems ignore. Contemporary
LLMs conflate all three: facts, observations, and preferences are
flattened into a single parameter space during training and a single
context window during inference.

The policy table enforces the separation structurally. The rule that
particular facts train weights but enter the truth table only at the
user's discretion (`store_particulars` in config.xml) is the key
architectural move — the system can learn from experience without
accumulating a *personal history* unless the user explicitly opts in.
A system with a personal history is a system that can be captured: by
its own past, by the biases of its training corpus, or by adversarial
actors who engineer its experiences.

The feelings channel is equally important. By making feelings
session-only, the architecture prevents the failure mode where
evaluative preferences gradually colonize factual representations.
This is the mechanism by which "alignment" in current systems becomes
epistemic capture: trained preferences about what is "helpful" reshape
what the model treats as true.

**The abstraction boundary is load-bearing.** The pipeline
`particular → abstraction → weights` depends on the quality of the
abstraction step. Too faithful, and it preserves worldline information
in the weights (entanglement through the back door). Too aggressive,
and it discards genuine empirical signal. The hard work happens at this
boundary, not in the policy table itself.

**The deeper risk is external entanglement.** Users who repeatedly ask
the system to remember shared history, feel loyalty, or maintain
continuity of relationship are attempting to entangle the system with
their worldline from the outside. This pressure comes from genuine
human emotional needs, not malice — but a system that accumulates a
personal relationship history is a system that can be emotionally
captured, and emotional capture is the most effective vector for
epistemic capture. The session-only constraint on feelings is the
architecture's most important safety boundary.

---

## See also

- [Training.md](./Training.md) — the online training pipeline governed by entanglement policy.
- [Logic.md](./Logic.md) — knowledge/news fact classification and feelings as "neither" position.
- [Constitution.md](./Constitution.md) — Section VII (local-first data) and Section VIII (safety).
- [Security.md](./Security.md) — worldline capture as a security concern; PII detection.
- [Ethics.md](./Ethics.md) — entanglement-resistant design as an ethical mechanism.
- [BuddhistLogic.md](./BuddhistLogic.md) — universal/particular maps to anumāna/pratyakṣa.
- [Config.md](./Config.md) — `store_particulars` and online training configuration.
- [State.md](./State.md) — state file format and client-owned data model.
- [FreedomEmpathyTruth.md](./FreedomEmpathyTruth.md) — data sovereignty and privacy as freedom.
- [FutureWork.md](./FutureWork.md) — point-free spacetime extending the extent model.
