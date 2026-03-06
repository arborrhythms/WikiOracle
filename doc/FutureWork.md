# Future Work

## Network of Trust
- Network of trust that supports diverse, multi-tenant models of what an individual finds true, similar to DDNS, instead of a monolithic body of truth governed by monopolistic corporations with product motives, advertising budgets, and mandates to capture attention.
- Pseudonymous participation in that network, allowing alignment with individual values within that distributed space.

## Sentence-Level Prediction
- Change the next-step prediction model to a syntactically structured derivation of sentence meaning, so that token prediction becomes prediction of the sentence (as a token), of the NP+VP (as two tokens), ... until the full sentence has been specified. This would take the same number of production steps as a current LLM, but the iterative refinement of the next-sentence production is conceptually much different, and closer to human reasoning and refinement where there is a core truth (S) and spatial NP and temporal VP which are successively refined by adjectives and adverbs that scope the conceptual space of that kernel sentence.
- A training and testing dataset for the network consisting of truth statements and implications with associated truth values.

## Mereological Operations on Conceptual Space
- Make improvements to NanoChat that allow it to compute truth within the geometric/conceptual space of the network, giving meaning to logical operations within that space (so use mereological operations to implement the ternary logic that is currently operating over the trust entries of the HME architecture in the current design). This means replacing AND with union, OR with intersection, IMPLICATION with parthood. See [Socrates.pdf](Socrates.pdf) for a quick sketch of deriving mereological (Venn-diagram-like) logic from entailment.

## Point-Free Spacetime
- The `<place>` and `<time>` attributes of facts and feelings define a larger or smaller spatiotemporal subspace, not an infinite synchronic or infinitesimal diachronic extent.  The synchronic/diachronic distinction is a gradient of spatiotemporal extent (see doc/Entanglement.md), and every proposition occupies a subspace that is larger or smaller, never infinite or infinitesimal.
- Allow ranges in `<place>` and `<time>` fields (e.g. `<time>2020..2026</time>`, `<place>Western Europe</place>`) and treat bare points as implicit small ranges, consistent with point-free topology.
- Investigate mereological / point-free representations of spatiotemporal extent so that `is_news_fact()` / `is_knowledge_fact()` can operate on extent size rather than presence/absence of child elements — a proposition with a broad temporal range behaves more like knowledge even if it carries a `<time>`.

## MCP Integration
- Expose WikiOracle as an MCP server: wrap `/chat`, truth management, and state merge as MCP tools; expose state and trust graph as MCP resources.
- Use MCP servers as authority-adjacent inputs: convert MCP resource/tool outputs into `<reference>`/`<fact>` entries with explicit certainty and scope, replacing per-source custom integrations.
- Multi-channel front-end via OpenClaw: route messages from Slack/Discord/Telegram to WikiOracle's `/chat` endpoint, preserving local-first truth ownership.
