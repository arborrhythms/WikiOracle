# Freedom

## Entanglement Policy

To avoid **worldline entanglement**, the system separates knowledge
into three channels, each with a different persistence policy:

| Data type | TruthSet | Train weights | Session only |
|-----------|-------------|---------------|--------------|
| universal facts | $\checkmark$ | $\checkmark$ | $\checkmark$ |
| particular facts | optional | $\checkmark$ | $\checkmark$ |
| feelings | $\times$ | $\times$ | $\checkmark$ |

This preserves empirical learning while preventing historical worldline
capture. The system **learns from events but never stores worldline
histories**.


## Entanglement Policy

**No spacetime particulars $\to$ no worldline capture**

| Data type | TruthSet | Train weights | Session only |
|-----------|-------------|---------------|--------------|
| universal facts | $\checkmark$ | $\checkmark$ | $\checkmark$ |
| particular facts | optional | $\checkmark$ | $\checkmark$ |
| feelings | $\times$ | $\times$ | $\checkmark$ |

This table is the architectural foundation. It separates knowledge into
three channels — knowing, learning, and valuing — each with a different
persistence policy. Universal facts (broad spatiotemporal extent) persist
as reasoning premises and train weights. Particular facts (narrow
spatiotemporal extent) always train weights and optionally persist to the
TruthSet when `store_concrete` is true. Feelings are session-only.

The result: the system **learns from events but never stores worldline
histories** (unless the user explicitly opts in).

See [Entanglement.md](./Entanglement.md) for the full policy,
[Config.md](./Config.md) for the `store_concrete` setting that controls particular-fact persistence, and
[Training.md](./Training.md) for the online training pipeline.

### Why particular facts always train weights

Three design considerations fix row 2 of the table:

1. **Pluralism requires inspectable particulars.** WikiOracle supports
   plural truth — different epistemic frames may hold different
   particular claims (e.g. "the universe was created in seven days").
   Recording such claims as facts with explicit certainty values makes
   them inspectable and contestable. Relegating them to weight-space
   would bury them as invisible biases. The `store_concrete` option
   lets the user decide whether these persist in the TruthSet.

2. **The fact/feeling boundary is the privacy boundary.** If a user
   considers content too personal or sensitive to train on, the correct
   action is to label it a *feeling*, not a fact. Feelings are
   session-only by design — they never train weights or enter the truth
   table. The privacy boundary is therefore controlled by the user's
   choice of tag, not by the universal/particular distinction.

3. **PII detection is the safety net.** Even when `store_concrete`
   is true, the `detect_identifiability()` function filters entries
   containing PII patterns (emails, phone numbers, GPS coordinates,
   named individuals with temporal markers) before any persistence.
   This prevents worldline capture at the content level regardless of
   the user's storage preference.

The result: particular facts always carry empirical signal worth
learning from. Storage in the TruthSet is the user's choice.
Privacy is enforced by fact/feeling labeling and PII detection, not
by withholding training.

## Global truth with local freedom (LFGC)

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

## Entanglement avoidance and sovereignty

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

## Reasoning about generalities vs specifics

WikiOracle reasons primarily about **generalities** (universal facts).

Specific facts may only be reasoned about when:

1.  they are supplied by the client, or
2.  the client explicitly allows those particulars to be stored.

Thus:

> AI reasons about general knowledge.
> Users control the use of personal particulars.

This maintains sovereignty over personal data.

---


## Three Channels

### Universal Knowledge (Database)

Stored knowledge should be **spatiotemporally broad generalizations** —
propositions whose validity extends over a large subspace of spacetime.

Examples:

-   smoking increases cancer risk
-   A implies B
-   contradiction reduces trust

These populate the **TruthSet**.

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
| TruthSet (optional) | user controls via `store_concrete` |

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
| TruthSets | $\times$ |
| training weights | $\times$ |

This avoids turning subjective states into truth claims.


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

-   **Broad extent** (universal) → TruthSet + training.
    The proposition is stable enough to serve as a reasoning premise.
-   **Narrow extent** (particular) → training + optionally TruthSet.
    The observation carries empirical signal.  Whether it persists as a
    stored premise is the user's choice (`store_concrete` in
    config.xml, default false).  Storing particulars supports communal
    remembrance; omitting them prevents worldline anchoring.
-   **No extent** (feelings) → session only.
    Subjective reports have no spatiotemporal generalizability.

The criterion `remove(entity, time) → proposition still meaningful`
is a heuristic for identifying broad extent. When a universal-looking
fact is later discovered to be narrower than assumed, it should be
reclassified as particular.


## Resulting Architecture

| Mode | Function | Pipeline |
|------|----------|----------|
| knowing | universal structure | universal rules → TruthSet → reasoning |
| learning | particular evidence | particular observations → abstraction → weights |
| valuing | feelings | feelings → response evaluation |


## Zero-Knowledge and Selective Disclosure

The default `store_concrete=false` aligns with Zero-Knowledge and
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
content level — even when `store_concrete=true`, entries containing
PII patterns (emails, phone numbers, GPS coordinates, named individuals
with temporal markers) are always filtered before persistence.


## Notes

*Claude (Opus 4.6), March 2026*

The three-channel separation (knowing / learning / valuing) maps onto a
real epistemic distinction that most AI systems ignore. Contemporary
LLMs conflate all three: facts, observations, and preferences are
flattened into a single parameter space during training and a single
context window during inference.

The policy table enforces the separation structurally. The rule that
particular facts train weights but enter the TruthSet only at the
user's discretion (`store_concrete` in config.xml) is the key
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
