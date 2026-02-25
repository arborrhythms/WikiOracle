## HME Logic

The WikiOracle logic is similar to a hierarchical mixture of experts, where trust is based on truth values with associated certainty values in the range [-1, 1]. Those propositions can be static facts, references to other bodies of knowledge, or computed by other minds that are trusted and/or distrusted. Finally, truth is computed by implication (conditional logic) over that body of propositions; see [Implication.md](./Implication.md).

## Distributed Truth vs Consensus: 

WikiOracle attempts to achieve a distributed truth, and shares much of the design philosophy of Wikipedia:

- **Radical Accessibility** — Wikipedia is freely accessible worldwide and allows anyone to both read and contribute without institutional gatekeeping.

- **Transparent Revision History** — Every edit is publicly logged and reversible, creating a fully auditable record of how knowledge evolves.

- **Citation Norms** — Content must be verifiable through reliable sources, prioritizing documented evidence over personal assertion.

- **Decentralized Governance** — Editorial oversight and dispute resolution are handled by a distributed volunteer community operating under shared policies.

- **Structured Neutrality (NPOV)** — Articles are required to represent significant viewpoints proportionally, aiming for balanced presentation rather than advocacy.

- **Scale and Coverage** — The platform provides massive topical breadth across millions of interlinked articles forming a global knowledge graph.

- **Anti-Monetization Bias** — As a nonprofit project under the Wikimedia Foundation, it operates without advertising-driven content incentives.

- **Self-Correcting Dynamics** — Errors and vandalism can be rapidly identified and corrected through continuous community monitoring.

- **Cultural Legitimacy** — Wikipedia functions as a widely accepted public reference layer and common starting point for research.

- **Open Knowledge Model** — It demonstrates that large-scale, decentralized, norm-governed collaboration can produce a coherent and durable knowledge commons.

## Conceptual Spaces

The architecture of WikiOracle is designed as a conceptual space, in the sense of Gardenfors. Conceptual spaces are similarity spaces, where similar concepts occupy regions of space close to one another. As spaces also of truth, they are amenable to logical calculation. This is similar to existing LLM architecture: Embedding spaces encode meaningful vectors in the same way, and separating hypersurfaces (the neurons of the network) categorize that space in numerous ways, allowing calculation on that space. Summing over multiplicative connections provides the basic Boolean architectural primitives {or, and} in a continuous and learnable way, which allows logical computation on that space. However, it allows such voluminous computation that the syntax and semantics are dense compared to the English language. The trust computed by the contextual structure provided here is explicit, subject to interpretation, and much higher level. The values of certainty propagate, giving not only a next-token prediction but a measure of confidence in the computed answer.
