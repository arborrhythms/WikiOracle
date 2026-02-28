# WikiOracle Constitution
Updated: 2026-02-27

## Preamble

WikiOracle is an open-source architecture for truthfulness: a way to enlist the power of LLMs while preserving truth in the face of centralized, opaque "global corporate mental models" (including those embedded in proprietary systems).

WikiOracle is the Wikipedia model applied to LLMs:
- anyone can contribute claims, counterclaims, evaluations, and tests
- revision is expected and legible
- provenance and dispute are first-class, not edge-cases

Truthfulness is not a one-time achievement. It is an ongoing, open engineering and governance effort.

Even if the reasoning machine is large and unified, the data and trust it operates on must remain distributed and under individual control.
Epistemic ontributions are people-owned and revocable by the data providers.
Answers must be conditioned on what each user chooses to trust and believe to be true, not forced into a single impoverished consensus view of reality.

This constitution defines the non-negotiable invariants for WikiOracle's truth system and for changes to it. Implementation details and deeper theory live in the rest of the `doc/` directory.

## I. Core Commitments

1. **Truthfulness over fluency** Prefer grounded, falsifiable, uncertain, or incomplete answers over smooth, unsupported ones.
2. **Truth is not consensus** A single, averaged narrative is not the goal. The system must preserve real disagreement where it exists.
3. **Plural points of view** The system must support multiple Points of View (POVs), each with its own trust map and standards of evidence.
4. **Transparency by default** Claims, confidence, provenance, and update rationales must be inspectable and reproducible.
5. **Reversibility and accountability** High-impact changes must be attributable, testable, and reversible.
6. **Public benefit and anti-capture** No single actor (company, state, foundation, or maintainer group) should be able to silently become the epistemic root for everyone else.

## II. Truth Primitives (What the System Is Allowed to Believe)

WikiOracle's truth layer is composed of explicit, user-visible primitives stored in state:

1. **Trust entries**: atomic propositions, citations, or computed evidence. They carry a `certainty` in `[-1, +1]` (Kleene-style: believed, unknown, disbelieved).
2. **Authorities**: pointers to external knowledge bases (remote `llm.jsonl` files). Import is explicit and certainty is scaled (we trust what they trust, to a degree).
3. **Implications**: explicit "if...then..." relationships, treated as typed operators (material/strict/relevant), not a single overloaded connective.
4. **Providers**: external LLMs used as tools ("other minds") whose outputs become evidence, not unquestionable authority.

All truth computation must remain legible as operations over these primitives. If the system "knows" something, it should be possible to point to what it is grounded in.

## III. Plurality, Dispute, and Minority Preservation

1. **POV-conditioned conclusions.** When different POVs trust different sources, the system should be able to present conclusions conditioned on the selected POV/trust map.
2. **Overlaps are valuable.** When independent POVs converge on the same claim, that agreement should be surfaced explicitly as a robustness signal.
3. **Disputes stay visible.** Where serious disagreement exists among credible sources or POVs, the system must represent the dispute rather than smoothing it away.
4. **Minority protection.** Evidence-supported minority viewpoints must not be excluded solely by majority preference, institutional pressure, or convenience.

## IV. Independence From Any Single LLM Vendor

WikiOracle may use proprietary or open models as providers, but:

1. **No provider is the constitution.** Vendor policies, hidden prompts, and implicit "mental models" are not allowed to silently define truth for the system.
2. **Providers are evidence generators.** Provider outputs must be treated as contributions with provenance and certainty, contestable like any other entry.
3. **Structured independence.** When multiple providers are used, the architecture should preserve independence (for example, "secondary opinions" should not be conditioned on the same trust table that the "primary synthesis" sees).
4. **Replaceability is required.** The system must remain operable if any single provider becomes unavailable, hostile, or compromised.

## V. Authority Delegation Must Be Bounded and Secure

Authority entries exist to enable decentralized truth (a network of trust) without collapsing into a single global oracle.

1. **One hop only.** Importing an authority must not recursively fetch authorities of authorities.
2. **Certainty scaling.** Imported claims must be scaled by the authority's certainty (trust is transitive but attenuated).
3. **Namespaced IDs.** Imported entries must be namespaced to prevent collisions and to preserve provenance.
4. **Explicit source selection.** Users (or POV definitions) must explicitly choose which authorities to trust; there is no implicit global root.
5. **Operational safety.** Fetching and caching authorities must be rate-limited and size-limited, and restricted to safe URL schemes.

## VI. Change Control (Open Source Governance for Truth)

WikiOracle's constitution is enforced by process:

1. **Changes require evidence.** Any change that affects truth computation, ranking, grounding, or safety must include reproducible examples (tests, probes, counterexamples).
2. **Regression protection.** Changes must be evaluated against a shared regression suite to detect "ideological drift" and accidental truth degradation.
3. **Dissonance resolution as a release gate.** Major releases must stress-test for contradictions. If contradictions remain, they must be resolved or explicitly marked as uncertainty/boundaries.
4. **Public rationale.** High-impact changes must include a written rationale: what changed, why, what evidence supports it, and what known limitations remain.

## VII. Local-First Data and Auditability

1. **Client-owned state.** The default posture is local-first: user conversation state and trust tables live on the user's machine and are portable.
2. **No hidden central memory.** A shared hosted service must not quietly accumulate private state as a control point for truth.
3. **Provenance over secrecy.** When possible, store the "why" (citations, trust entries, authority sources) alongside the "what" (answers).

## VIII. Safety as Freedom, Love, and Wisdom

WikiOracle's truthfulness effort must not trade away human welfare or agency:

1. **Freedom (agency):** increase distributed agency, not centralized leverage.
2. **Love (relational integrity):** preserve dignity, minimize harm, and make uncertainty explicit.
3. **Wisdom (truth):** keep truth auditable and non-proprietary; do not convert epistemic advantage into coercive control.

## IX. Forking as a Constitutional Right

If governance fails these obligations, forking is a legitimate remedy. The project should be structured so that forks remain viable: data formats, tests, and truth primitives must be open and reproducible.

## X. Related Documents

This constitution is intentionally compact. For the rest of the system design:

- `WhatIsTruth.md`: plural truth, POVs, certainty semantics, and HME-style fan-out.
- `ArchitectureOfTruth.md`: HME logic, distributed truth vs consensus, conceptual spaces framing.
- `Authority.md`: transitive trust and authority import format/security.
- `Implication.md`: logical operators (and/or/not) and derived truth computation.
- `HowToEnsureSafety.md`: the Freedom/Love/Wisdom safety frame.
- `Security.md`: concrete security considerations for the local-first implementation.
- `Architecture.md`: the current software architecture (Flask shim + UI + `llm.jsonl`).
- `FutureWork.md`: roadmap items (trust network, sentence-level prediction, conceptual-space operations).
