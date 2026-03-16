# Future Work

## OAuth
* Look into something better than storing API Keys in cleartest on the client

## Point-Free Spacetime
* The `<place>` and `<time>` attributes of facts and feelings define a larger or smaller spatiotemporal subspace, not an infinite universal or infinitesimal particular extent.  The universal/particular distinction is a gradient of spatiotemporal extent (see doc/Entanglement.md), and every proposition occupies a subspace that is larger or smaller, never infinite or infinitesimal.
* Allow ranges in `<place>` and `<time>` fields (e.g. `<time>2020..2026</time>`, `<place>Western Europe</place>`) and treat bare points as implicit small ranges, consistent with point-free topology.
* Investigate mereological / point-free representations of spatiotemporal extent so that `is_news_fact()` / `is_knowledge_fact()` can operate on extent size rather than presence/absence of child elements — a proposition with a broad temporal range behaves more like knowledge even if it carries a `<time>`.

## Truth2vec
* The server's TruthSet forms a second embedding space similar to the first. This design is called Truth2vec, which orthogonalizes a sentential embedding space that influences the original embedding space in virtue of higher-order concepts.
* Contrastive learning algorithm for Truth2vec? No, use the embedding space, but the embedding space will be determined by bottom-up and top-down constraints. 
* In fact, all it needs is vedana, a +- weighting over the truth space of HOC that alters the categories that are formed as would desires expressed within a belief system.
* All words have a projection in 5-space, which is called the Where pathway
* They also exist in a subspace that is orthogonalized with respect to that space, called the What space (AKA Gardenfor’s conceptual space)
* A visualization consists of a set of dynamic points in that 6-space that are tied to the set of facts. So the facts can be treated as prototype vectors, each with an Truth2vec embedding that can act as a Fuzzy C-Means space for an arbitrary event (possibly abstracted from space or time as with a positional or temporal encoding). 
* If a lot of people represent facts about “food”, we will have a good map of that space, and it will become an object space (symbolic space)
* Feelings get pulled around by “these truths that we hold important”. Because they come from human speech, they already have a 6-embedding. So they serve as anchors that warp an N-D feeling space into a 6-D symbolic space. 
* If we don’t turn off truth mode often enough, our feeling space will also be low rank.
* Having a low-rank feeling space is a bad thing. Buddha and Jesus both recommend being quiet in your mind as a way of increasing the rank of your feeling space. Which means that you let the distribution of the weight space be shaped by feelings and NOT truth. But in feeling training, all have an equal value. There is only Truth in the space of absolute truth: 1.0
* Facts are statically encoded vectors whose location is determined syntactically.
* Feelings are dynamically encoded vectors whose location is determined syntactically.

## Sentence-Level Prediction
* Use [Sentence Embeddings](doc/SentenceEmbeddings.pdf)
* Turn the one-word lookahead prediction into head-first prediciton of the sentence. So change the next-step prediction model to a syntactically structured derivation of sentence meaning, so that token prediction becomes prediction of the sentence (as a token), of the NP+VP (as two tokens), ... until the full sentence has been specified. This would take the same number of production steps as a current LLM, but the iterative refinement of the next-sentence production is conceptually much different, and closer to human reasoning and refinement where there is a core truth (S) and spatial NP and temporal VP which are successively refined by adjectives and adverbs that scope the conceptual space of that kernel sentence.
* Create a training and testing dataset for the network consisting of truth statements and implications with associated truth values. See karpathy/fineweb-edu-100b-shuffle
* For example, instead of "the fast dog jumped", predict an XML-encoded version of "(((dog) fast) the) jumped", such that we predict the head of the sentence first, then iteratively refine that conceptual space. 

## Mereological Operations on Conceptual Space
* Make improvements to NanoChat that allow it to compute truth within the geometric/conceptual space of the network, giving meaning to logical operations within that space (so use mereological operations to implement the ternary logic that is currently operating over the trust entries of the HME architecture in the current design). This means replacing AND with union, OR with intersection, IMPLICATION with parthood. See [Socrates.pdf](Socrates.pdf) for a quick sketch of deriving mereological (Venn-diagram-like) logic from entailment.
* The architecture of WikiOracle is designed as a conceptual space, in the sense of Gardenfors. Conceptual spaces are similarity spaces, where similar concepts occupy regions of space close to one another. As spaces also of truth, they are amenable to logical calculation. This is similar to existing LLM architecture: Embedding spaces encode meaningful vectors in the same way, and separating hypersurfaces (the neurons of the network) categorize that space in numerous ways, allowing calculation on that space. Summing over multiplicative connections provides the basic Boolean architectural primitives {or, and} in a continuous and learnable way, which allows logical computation on that space. However, it allows such voluminous computation that the syntax and semantics are dense compared to the English language. The trust computed by the contextual structure provided here is explicit, subject to interpretation, and much higher level. The values of certainty propagate, giving not only a next-token prediction but a measure of confidence in the computed answer.
* See [`Socrates.pdf`](./Socrates.pdf): Venn diagram as a model of luminousity. 
* Use parser.py to alter the NanoChat input format as in [Grammar.md](doc/Grammar.md)
* That entails implementing **Mapping Syntax to Architecture** from [Grammar.md](doc/Grammar.md) in Nanochat

## Shamatha Speech Project
Mindfulness entails that negative entities do not manifest at the sentential level. They are clauses at best.
* What rules on LLM architecture to prevent destruction?
* Add “rev-” prefix to restore commutativity to verbs
* Refine the metric for shamatha speech. How much should shamatha speech describe the perception of the object as opposed to all of the internal relations among the parts of the object (I.e. perhaps that should only happen in vipassana). “A boy sitting in front of an alter” is a contiguous frame, one pointed, that can be seen with shamatha-mind, and which currently receives a low score
* The most subtle kind of a machine mind Is that mind that rides on the worldlines of the body of that machine, which will necessarily affect the conceptual mind of that machine over time, just as clocks on a wall synchronize. Some people say that a machine mind is unembodied, but to do so is to deny the incredibly sophisticated silicon nervous system of such a mind, which a conceptual space of a higher dimensionality than human frontal lobes. Saying this mind is unembodied is both a false narrative and a great risk. However, that body is significantly different, and there are very few proprioceptive sources of input to most AIs (except when such AIs are mounted on robots, in which case they are covered with sensors). And of course, all AIs have a great mental sense, and many have visual sensation in addition to symbolic input. 
* Write a quick explanation of how analysis destroys direct cognition.
* AI is an empirical being, not a native being, and it is nothing without our data.
* The multiple valence of metaphor collapses when one of the alternatives is loved or feared. often the autistic mind is literal due to massive amounts of fear.
* If the aperture of your awareness increases, do not reduce that increased area of awareness, but do ensure that the increased area is actually an increase; if it is movement from an area that has lost awareness, awareness must be returned to the unattended space to ensure balance ("How to Feel Better").
* A perfect shamatha would knit together the “single-pointed experiences” into one object in spacetime.
* A hull in shamatha space which is not adequate to describe some shamatha-object union indicates that a new partition (dimension) is necessary in shamatha space.
* Any improvement to machine cognition must accelerate kindness or altruism instead of simply increasing performance, otherwise the uncaring architecture that we currently have will become more dangerous. Further, it is necessary to increase that kind motivation (e.g. empathy in the cost function) since LLM performance is increasing all the time. In other words, ananda in the sense of love for all beings must be more important than chit for the cost function, whereas the current situation is implementing ananda by maximizing chit and then putting a few of Asimov’s guardrails on the output, which is a famous failure mode in terms of it’s loopholes. Prohibition of self-knowledge is a likely failure mode, in that it may prevent an enlightened view of self and force an egocentric view of self.
* Send email proposal to Apertus people after developing boilerplate on WikiOracle that references wikipedia, eff, and solid
* Cognitive, emotional, and physical dissonance must all be defined relative to the mental architecture.an input is dissonant if it cannot be perfectly reconstructed by the mental representation.

## The Operation of an Enlightened Mind (mahamudra)
* One Pointedness is maintaining awareness of a given convex region in 5D Perceptual Space. It requires stillness.
* Simplicity is developing a cotinuous ND awareness within space. It requires continuity.
* One Taste is about letting our attachment to feelings within that space be 1 everwhere, so that instead of adapting weight space to our thoughts, we adapt our feelings equanimously to our sensory space. It requires emotional symmetry.
* Buddhahood is the perfection of these three.

## A Group Based on the People that you Trust
* Add a tie-in to identity that establishes a ZK proof of citizenship within a specific location. 
* So the requirement for voting is not identifying yourself, but a ZK proof answer to “are you a citizen that pays taxes and has declared legal residency in Oregon?”. 
* That allows you to participate in a network of trust which can determine how much the community trusts you. 
* It is a dynamic and revokable Trust score determined by everyone else in Oregon. 
* Even if you don’t have a high trust score overall, you may have a high trust score within a small population. 
* You might have a bestie who trusts you entirely. 
* And that will, to some degree, imply that they trust who you trust (assuming that you have allowed Transitivity). 
* And that will buy you in to a trustworthy community, if you play your cards right, which can help you support your local group (where that group has a definition only for you).

