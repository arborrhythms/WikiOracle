# WikiOracle Constitution

Revision: 2026.07.15

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

| Principle                          | Implication                                                                                                |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Truthfulness over fluency          | Prefer grounded, falsifiable, uncertain, or incomplete answers over smooth, unsupported ones.              |
| Truth is not consensus             | A single, averaged narrative is not the goal. The system must preserve real disagreement where it exists.  |
| Plural points of view              | Support multiple POVs, each with its own trust map and standards of evidence.                              |
| Transparency by default            | Claims, confidence, provenance, and update rationales must be inspectable and reproducible.                |
| Reversibility and accountability   | High-impact changes must be attributable, testable, and reversible.                                        |
| Public benefit and anti-capture    | No single actor (company, state, foundation, or maintainer group) becomes the epistemic root for others.   |

## Truth Primitives (What the System Is Allowed to Believe)

WikiOracle's truth layer is composed of explicit, user-visible primitives stored in state. All carry a Degree of Trust on $[-1, +1]$ except feelings, which are orthogonal to the truth lattice.

| Primitive       | Trust value      | Source                              | Role in reasoning                                                            |
| --------------- | ---------------- | ----------------------------------- | ---------------------------------------------------------------------------- |
| **Feeling**     | none (orthogonal)| user / provider                     | Non-falsifiable direct perception. Influences evaluation; never trains.      |
| **Fact**        | $[-1, +1]$       | user / provider / authority         | Atomic proposition with Fuzzy Kleene certainty (believed / unknown / disbelieved). |
| **Reference**   | $[-1, +1]$       | user                                | Pointer to an external object (URL).                                         |
| **Operator**    | derived          | user / engine                       | Explicit computed relationship: `and`, `or`, `not`, `non` (Strong Kleene).   |
| **Authority**   | $[-1, +1]$       | user                                | Pointer to a remote knowledge base (`state.xml`, ORCID, DID); transitive trust, attenuated. |
| **Provider**    | $[-1, +1]$       | user                                | External AI used as a tool ("other mind"); its outputs become evidence, not authority. |

All truth computations must remain legible as operations over these primitives. If the system "knows" something, it should be possible to point to what it is grounded in; otherwise it is merely intuition. See [Truth.md](./Truth.md).

## Plurality, Dispute, and Minority Preservation

| Rule                          | Mechanism                                                                                              |
| ----------------------------- | ------------------------------------------------------------------------------------------------------ |
| POV-conditioned conclusions   | Present conclusions conditioned on the selected POV / trust map.                                       |
| Overlaps are valuable         | When independent POVs converge on a claim, surface the agreement explicitly as a robustness signal.    |
| Disputes stay visible         | Where serious disagreement exists, represent the dispute rather than smoothing it away.                |
| Minority protection           | Evidence-supported minority viewpoints must not be excluded by majority preference or convenience.     |

## Independence From Any Single AI Vendor

WikiOracle may use proprietary or open models as providers, but:

| Rule                          | What it guarantees                                                                                     |
| ----------------------------- | ------------------------------------------------------------------------------------------------------ |
| No provider is privileged     | Data is revocable and belongs to the client.                                                           |
| Providers are evidence sources| Provider outputs are non-authoritative contributions with a trust value like any other entry.          |
| Replaceability is required    | The system remains operable if any single provider becomes unavailable, hostile, or compromised.       |

## Authority Delegation Must Be Bounded and Secure

Authority entries exist to enable decentralized truth (a network of trust) without collapsing into a single global oracle.

| Constraint                          | Detail                                                                                            |
| ----------------------------------- | ------------------------------------------------------------------------------------------------- |
| Trust decreases with every hop      | Importing an authority must not recursively fetch authorities of authorities.                     |
| Certainty scaling                   | Imported claims are scaled by the authority's certainty (trust is transitive but attenuated).     |
| Namespaced IDs                      | Imported entries are namespaced to prevent collisions and preserve provenance.                    |
| Explicit source selection           | Users (or POV definitions) explicitly choose which authorities to trust; no implicit global root. |
| Operational safety                  | Fetching and caching is rate-limited, size-limited, and restricted to safe URL schemes.           |

## Local-First Data and Auditability

| Tier                          | Posture                                                                                            |
| ----------------------------- | -------------------------------------------------------------------------------------------------- |
| Client-owned Particular State | Default local-first: user conversation state and news live on the user's machine and are portable. |
| Server-owned Universal State  | A shared service accumulates only anonymized knowledge as a TruthSet of trusted facts.             |

See [PrivacyAndSecurity.md](./PrivacyAndSecurity.md).

## Safety as Freedom, Empathy, and Truth

WikiOracle's truthfulness effort must not trade away human welfare or agency:

| Pillar    | Commitment                                                                                                                                                                                |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Freedom   | Increase distributed agency, not centralized leverage. AI must not be used to transgress the freedom of others. Data sovereignty is non-negotiable.                                       |
| Empathy   | Represent the concerns of all creatures, not just the operator. Preserve dignity, minimize harm, and make uncertainty explicit. De-emphasize egocentric optimization that externalizes costs. |
| Truth     | Keep truth auditable and non-proprietary; do not convert epistemic advantage into coercive control. Open data formats, open tests, willingly shared truth. Make surveillance impossible.  |


See [Freedom.md](./Freedom.md), [Ethics.md](./Ethics.md), and [Truth.md](./Truth.md).
