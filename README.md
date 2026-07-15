# WikiOracle
Revision: 2026.07.15

**An open-source architecture for truthful AI.**

WikiOracle is a truthful, explainable LLM system designed as a public good -- the Wikipedia model applied to artificial intelligence.

## The Problem

For-profit corporations are using our data -- sourced from billions of people -- to train models that are teaching our children. Those models hallucinate, cannot reliably explain themselves, and are vulnerable to ideological capture and data-driven manipulation, especially under online learning. The knowledge they encode is then locked behind proprietary walls.

Most large AI systems are built around a single global objective, centralized data aggregation, hidden alignment rules, and implicit averaging over moral and cultural differences. Minority viewpoints are quietly averaged away, the loudest groups shape the model at scale, and a single model becomes an authority node on which everyone depends. When predictive advantage converts into economic or political dominance, wisdom stops being a shared good and becomes a strategic asset.

## What Makes WikiOracle Different

| Commitment | Architectural expression | Practical effect |
|---|---|---|
| **Truth** | Claims are explicit TruthSet entries with a Degree of Truth (DoT) on [-1, +1]; logic and sources remain inspectable. | Claims can be contested, revised, and grounded instead of being accepted because they sound fluent. |
| **Data sovereignty** | `state.xml` holds identity, conversations, and truth; `config.xml` separates server policy from client preferences. Stateful and stateless runtime modes are both supported. | A user can export, merge, and move a session without depending on hidden central memory. |
| **Secure sharing** | Dropbox backup stores AES-encrypted ZIP bundles. A shared state can be represented as an `<authority>` reference and encoded as a QR code. | Another client can import the shared state and assign its own trust weight without receiving the sender's config or provider keys. |
| **Democracy** | Each participant maintains an independent trust map; disagreement among credible sources is represented rather than silently averaged away. Forking is a constitutional right. | No company, state, foundation, or maintainer group becomes the universal epistemic root. |
| **Distribution** | Authorities contribute remote TruthSets with scaled certainty, while provider entries act as expert consultants in a Hierarchical Mixture of Experts (HME). | Trust is transitive but attenuated, and provider output remains evidence rather than unquestionable authority. |

## Current Prototype

| Capability | Current implementation |
|---|---|
| Conversation model | Branching conversation tree with diamond-shaped merges for provider voting |
| Truth model | Facts, feelings, references, logic, authorities, and providers in typed XML |
| Reasoning | Strong Kleene `and`, `or`, `not`, and `non` operators over DoT values |
| Provider layer | Runtime-selectable WikiOracle/NanoChat, BasicModel, OpenAI, Anthropic, Gemini, Grok, and OpenRouter adapters |
| Learning | Optional online training constrained by DoT, warmup, clipping, and checkpoint anchoring |
| Storage | Local XML plus optional AES-encrypted Dropbox backup and authority sharing |
| Research scale | Local CPU/MPS workflows and rentable GPU workflows intended for comparatively low-cost experiments |

## Longer-Term Direction

If WikiOracle proves viable at small scale, the architecture can be evaluated with larger open models. The broader aim is to test whether architectural commitments to truth can enable honest self-explanation, reduce reliance on ad-hoc guardrails, and support AI systems that function as durable public goods. Current engineering priorities are tracked in [`todo.md`](todo.md).

## How to Contribute

| Area | Examples |
|---|---|
| ML systems | Model integration, training, evaluation, and performance work |
| Safety and interpretability | Explainability, adversarial analysis, and capture resistance |
| Epistemology and governance | Philosophy of science, plural truth, and constitutional critique |
| Product quality | Documentation, UI, accessibility, testing, and deployment |

## Getting Started

See the [Installation Guide](doc/Installation.md) for prerequisites, local services, training, and deployment.

```bash
git submodule update --init --recursive
make install
make nano_restart NANO_MODEL_TAG=d26 NANO_DEVICE_TYPE=cpu NANO_DTYPE=float32
make wo_restart
make nano_status wo_status
```

Then open `https://127.0.0.1:8888` and accept the local development certificate.

## Documentation

The assembled manual is [WikiOracle.pdf](WikiOracle.pdf). Its WikiOracle server and client chapters live in `./doc`:

| File | Topic |
|---|---|
| [WikiOracle.md](doc/WikiOracle.md) | Design and architecture overview |
| [Constitution.md](doc/Constitution.md) | Non-negotiable invariants for truth and governance |
| [Installation.md](doc/Installation.md) | Build, deploy, and runtime instructions |
| [Truth.md](doc/Truth.md) | Plural truth, points of view, empathy, and certainty semantics |
| [Ethics.md](doc/Ethics.md) | Truth symmetry, entanglement policy, and ethical reasoning |
| [PrivacyAndSecurity.md](doc/PrivacyAndSecurity.md) | Data ownership, credentials, transport, storage, and browser security |
| [Freedom.md](doc/Freedom.md) | Freedom, entanglement policy, and worldline-capture constraints |
| [Voting.md](doc/Voting.md) | HME provider voting and diamond topology |
| [Logic.md](doc/Logic.md) | Strong Kleene operators and derived truth |
| [Training.md](doc/Training.md) | Sensation preprocessing, DegreeOfTruth, and online learning |
| [Implementation.md](doc/Implementation.md) | Components, endpoints, and request flow |
| [Config.md](doc/Config.md) | Canonical configuration format and environment variables |
| [State.md](doc/State.md) | State grammar, conversation DAG, truth elements, and serialization |
| [UserInterface.md](doc/UserInterface.md) | Client behavior, settings, navigation, and canonical strings |
| [ProposedLicense.md](doc/ProposedLicense.md) | Proposed layered licensing architecture |

BasicModel documentation lives in `./basicmodel/doc`:

| File | Topic |
|---|---|
| [Architecture.md](basicmodel/doc/Architecture.md) | Bidirectional model pipeline and decomposition |
| [BasicModel.md](basicmodel/doc/BasicModel.md) | Cognitive model theory and symmetric perception |
| [Componentization.md](basicmodel/doc/Componentization.md) | Model component boundaries |
| [Ergodic.md](basicmodel/doc/Ergodic.md) | Ergodic exploration and training dynamics |
| [Language.md](basicmodel/doc/Language.md) | Language and grammar implementation |
| [Lexicon.md](basicmodel/doc/Lexicon.md) | Lexical representation |
| [Logic.md](basicmodel/doc/Logic.md) | Subsymbolic and symbolic operators |
| [MachineMinds.md](basicmodel/doc/MachineMinds.md) | Invertibility, uncertainty, and machine minds |
| [Mereology.md](basicmodel/doc/Mereology.md) | Part-whole representation |
| [Params.md](basicmodel/doc/Params.md) | XML model parameters |
| [Reasoning.md](basicmodel/doc/Reasoning.md) | Reasoning surfaces and TruthLoss |
| [Spaces.md](basicmodel/doc/Spaces.md) | Model-space specifications |
| [STM.md](basicmodel/doc/STM.md) | Short-term memory |
| [SymbolFirewall.md](basicmodel/doc/SymbolFirewall.md) | Symbolic boundary and safety contract |
| [Training.md](basicmodel/doc/Training.md) | BasicModel training pipeline |

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
| [BF_ICDCS_2022.pdf](doc/research/BF_ICDCS_2022.pdf) | Conference paper PDF |
