# WikiOracle Docs
Updated: 2026-02-28

This directory is the design, governance, and research documentation for WikiOracle.

Recommended reading order:
1. `Constitution.md` (project invariants)
2. `WhatIsTruth.md` (plural truth, POVs, and certainty semantics)
3. `HierarchicalMixtureOfExperts.md` (HME logic, distributed truth vs consensus, conceptual spaces)
4. `Authority.md` (transitive trust and the authority import format)
5. `Implication.md` (logical operators: and/or/not under Strong Kleene semantics)
6. `Voting.md` (voting protocol: dom steering, sub fan-out, cycle prevention, truth-only output)
7. `FreedomEmpathyTruth.md` (Freedom, Empathy, and Truth — safety principles)
8. `Architecture.md` (current local-first software architecture)
9. `Security.md` (concrete security considerations)
10. `Installation.md` (build, deploy, and runtime instructions)
11. `FutureWork.md` (roadmap)
12. `WikiOracle.md` (consistency-first framing; document starts with "OpenMind")

## Core Documents (doc/)

- [`README.md`](./README.md): this index.
- [`Constitution.md`](./Constitution.md): the non-negotiable invariants for WikiOracle's truth system and governance.
- [`WhatIsTruth.md`](./WhatIsTruth.md): plural truth model, POVs, empathy as procedural constraint, HME fan-out, Kleene-style certainty.
- [`HierarchicalMixtureOfExperts.md`](./HierarchicalMixtureOfExperts.md): HME logic, Wikipedia-inspired distributed truth framing, conceptual spaces model.
- [`Authority.md`](./Authority.md): authority blocks (`<authority>`), transitive trust, certainty scaling, namespacing, and fetch/security constraints.
- [`Implication.md`](./Implication.md): logical operators (and/or/not); Strong Kleene evaluation; derived truth engine.
- [`Voting.md`](./Voting.md): voting protocol — dom steering, sub fan-out, cycle prevention, `<feeling>` as truth type, truth-only output.
- [`FreedomEmpathyTruth.md`](./FreedomEmpathyTruth.md): Freedom, Empathy, and Truth — safety principles and architectural commitments.
- [`Security.md`](./Security.md): local-first security considerations (keys, CSP/XSS, CORS, filesystem, scraping/capture).
- [`Architecture.md`](./Architecture.md): implementation architecture (Flask shim + UI + `llm.jsonl` state model).
- [`Installation.md`](./Installation.md): build, deploy, and runtime instructions.
- [`FutureWork.md`](./FutureWork.md): future directions (trust network, sentence-level prediction, conceptual-space operations).
- [`WikiOracle.md`](./WikiOracle.md): a consistency-first design note (historically labeled "OpenMind" in the text).

Build, deploy, and runtime details are in [`Installation.md`](./Installation.md).

## Research Notes (doc/research/)

- [`research/CONTENTS.md`](./research/CONTENTS.md): research index and suggested reading order.
- [`research/Huang2023_HallucinationSurvey.md`](./research/Huang2023_HallucinationSurvey.md): hallucination landscape and taxonomy.
- [`research/Alansari2025_HallucinationSurvey.md`](./research/Alansari2025_HallucinationSurvey.md): hallucination survey (comprehensive).
- [`research/Wang2023_FactualitySurvey.md`](./research/Wang2023_FactualitySurvey.md): factuality in LLMs survey.
- [`research/Wang2024_FactualitySurvey.md`](./research/Wang2024_FactualitySurvey.md): updated factuality survey.
- [`research/Gao2023_RAGSurvey.md`](./research/Gao2023_RAGSurvey.md): retrieval-augmented generation survey.
- [`research/Dhuliawala2023_CoVe.md`](./research/Dhuliawala2023_CoVe.md): Chain-of-Verification methods.
- [`research/Ghafouri2024_EpistemicIntegrity.md`](./research/Ghafouri2024_EpistemicIntegrity.md): epistemic integrity, calibration, assertiveness.
- [`research/Li2024_HonestySurvey.md`](./research/Li2024_HonestySurvey.md): honesty in LLMs survey.
- [`research/Li2024_KnowledgeBoundary.md`](./research/Li2024_KnowledgeBoundary.md): knowledge boundaries and limitations survey.
- [`research/Concept_Note_AlecRogers.md`](./research/Concept_Note_AlecRogers.md): project-specific concept note.
- [`research/Apertus_Small_Compute_Request.md`](./research/Apertus_Small_Compute_Request.md): small-compute access request draft.
- [`research/1711.00937.md`](./research/1711.00937.md): converted paper (Neural Discrete Representation Learning).
- [`research/2601.15714.md`](./research/2601.15714.md): converted paper (Even GPT-5.2 Can't Count to Five).
- [`research/2602.03442.md`](./research/2602.03442.md): converted paper (A-RAG: Agentic Retrieval-Augmented Generation).
