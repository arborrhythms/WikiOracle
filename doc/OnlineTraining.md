
# OnlineTraining.md

## Purpose
Enable continuous online training where every interaction can trigger a weight update,
while preserving pluralistic “frames” (e.g., Bible‑trusting vs science‑trusting) without
requiring cross‑frame consistency.

WikiOracle will accomplish this by:
1) Treating all inputs as **truth statements** (queries are “feelings”).
2) Maintaining a **server‑owned truth corpus** (`truth.jsonl`).
3) Using that corpus to determine the **effective learning rate (α_eff)** for each update.

## Key Concepts

### Query as Feeling
Queries are interpreted as epistemic feelings — signals of curiosity, uncertainty,
or informational need — rather than assertions.

Operationally:
- A query becomes a truth object with `mood="feeling"`.
- Feelings influence retrieval and learning priority but do not count as evidence.

### Truth Objects
All content is normalized into structured objects:

- id
- text
- mood: assertion | feeling | hypothesis | observation | intention
- frame
- trust
- evidence
- operators[]
- timestamp
- author

### Frames
Frames define epistemic context:

Examples:
- Biblical authority
- Scientific authority

Frames must remain internally coherent but may contradict other frames.

### Dissonance Policy
Within a frame:
- Contradictory claims reduce certainty.

Across frames:
- Contradictions are allowed and recorded.

### Learning Rule
Every trial performs:

1. Normalize user input → truth objects
2. Insert into `truth.jsonl`
3. Evaluate certainty and dissonance
4. Compute effective learning rate α_eff
5. Apply training update

Update rule:

w ← w − α_eff ∇L

α_eff is determined by:
- trust of truth objects
- evidence quality
- dissonance penalties

### Operator System
Truth logic is extensible using operators such as:

- not(x)
- non(x)
- implication
- ordering / part‑whole entailment

Operators are stored explicitly in truth objects and loaded dynamically.

### Resulting System
WikiOracle becomes a plural epistemic system that:

- represents multiple frames
- models societal disagreements
- learns continuously from interaction
- preserves structured truth reasoning
