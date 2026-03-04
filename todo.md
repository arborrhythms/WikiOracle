
# todo.md

## Goal
Modify WikiOracle to support online learning governed by a server‑maintained truth corpus.

Key elements:
- truth.jsonl maintained by server
- all inputs normalized into truth objects
- truth corpus determines learning rate α_eff
- frames provide epistemic conditioning

---

## 1. Truth Corpus Infrastructure

Create:

data/truth.jsonl

Append-only log of truth objects.

Add indexing layer:

data/truth_index/

Indexes by:
- frame
- keywords
- trust
- operator
- timestamp

---

## 2. Truth Object Schema

Add specification file:

spec/truth_object_v1.json

Fields:

id
text
mood
frame
trust
evidence
operators
timestamp
author

---

## 3. Frame System

Add frame schema:

spec/frame_v1.json

Fields:

frame_id
authority_set
priors
operator_set

Frames determine epistemic context.

---

## 4. Server Pipeline Changes

Modify wikioracle.py request pipeline:

Steps:

1) Normalize inbound content → truth objects
2) Insert into truth.jsonl
3) Detect dissonance
4) Compute α_eff
5) Perform training step

---

## 5. Truth Engine Module

Create module:

bin/truth_engine.py

Responsibilities:

- truth ingestion
- claim canonicalization
- contradiction detection
- certainty updates
- α_eff computation

---

## 6. Dissonance Detection

Within frames:

Detect contradictions using:

- negation operators
- numeric conflicts
- mutually exclusive predicates

Reduce trust when conflicts appear.

---

## 7. Learning Rate Controller

Function:

compute_alpha(truth_objects, frame_state)

Higher certainty → higher α

Higher dissonance → lower α

---

## 8. Online Trainer

Create module:

training/online_trainer.py

Function:

step(training_payload, α_eff, truth_prefix)

Responsibilities:

- prefix conditioning
- optimizer step

---

## 9. Operator Registry

Add:

operators/registry.py

Supports dynamic operator loading.

Operators stored in:

operators/operators.jsonl

---

## 10. Authentication

Add user store:

users.jsonl or sqlite

Fields:

user_id
trust_user
domain_trust

Used to weight truth evidence.

---

## 11. Query Handling

Queries become:

TruthObject(mood="feeling")

Feelings influence retrieval and priority but not truth evidence.

---

## 12. Configuration

Extend config.yaml:

online_training.enabled
truth_corpus.path
alpha.base
alpha.min
alpha.max
dissonance.enabled
operators.dynamic_enabled

---

## 13. Testing

Add tests for:

- truth object validation
- operator registry
- contradiction detection
- α_eff scaling

Integration test:

Two frames (creationist vs scientific) answering same query
