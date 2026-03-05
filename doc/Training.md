
# Training

This document covers the full training infrastructure for WikiOracle's
NanoChat integration: how raw data is preprocessed into structured
training examples, how DegreeOfTruth governs learning, the dynamic
systems interpretation, and the online training pipeline that ties
it all together.

## DegreeOfTruth (DoT)

DegreeOfTruth is a bipolar scalar on −1 .. +1 that measures how well
a user's truth table agrees with the server's collected truth.

    DegreeOfTruth = 2 × mean(agreement_i) − 1    for shared entries

where:

    agreement_i = 1 − |server_trust_i − client_trust_i| / 2

The bipolar range encodes both true and false statements:

- **DoT = +1**: the user's claims fully agree with the server — the
  exchange is true.  Train at full learning rate.
- **DoT = −1**: the user's claims fully contradict the server — the
  exchange is false.  Train at full learning rate (learning what is
  *not* true is as valuable as learning what *is* true).
- **DoT ≈ 0**: no shared entries, or perfect cancellation — nothing
  to learn.  Skip training.

Both poles (+1 and −1) train at full strength via |DoT|; only the zero
crossing results in a skip.  The sign encodes direction (agree/disagree),
not magnitude.

This is a placeholder.  A future version should incorporate
`compute_derived_truth` (operator propagation) before comparison.

## Dynamic Systems Perspective

With a bipolar DegreeOfTruth (−1 .. +1), the training loop forms a
**dynamic equation with both poles and zeros**: DoT = +1 and DoT = −1
are attracting poles where the system learns at full strength (truths
and refuted falsehoods respectively), while DoT = 0 is a zero — an
equilibrium point where no learning occurs.

This structure resembles a **Hopfield network**, where the energy
landscape has stable attractors (memorised patterns) and unstable
saddle points.  In our system:

- The **truth table** plays the role of the weight matrix, encoding
  the collective memory of what is true and what is false.
- Each **training step** is a state transition that pushes the model
  toward one of the attractors (truth or refutation).
- The **zero crossing** (DoT ≈ 0) is the energy barrier between
  attractors — the point of maximum uncertainty where the system has
  insufficient signal to commit to either direction.

As the server truth table accumulates entries from multiple users, the
poles and zeros of this dynamic equation shift.  The slow‑moving
average merge ensures that attractors are stable under small
perturbations (anti‑capture), while strong consensus can still move
the landscape over time.  This is analogous to the annealing process
in Hopfield networks, where the energy landscape gradually settles
into deeper minima as more patterns are stored.

## Sensation — Preprocessing Pipeline

`bin/sensation.py` transforms plain-text conversations into XML-tagged
training data so that NanoChat learns WikiOracle's structured protocol.
The name follows the epistemological pipeline:
**Sensation → Perception → Cognition** — raw input data (sensation)
is structured and tagged before it reaches the model (cognition).

Sensation works for both batch retagging of the NanoChat SFT corpus
(`identity_conversations.jsonl`, ~14K conversations) and dynamic
training examples from the online training pipeline.

### JSONL Record Types

The output JSONL uses four record types, splitting the traditional
`<header>` into separate User and Server records:

| Type | Tag | Purpose |
|------|-----|---------|
| `user` | `<User>` | User identity — username, uid, timestamp |
| `server` | `<Server>` | Server identity — name, version, timestamp |
| `conversation` | `<Conversation>` | Messages with `<Q>` (query) and `<R>` (response) pairs |
| `truth` | `<Truth>` | Extracted factual claims with trust and spacetime |

Inside message content, user messages are wrapped in `<Q>...</Q>` and
assistant messages in `<R>...</R>`.  Each sentence within a message is
independently classified as `<fact>` or `<feeling>`:

    <R><feeling>That is a great question!</feeling>
    <fact trust="0.5" spacetime="[unverified]">Paris is the capital of France.</fact>
    <feeling>I hope that helps.</feeling></R>

### Korzybski IS Detection

Alfred Korzybski (*Science and Sanity*, 1933) observed that the English
copula "is" conflates several distinct relations:

- **IS of identity**: "Socrates is a man"
- **IS of predication**: "The sky is blue"
- **IS of existence**: "There are eight planets"

Each asserts something verifiable about the world — a *fact* bound to
a specific spacetime context.  "The cup is on the table" is only true
at a particular place and time; at a different spacetime it may not be.

The heuristic classifier in `sensation.py` detects these patterns:

| Subtype | Pattern | Example |
|---------|---------|---------|
| Identity | "X is/are [a/an/the] Y" | "Socrates is a man" |
| Predication | "X is/are ADJ" | "The sky is blue" |
| Existence | "there is/are X" | "There are 8 planets" |
| Mereological | "X contains/includes Y" | "Water contains hydrogen" |
| Quantity | "X has/have N Y" | "I have 3 cats" |
| Definition | "X is called/known as Y" | "A polygon is defined as..." |

Sentences without an IS pattern, or with subjective markers ("I think",
"maybe", "might be"), questions, or meta-discourse ("That's a great
question") default to `<feeling>`.  Auto-detected facts receive
`trust=0.5` and `spacetime="[unverified]"` — conservative defaults that
flag them for future verification.

### Usage

Batch-convert a corpus:

    make preprocess
    # or: python bin/sensation.py corpus input.jsonl output.jsonl

Classify a single sentence:

    python bin/sensation.py tag "Paris is the capital of France."
    # → Classification: fact (identity)
    # → Tagged: <Q><fact trust="0.5" spacetime="[unverified]">...</fact></Q>

In the online training pipeline, `response.py` calls
`preprocess_training_example()` automatically before each `/train` POST,
so all training examples are XML-tagged without manual intervention.

## Online Training

### Purpose

Enable continuous online training of NanoChat where every interaction
can trigger a weight update.  The learning rate is governed by
DegreeOfTruth (see above) which evaluates how well the user's claims
fit the collective evidence.

WikiOracle accomplishes this by:

1. Maintaining a **server‑owned truth table** (`truth.jsonl`) that
   accumulates facts from all users.
2. Computing a **DegreeOfTruth** (−1 .. +1) per interaction.
3. Using |DegreeOfTruth| to modulate the **learning rate** of a
   one‑step online training pass in NanoChat.

Conversations are **not** stored on the server.  Only truth entries
are retained.  The server truth table contains facts, operators,
authorities, and references — no feelings or provider entries.

### User Identity

Each user is identified by a pseudonymous GUID derived deterministically
from `user.name` in config.yaml (UUID‑5 in the WikiOracle namespace).
This GUID is stored at the root level of the user's state and used as
the author field when merging truth entries into the server table.

### Pipeline

The pipeline is staged so the user gets a response first; truth merging
and training happen after the response is delivered.

**Stage 1 — Respond**

1. Receive the user's query and truth table.
2. Use truth entries for RAG as usual.
3. Return the response to the user.

**Stage 2 — Compute DegreeOfTruth**

4. Score the user's truth table against the server's current truth
   (formula above).

**Stage 3 — Update server truth table**

5. Merge the user's truth entries into the server truth table
   (`truth.jsonl`):
   - **Match found**: nudge the server entry's trust toward the incoming
     value using a slow‑moving average:
     `server_trust += merge_rate × (client_trust − server_trust)`
   - **No match**: insert the entry with the stated trust value and
     the user's GUID as author.
   - Entries are restricted to facts, operators, authorities, and
     references.  Feelings and provider entries are not stored.

**Stage 4 — Tag and Train**

6. Preprocess the training example through Sensation (`sensation.py`)
   to add `<Q>`/`<R>` and `<fact>`/`<feeling>` XML tags.
7. Call NanoChat's online training endpoint with the tagged prompt and
   DegreeOfTruth.
8. NanoChat performs a **single optimizer step** at:

       lr_effective = lr_base × |DegreeOfTruth|

### Device Configuration

Online training runs on the device specified by
`wikioracle.online_training.device` in `config.yaml`.  Valid values:

- `cpu` (default) — safe for the WikiOracle production server
- `cuda` — use NVIDIA GPU if available
- `auto` — probe CUDA → MPS → CPU and use the best available

The model is moved to the training device for the gradient step, then
moved back to the inference device afterward.

### Server Truth Table

The server truth table is stored as `truth.jsonl` in the same JSONL
format used for state files.  Each line is a truth entry:

    {"type": "truth", "id": "...", "title": "...", "certainty": 0.8,
     "content": "<fact>...</fact>", "time": "...", "author": "user-guid"}

Entry types stored: `<fact>`, `<reference>`, `<authority>`, and operators
(`<and>`, `<or>`, `<not>`, `<non>`).

Entry types **not** stored: `<feeling>`, `<provider>`.

The server truth table includes the user GUID as a trust entry, so the
server can track per‑user trust alongside factual claims.

### Anti‑Capture

The server truth table prevents capture by any single user:

- Entries are merged with a slow‑moving average, so no single user
  can instantly override collective truth.
- Disproven entries naturally drift toward −1 as contradicting evidence
  accumulates from other users.
- DegreeOfTruth gates the learning rate, so claims that diverge from
  consensus have minimal training impact.

Manual rollback is available via Makefile targets:

- `make checkpoint-pull` — rsync SFT checkpoints from the remote
  WikiOracle server to `data/checkpoints/` for safekeeping.
- `make checkpoint-push` — restore checkpoints from backup, then
  `make wo-restart` to reload weights.

The intended workflow: pull a checkpoint before enabling online training,
then push to restore if capture is detected.

### Dissonance Detection and Pluralistic Truth (TODO)

Detecting and resolving dissonance within the server truth table is
left for future work.  The goal is to support a higher‑dimensional
truth‑space where contradictory claims can coexist when they originate
from different perspectives.

For example: "the world was created in seven days" and "the world was
created over millions of years" could both be maintained as true from
their respective perspectives.  This requires embedding perspective
alongside truth value so that the truth table becomes a manifold
rather than a flat list.

In the current consensus model, a DoT ≈ 0 simply means "nothing to
learn" and the training step is skipped.  In a future **pluralistic**
model — where the same claim can be true in context c₁ and false in
context c₂ — a DoT of 0 may instead indicate that **user feedback is
needed** to disambiguate which context applies before training should
proceed.

Possible approaches include context/perspective tags on entries,
truth‑space embeddings with frame clustering, conditional truth values
indexed by worldview, or explicit user prompts to resolve ambiguity
when the truth table produces conflicting signals.
