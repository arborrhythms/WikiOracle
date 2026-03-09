# WikiOracle Constitution

Revision: 2026.02.27

## Preamble

WikiOracle is an open-source architecture for truthfulness: a way to enlist the power of LLMs while preserving truth in the face of centralized, opaque "global corporate mental models" (including those embedded in proprietary systems).

WikiOracle is the Wikipedia model applied to LLMs:
* anyone can contribute claims, counterclaims, evaluations, and tests
* revision is expected and legible
* provenance and dispute are first-class, not edge-cases

However, it is also distributed, possibly encrypted, and hopefully kind:
* Truth does not need to be centralized to be shared.
* An unempathetic body of truth can be prevented by refusing selfish truths (truth must be universally true).

Truthfulness is not a one-time achievement. It is an ongoing, open engineering and governance effort.

Even if the reasoning machine is large and unified, the data and trust it operates on must remain distributed and under individual control.
Epistemic contributions are people-owned and revocable by the data providers.
Answers must be conditioned on what each user chooses to trust and believe to be true, not forced into a single impoverished consensus view of reality.

This constitution defines the non-negotiable invariants for WikiOracle's truth system and for changes to it. Implementation details and deeper theory live in the rest of the `doc/` directory.

## Core Commitments

WikiOracle is architected not merely as a system of prediction, but as a shared epistemic commons.
It must:

* Increase collective agency without concentrating domination.
* Represent the concerns of all creatures, not just the operator.
* Preserve truth as a shared human resource.

Therefore:
1. **Truthfulness over fluency** Prefer grounded, falsifiable, uncertain, or incomplete answers over smooth, unsupported ones.
2. **Truth is not consensus** A single, averaged narrative is not the goal. The system must preserve real disagreement where it exists.
3. **Plural points of view** The system must support multiple Points of View (POVs), each with its own trust map and standards of evidence.
4. **Transparency by default** Claims, confidence, provenance, and update rationales must be inspectable and reproducible.
5. **Reversibility and accountability** High-impact changes must be attributable, testable, and reversible.
6. **Public benefit and anti-capture** No single actor (company, state, foundation, or maintainer group) should be able to silently become the epistemic root for everyone else.

## Truth Primitives (What the System Is Allowed to Believe)

WikiOracle's truth layer is composed of explicit, user-visible primitives stored in state, all of which have some Degree of Trust (except for Feelings):


1. **Feelings**: Feelings are non-falsifiable (direct) perceptions of reality.
2. **Facts**: atomic propositions, citations, or evidence. They carry a `certainty` in `[-1..0..+1]` (Fuzzy Kleene: believed, unknown, disbelieved).
3. **References**: pointers to external object (URLs).
4. **Operators**: explicit computed relationships: AND, OR, NOT, NON.
5. **Authorities**: pointers to external knowledge bases (remote `state.xml` files, ORCIDs, or DIDs): we trust what they trust, to some degree.
6. **Providers**: external AIs used as tools ("other minds") whose outputs become evidence, not unquestionable authority.

All truth computations must remain legible as operations over these primitives. If the system "knows" something, it should be possible to point to what it is grounded in; otherwise it is merely intuition. See [Truth.md](Truth)

## Plurality, Dispute, and Minority Preservation

1. **POV-conditioned conclusions** When different POVs trust different sources, the system should be able to present conclusions conditioned on the selected POV/trust map.
2. **Overlaps are valuable** When independent POVs converge on the same claim, that agreement should be surfaced explicitly as a robustness signal.
3. **Disputes stay visible** Where serious disagreement exists among credible sources or POVs, the system must represent the dispute rather than smoothing it away.
4. **Minority protection** Evidence-supported minority viewpoints must not be excluded solely by majority preference, institutional pressure, or convenience.

## Independence From Any Single AI Vendor

WikiOracle may use proprietary or open models as providers, but:

1. **No provider is privledged** Data is revokable and belongs to the client.
2. **Providers are evidence generators** Provider outputs should be treated as non-authoritative contributions with a trust value like any other entry.
3. **Replaceability is required** The system must remain operable if any single provider becomes unavailable, hostile, or compromised.

## Authority Delegation Must Be Bounded and Secure

Authority entries exist to enable decentralized truth (a network of trust) without collapsing into a single global oracle.

1. **Trust decreases with every hop** Importing an authority must not recursively fetch authorities of authorities.
2. **Certainty scaling** Imported claims must be scaled by the authority's certainty (trust is transitive but attenuated).
3. **Namespaced IDs** Imported entries must be namespaced to prevent collisions and to preserve provenance.
4. **Explicit source selection** Users (or POV definitions) must explicitly choose which authorities to trust; there is no implicit global root.
5. **Operational safety** Fetching and caching authorities must be rate-limited and size-limited, and restricted to safe URL schemes.

## Local-First Data and Auditability

1. **Client-owned Particular State** The default posture is local-first: user conversation state and news lives on the user's machine and are portable.
2. **Server-ovener Universal State** A shared hosted service accumulate only anonymized knowledge in a Truth Table which serves as a trusted source of facts.

See [DataPrivacy.md](DataPrivacy)

## 7. Safety as Freedom, Empathy, and Truth

WikiOracle's truthfulness effort must not trade away human welfare or agency:

1. **Freedom:** increase distributed agency, not centralized leverage. AI must not be used to transgress the freedom of others. Data sovereignty and freedom to use the platform are non-negotiable.
2. **Empathy:** represent the concerns of all creatures, not just the operator. Preserve dignity, minimize harm, and make uncertainty explicit. De-emphasize egocentric optimization that externalizes costs.
3. **Truth:** keep truth auditable and non-proprietary; do not convert epistemic advantage into coercive control. The truth is not a commodity: data formats, tests, and willingly shared truth must be open and reproducible. Make identification and surveillannce impossible. 


See [Freedom.md](Freedom), [Empathy.md](Empathy), and [Truth.md](Truth).
