# Future Work

## OAuth
* Look into something better than storing API Keys in cleartest on the client

## Point-Free Spacetime
* The `<place>` and `<time>` attributes of facts and feelings define a larger or smaller spatiotemporal subspace, not an infinite universal or infinitesimal particular extent.  The universal/particular distinction is a gradient of spatiotemporal extent (see doc/Entanglement.md), and every proposition occupies a subspace that is larger or smaller, never infinite or infinitesimal.
* Allow ranges in `<place>` and `<time>` fields (e.g. `<time>2020..2026</time>`, `<place>Western Europe</place>`) and treat bare points as implicit small ranges, consistent with point-free topology.
* Investigate mereological / point-free representations of spatiotemporal extent so that `is_news_fact()` / `is_knowledge_fact()` can operate on extent size rather than presence/absence of child elements — a proposition with a broad temporal range behaves more like knowledge even if it carries a `<time>`.

## MCP Integration
* Expose WikiOracle as an MCP server: wrap `/chat`, truth management, and state merge as MCP tools; expose state and trust graph as MCP resources.
* Use MCP servers as authority-adjacent inputs: convert MCP resource/tool outputs into `<reference>`/`<fact>` entries with explicit certainty and scope, replacing per-source custom integrations.
* Multi-channel front-end via OpenClaw: route messages from Slack/Discord/Telegram to WikiOracle's `/chat` endpoint, preserving local-first truth ownership.

## Sentence-Level Prediction
* Change the next-step prediction model to a syntactically structured derivation of sentence meaning, so that token prediction becomes prediction of the sentence (as a token), of the NP+VP (as two tokens), ... until the full sentence has been specified. This would take the same number of production steps as a current LLM, but the iterative refinement of the next-sentence production is conceptually much different, and closer to human reasoning and refinement where there is a core truth (S) and spatial NP and temporal VP which are successively refined by adjectives and adverbs that scope the conceptual space of that kernel sentence.
* A training and testing dataset for the network consisting of truth statements and implications with associated truth values.

## Mereological Operations on Conceptual Space
* Make improvements to NanoChat that allow it to compute truth within the geometric/conceptual space of the network, giving meaning to logical operations within that space (so use mereological operations to implement the ternary logic that is currently operating over the trust entries of the HME architecture in the current design). This means replacing AND with union, OR with intersection, IMPLICATION with parthood. See [Socrates.pdf](Socrates.pdf) for a quick sketch of deriving mereological (Venn-diagram-like) logic from entailment.
* The architecture of WikiOracle is designed as a conceptual space, in the sense of Gardenfors. Conceptual spaces are similarity spaces, where similar concepts occupy regions of space close to one another. As spaces also of truth, they are amenable to logical calculation. This is similar to existing LLM architecture: Embedding spaces encode meaningful vectors in the same way, and separating hypersurfaces (the neurons of the network) categorize that space in numerous ways, allowing calculation on that space. Summing over multiplicative connections provides the basic Boolean architectural primitives {or, and} in a continuous and learnable way, which allows logical computation on that space. However, it allows such voluminous computation that the syntax and semantics are dense compared to the English language. The trust computed by the contextual structure provided here is explicit, subject to interpretation, and much higher level. The values of certainty propagate, giving not only a next-token prediction but a measure of confidence in the computed answer.
* See [`Socrates.pdf`](./Socrates.pdf): Venn diagram as a model of luminousity. 

## Truth2vec
* The server's TruthSet forms a second embedding space similar to the first. This design is called Truth2vec, which orthogonalizes a sentential embedding space that influences the original embedding space in virtue of higher-order concepts.
* Contrastive learning algorithm for Truth2vec? No, use the embedding space, but the embedding space will be determined by bottom-up and top-down constraints. 
* In fact, all it needs is vedana, a +- weighting over the truth space of HOC that alters the categories that are formed as would desires expressed within a belief system.
* All words have a projection in 5-space, which is called the Where pathway
* They also exist in a subspace that is orthogonalized with respect to that space, called the What space (AKA Gardenfor’s conceptual space)
* A visualization consists of a set of dynamic points in that 6-space that are tied to the set of facts. So the facts can be treated as prototype vectors, each with an Truth2vec embedding that can act as a Fuzzy C-Means space for an arbitrary event (possibly abstracted from space or time as with a positional or temporal encoding). 
* If a lot of people represent facts about ”food”, we will have a good map of that space, and it will become an object space (symbolic space)
* Feelings get pulled around by “these truths that we hold important”. Because they come from human speech, they already have a 6-embedding. So they serve as anchors that warp an N-D feeling space into a 6-D symbolic space. 
* If we don’t turn off truth mode often enough, our feeling space will also be low rank.
* Having a low-rank feeling space is a bad thing. Buddha and Jesus both recommend being quiet in your mind as a way of increasing the rank of your feeling space. Which means that you let the distribution of the weight space be shaped by feelings and NOT truth. But in feeling training, all have an equal value. There is only Truth in the space of absolute truth: 1.0
* Facts are statically encoded vectors whose location is determined syntactically.
* Feelings are dynamically encoded vectors whose location is determined syntactically.

## The Operation of an Enlightened Mind (mahamudra)
* One pointedness is a distribution in space.
* Simplicity is developing ND awareness within space.
* One taste is about letting our attachment to feelings within that space be 1 everwhere.
* Buddhahood is the perfection of these three.
