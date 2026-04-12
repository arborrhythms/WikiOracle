# WikiOracle
Revision: 2026.02.27

**An open-source architecture for truthful AI.**

WikiOracle is a truthful, explainable LLM system designed as a public good — the Wikipedia model applied to artificial intelligence.

## The Problem

For-profit corporations are using our data — sourced from billions of people — to train models that are teaching our children. Those models hallucinate. They can't explain themselves. They are vulnerable to ideological capture and data-driven manipulation, especially under online learning. And the knowledge they encode is locked behind proprietary walls.

Most large AI systems today are built around a single global objective function, centralized data aggregation, hidden alignment rules, and implicit averaging over moral and cultural differences. The result is predictable: minority viewpoints are quietly averaged away, the loudest groups shape the model at scale, a single model becomes an authority node that everyone depends on, and predictive advantage converts into economic or political dominance.

When this happens, wisdom stops being a shared good and becomes a strategic asset.

## What Makes WikiOracle Different

### Truth

WikiOracle does not optimize for fluency and bolt on truthfulness as an afterthought. Truthfulness is the primary design constraint. Every claim traces back to explicit trust entries carrying certainty values on [-1, +1]. Reasoning chains and citations are inspectable. Grounded models are less prone to hallucination and capture, and claims can be contested, improved, or revised openly.

### Data Soverignty

WikiOracle is local-first. Your conversation state, your trust entries, and your configuration live on your machine — not on a corporate server accumulating hidden central memory. The remote server is strictly stateless. You can export, merge, and port your sessions freely. Your data is yours.

### Democracy

No single actor — company, state, foundation, or maintainer group — can silently become the epistemic root for everyone else. WikiOracle supports multiple points of view, each with its own trust map and standards of evidence. Where serious disagreement exists among credible sources, the system represents the dispute rather than smoothing it away. Minority viewpoints are preserved, not averaged into oblivion. And if governance ever fails these obligations, forking is a constitutional right.

### Distribution

Instead of one model that claims to know everything, WikiOracle builds a network of trust. Authorities are pointers to external knowledge bases whose entries are imported with scaled certainty — we trust what they trust, to a degree. You choose who to trust and how much. Multiple LLM providers serve as "other minds" whose outputs become evidence, not unquestionable authority. Trust is transitive but attenuated, distributed but structured. A distributed truth network prevents appropriation. Open truth does disrupt business models that depend on information asymmetry, extractive IP capture, and strategic opacity, but that disruption is corrective.

## Current Prototype

The initial prototype is intentionally modest and low-cost:

* Hierarchical, multi-LLM architecture for runtime-configurable Hierarchical Mixture of Experts.
* User-specified truth sets (consisting of facts, feelings, references, operators, authorities, and providers)
* Online learning constrained by trust and epistemic grounding
* Extends [NanoChat](https://github.com/karpathy/nanochat) with Truth Sets using Retrieval-Augmented Generation
* Allows feasible experiments in LLM architectures on rented compute (~$100 scale)

## Longer-Term Direction

If WikiOracle proves viable at small scale, the architecture can be evaluated and extended to larger open models. The broader aim of WikiOracle is to explore whether architectural commitments to truth can enable honest self-explanation, reduce the need for ad-hoc guardrails, and support AI systems that function as durable public goods. See [FutureWork.md](doc/FutureWork.md)

## How to Contribute

Contributions of many kinds are welcome:
* ML research and implementation
* xAI, interpretability, and safety analysis
* Epistemology, philosophy of science, and governance critique
* Documentation, evaluation, and testing

## Getting Started

See the [Installation Guide](doc/Installation.md) for build, deploy, and runtime instructions.

Quickstart:

```bash
pip install -r requirements.txt
python bin/wikioracle.py
```

## Documentation

Server and client documentation lives in `./doc`:

| File | Topic |
|---|---|
| [Config.md](doc/Config.md) | Configuration format, settings reference, and environment variables |
| [Constitution.md](doc/Constitution.md) | Non-negotiable invariants for WikiOracle truth and governance |
| [Ethics.md](doc/Ethics.md) | Ethical AI through truth architecture, entanglement policy, and truth development |
| [Freedom.md](doc/Freedom.md) | Freedom, entanglement policy, and worldline-capture constraints |
| [FutureWork.md](doc/FutureWork.md) | Server roadmap and future directions |
| [Voting.md](doc/Voting.md) | Hierarchical Mixture of Experts architecture and voting model |
| [Implementation.md](doc/Implementation.md) | Implementation notes |
| [Installation.md](doc/Installation.md) | Build, deploy, and runtime instructions |
| [Logic.md](doc/Logic.md) | Logical operators, Strong Kleene evaluation, and derived truth |
| [PrivacyAndSecurity.md](doc/PrivacyAndSecurity.md) | Privacy and security considerations |
| [ProposedLicense.md](doc/ProposedLicense.md) | Proposed licensing architecture |
| [Socrates.pdf](doc/Socrates.pdf) | PDF reference document |
| [State.md](doc/State.md) | State file format, conversation tree, truth table, and serialization |
| [Training.md](doc/Training.md) | Training pipeline, DegreeOfTruth, and NanoChat integration |
| [Truth.md](doc/Truth.md) | Plural truth, POVs, empathy, and certainty semantics |
| [UserInterface.md](doc/UserInterface.md) | Canonical client UI strings and labels |
| [WikiOracle.md](doc/WikiOracle.md) | WikiOracle design overview |
| [WikiOracle.pdf](doc/WikiOracle.pdf) | PDF version of the WikiOracle overview |

BasicModel AI documentation lives in `./basicmodel/doc`:

| File | Topic |
|---|---|
| [Architecture.md](basicmodel/doc/Architecture.md) | Six-space bidirectional pipeline, invertible layers, LDU |
| [BasicModel.md](basicmodel/doc/BasicModel.md) | Four-space cognitive model theory, symmetric perception |
| [BuddhistParallels.md](basicmodel/doc/BuddhistParallels.md) | Buddhist epistemology parallels, pramana theory, tetralemma |
| [Ergodic.md](basicmodel/doc/Ergodic.md) | Ergodic exploration, gradient energy sensor, simulated annealing |
| [Grammar.md](basicmodel/doc/Grammar.md) | Formal grammar mapped to neural architecture spaces |
| [Language.md](basicmodel/doc/Language.md) | SyntacticLayer, CNF grammar rules, method implementations, thought-free mode |
| [Logic.md](basicmodel/doc/Logic.md) | Subsymbolic/symbolic operators, truth fields, luminosity |
| [MachineMinds.md](basicmodel/doc/MachineMinds.md) | Weight ergodicity, network invertibility, output certainty |
| [Params.md](basicmodel/doc/Params.md) | XML configuration schema for all model hyperparameters |
| [Reasoning.md](basicmodel/doc/Reasoning.md) | Reasoning methods, TruthLoss, partitioned symbolic space, contemplative awareness |
| [Spaces.md](basicmodel/doc/Spaces.md) | InputSpace through OutputSpace specifications |
| [Training.md](basicmodel/doc/Training.md) | Two-phase training: embedding pretraining + network training |

## Research Materials

Supporting papers live in [`doc/research/`](doc/research):

| File | Type |
|---|---|
| [1711.00937v2.pdf](doc/research/1711.00937v2.pdf) | arXiv paper PDF |
| [2309.11495v2.pdf](doc/research/2309.11495v2.pdf) | arXiv paper PDF |
| [2311.05232v2.pdf](doc/research/2311.05232v2.pdf) | arXiv paper PDF |
| [2312.10997v5.pdf](doc/research/2312.10997v5.pdf) | arXiv paper PDF |
| [2403.05156.pdf](doc/research/2403.05156.pdf) | arXiv paper PDF |
| [2409.18786v1.pdf](doc/research/2409.18786v1.pdf) | arXiv paper PDF |
| [2411.06528v2.pdf](doc/research/2411.06528v2.pdf) | arXiv paper PDF |
| [2412.12472v2.pdf](doc/research/2412.12472v2.pdf) | arXiv paper PDF |
| [2503.22759v1.pdf](doc/research/2503.22759v1.pdf) | arXiv paper PDF |
| [2510.06265v2.pdf](doc/research/2510.06265v2.pdf) | arXiv paper PDF |
| [2511.03529v1.pdf](doc/research/2511.03529v1.pdf) | arXiv paper PDF |
| [2601.11199v1.pdf](doc/research/2601.11199v1.pdf) | arXiv paper PDF |
| [BF_ICDCS_2022.pdf](doc/research/BF_ICDCS_2022.pdf) | conference paper PDF |
