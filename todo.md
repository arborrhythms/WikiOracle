# TODO

================================== Europe ==================================

## Ask Solid community for a simple file-getting interface
* if the user provides the server with an API key, we can query an LLM
* if the user provides the server with a SOLID key, we can retrieve a file
* if the user provides the server with a DSA key, we can decrypt a file
* is there a POD service that does simple free hosting?

## Ask EFF for a security review
* propose "Owning our Data"
* this entails taht marketers and AI are not allowed to lock us down karmically
with specifically-characterized information (concrete details)
* maybe it can learn from that data by removing or randomizing that information

## Send email proposal to Apertus / SwissAI
* First develop boilerplate on WikiOracle that references wikipedia, eff, and solid

## Re-apply for poster session

## Get WikiOracle running
* Start with training a model

================================== Deferred ==================================

## Reversing Verb Operation (rev- prefix)
* When grammatically coding a sentence, allow a "rev-" prefix on a VP to do the inverse VP: lift_inverse() followed by lift() to reconstruct.
* Surface grammar: add `VP -> REV VP` and `REV -> "rev"` to grammar.cfg
* Parser: add handler in parse.py VP block to emit `<rev-lift>` XML tag
* LiftingLayer: add `lift_inverse()` to Model.py -- since forward_reflexive computes C' = (I + VP_eff) @ C, inverse is C = (I + VP_eff)^{-1} @ C' via torch.linalg.solve
* Engine: handle `<rev-lift>` tag in ConceptualSpace forward pass

## Point-Free Spacetime
* The `<place>` and `<time>` attributes of facts and feelings define a larger or smaller spatiotemporal subspace, not an infinite universal or infinitesimal particular extent.  The universal/particular distinction is a gradient of spatiotemporal extent (see doc/Freedom.md), and every proposition occupies a subspace that is larger or smaller, never infinite or infinitesimal.
* Allow ranges in `<place>` and `<time>` fields (e.g. `<time>2020..2026</time>`, `<place>Western Europe</place>`) and treat bare points as implicit small ranges, consistent with point-free topology.
* Investigate mereological / point-free representations of spatiotemporal extent so that `is_news_fact()` / `is_knowledge_fact()` can operate on extent size rather than presence/absence of child elements -- a proposition with a broad temporal range behaves more like knowledge even if it carries a `<time>`.

## A Group Based on the People that you Trust
* Add a tie-in to identity that establishes a ZK proof of citizenship within a specific location. 
* So the requirement for voting is not identifying yourself, but a ZK proof answer to "are you a citizen that pays taxes and has declared legal residency in Oregon?". 
* That allows you to participate in a network of trust which can determine how much the community trusts you. 
* It is a dynamic and revokable Trust score determined by everyone else in Oregon. 
* Even if you don't have a high trust score overall, you may have a high trust score within a small population. 
* You might have a bestie who trusts you entirely. 
* And that will, to some degree, imply that they trust who you trust (assuming that you have allowed Transitivity). 
* And that will buy you in to a trustworthy community, if you play your cards right, which can help you support your local group (where that group has a definition only for you).


