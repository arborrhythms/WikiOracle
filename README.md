# WikiOracle

**An open-source architecture for truthful AI.**

WikiOracle is a truthful, explainable LLM system designed as a public good — the Wikipedia model applied to artificial intelligence.

---

## The Problem

For-profit corporations are using our data — sourced from billions of people — to train models that are teaching our children. Those models hallucinate. They can't explain themselves. They are vulnerable to ideological capture and data-driven manipulation, especially under online learning. And the knowledge they encode is locked behind proprietary walls.

Most large AI systems today are built around a single global objective function, centralized data aggregation, hidden alignment rules, and implicit averaging over moral and cultural differences. The result is predictable: minority viewpoints are quietly averaged away, the loudest groups shape the model at scale, a single model becomes an authority node that everyone depends on, and predictive advantage converts into economic or political dominance.

When this happens, wisdom stops being a shared good and becomes a strategic asset.

WikiOracle asks: **can we do better?**

---

## What Makes WikiOracle Different

### Truth as a first-class constraint

WikiOracle does not optimize for fluency and bolt on truthfulness as an afterthought. Truthfulness is the primary design constraint. Every claim traces back to explicit trust entries carrying certainty values on [-1, +1]. Reasoning chains and citations are inspectable. Grounded models are less prone to hallucination and capture, and claims can be contested, improved, or revised openly.

### You own your data

WikiOracle is local-first. Your conversation state, your trust entries, and your configuration live on your machine — not on a corporate server accumulating hidden central memory. The remote server is strictly stateless. You can export, merge, and port your sessions freely. Your data is yours.

### Democratic, not corporate

No single actor — company, state, foundation, or maintainer group — can silently become the epistemic root for everyone else. WikiOracle supports multiple points of view, each with its own trust map and standards of evidence. Where serious disagreement exists among credible sources, the system represents the dispute rather than smoothing it away. Minority viewpoints are preserved, not averaged into oblivion. And if governance ever fails these obligations, forking is a constitutional right.

### A network of trust, not a monolithic oracle

Instead of one model that claims to know everything, WikiOracle builds a network of trust. Authorities are pointers to external knowledge bases whose entries are imported with scaled certainty — we trust what they trust, to a degree. You choose who to trust and how much. Multiple LLM providers serve as "other minds" whose outputs become evidence, not unquestionable authority. Trust is transitive but attenuated, distributed but structured.

### Resistant to capture

A distributed truth network prevents appropriation. Anyone who tries to capture the network's knowledge must do so in a distributed way — which preserves the multicultural component — because monolithic capture would collapse consensus. Scraping a living network of trust yields only a static snapshot of a dynamic, evolving system. Open truth disrupts business models that depend on information asymmetry, extractive IP capture, and strategic opacity. That disruption is corrective, not destructive.

---

## How It Works

WikiOracle implements a **Hierarchical Mixture of Experts (HME)** architecture for evaluating claims:

- **Trust entries** carry certainty values in [-1, +1] using Kleene ternary/fuzzy logic — from certainly true (+1) through ignorance (0) to certainly false (-1).
- **Logical operators** (and/or/not/non under Strong Kleene semantics) compute derived certainty over the truth table.
- **Authorities** reference external knowledge bases, enabling transitive trust with certainty scaling.
- **Providers** are external LLMs used as expert consultants whose responses become sources with associated certainty.

The UI-selected provider acts as the "mastermind," synthesizing all evidence — facts, references, operator-derived certainty, authority imports, and provider consultations — into a final response.

See the [documentation](doc/README.md) for the full design.

---

## Current Prototype

The initial prototype is intentionally modest and low-cost:

- Extends Andrej Karpathy's [NanoChat](https://github.com/karpathy/nanochat) with Retrieval-Augmented Generation (RAG) over trusted corpora
- User-specified trust sets (configurable source whitelists)
- Online learning constrained by trust and grounding requirements
- Experiments in symbolic computation for grounding truth
- Training feasible on rented compute (~$100 scale)

## Longer-Term Direction

If WikiOracle proves viable at small scale, the architecture can be evaluated and extended to larger open models. The broader aim is to explore whether architectural commitments to truth can enable honest self-explanation, reduce the need for ad-hoc guardrails, and support AI systems that function as durable public goods.

---

## How to Contribute

Contributions of many kinds are welcome:
- ML research and implementation
- xAI, interpretability, and safety analysis
- Epistemology, philosophy of science, and governance critique
- Documentation, evaluation, and testing

---

## Getting Started

See the [Installation Guide](doc/Installation.md) for build, deploy, and runtime instructions.

Quickstart:

```bash
pip install -r requirements.txt
python bin/wikioracle.py
```

## Documentation

The full design and governance documentation lives in [`doc/`](doc/README.md):

| Document | Topic |
|---|---|
| [Constitution](doc/Constitution.md) | Non-negotiable invariants for truth and governance |
| [WhatIsTruth](doc/WhatIsTruth.md) | Plural truth, POVs, empathy, certainty semantics |
| [HierarchicalMixtureOfExperts](doc/HierarchicalMixtureOfExperts.md) | HME logic, distributed truth, conceptual spaces |
| [Authority](doc/Authority.md) | Transitive trust and authority import format |
| [Logic](doc/Logic.md) | Logical operators (and/or/not/non) under Strong Kleene semantics |
| [Non](doc/non.md) | Non-affirming negation: Buddhist motivation, fuzzy interpretation, expressive necessity |
| [FreedomEmpathyTruth](doc/FreedomEmpathyTruth.md) | Freedom, Empathy, and Truth — safety principles |
| [Architecture](doc/Architecture.md) | Local-first software architecture |
| [Security](doc/Security.md) | Security considerations |
| [Installation](doc/Installation.md) | Build, deploy, and runtime instructions |
