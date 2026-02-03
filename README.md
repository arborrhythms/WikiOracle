# WikiOracle

**WikiOracle** is an open-source LLM (based on GPT or Apertus) which is truthful, capable of online learning, and which serves as a public good.

The project is motivated by a simple question:

> Can we design an LLM whose outputs are explicitly grounded in trusted sources, such that its conclusions are explainable and consistent, and whose conversations can serve as training data?

## Motivation
Right now LLMs are using our data (sourced from a billion people) to train its LLMs. The world is using LLMs to train its children. This raises privacy concerns (how do we prevent malicious commercial use?), concerns about the psychological health of our children (do we want them imprinting on a prediction-engine based on arbitrary internet content?), and good opportunities (can we create a public good similar to Wikipedia?).

So to enumerate several problems with existing LLMs:
- they frequently produce ungrounded or fabricated claims,
- they are difficult to explain or audit,
- they and are vulnerable to ideological or data-driven capture, especially under online learning.

## Core Idea

WikiOracle explores architectures where **truthfulness is a first-class design constraint**.

A central requirement is *explicit grounding*: 
users should be able to require that the model’s conclusions are derived *only* from a specified set of trusted sources (e.g. Wikipedia snapshots, peer-reviewed literature, curated datasets).

This approach directly supports:
- **Explainable AI (xAI):** reasoning chains and citations are inspectable.
- **Safety:** grounded models are less prone to hallucination and capture.
- **Public governance:** claims can be contested, improved, or revised openly.

## 2026 Prototype Goals

The initial goal is intentionally modest and low-cost.

We aim to extend Andrej Karpathy’s **NanoChat** (a minimal GPT-style implementation, https://github.com/karpathy/nanochat ) with:
- **Retrieval-Augmented Generation (RAG)** over trusted corpora,
- **User-specified trust sets** (configurable source whitelists),
- **Online learning**, constrained by trust and grounding requirements.
- Experiments in thought and symbolic computation that assist in grounding the truth of the outcome

Training and experimentation are feasible on rented compute (≈ $100 scale).

## Longer-Term Direction

If grounding-based truthfulness proves viable at small scale, the architecture can be evaluated and extended to larger open models (e.g. Apertus). The broader aim is to explore whether architectural commitments to truth can:
- enable honest self-explanation,
- reduce the need for ad-hoc guardrails,
- and support AI systems that function as durable public goods.

## How to Contribute

Contributions of many kinds are welcome:
- ML research and implementation
- xAI, interpretability, and safety analysis
- Epistemology, philosophy of science, and governance critique
- Documentation, evaluation, and testing
- Monetary contributions are discouraged; better to fund organizations that are figting for truthfulness and privacy (Internet Archive, EFF, Wikipedia, ...).

