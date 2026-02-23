    # Knowledge Boundary of Large Language Models: A Survey
    **Authors:** Moxin Li et al.  
    **Year:** 2024 (arXiv Dec 2024; later versions 2025)  
    **arXiv:** https://arxiv.org/abs/2412.12472  
    **PDF:** https://arxiv.org/pdf/2412.12472  

    ## What problem this addresses
    Large language models often produce **plausible but untrue** outputs (“hallucinations”), and can also present claims with **miscalibrated confidence**. This paper contributes to methods (or taxonomies of methods) to make LLM outputs more **truthful**, **grounded**, and **auditable**.

    ## Core contribution
    Defines and surveys the ‘knowledge boundary’ of LLMs—what they can reliably know and use—plus methods to identify those boundaries and mitigate failures outside them.

    ## Specific mechanisms proposed or synthesized
    - Formal definition and taxonomy of knowledge types.
- Boundary identification: probing, uncertainty estimation, out-of-distribution detection, and benchmarks.
- Mitigation: selective answering, retrieval augmentation, targeted fine-tuning, and system-level safeguards.

    ## How it reduces hallucination and/or deception
    Hallucination is often boundary violation: the model answers beyond its reliable knowledge. Boundary-aware systems reduce hallucination by detecting low-knowledge regimes and switching to retrieval/abstention.

    ## What it can and cannot guarantee
    **Can help guarantee / improve**
    - Improve reliability by gating answers based on ‘answerability’.
- Provide a framework to decide when to retrieve, defer, or refuse.
- Reduce confident fabrications on out-of-scope queries.

    **Cannot guarantee**
    - Perfectly delineate knowledge in all contexts (boundaries shift with prompting and distribution).
- Replace evidence: boundary detection must be paired with grounding/verification for strong truth claims.

    ## Practical takeaways for system builders
    Add a knowledge-boundary controller: estimate answerability, then choose (a) answer w/ citation, (b) retrieve, (c) ask clarifying questions, or (d) abstain.

    ## Mapping to “valid cognition” (pramāṇa-inspired lens)
    - **Perception / direct evidence:** what counts as externally checkable grounding (retrieved documents, tool outputs, measurements).
    - **Inference:** structured reasoning steps that preserve truth under valid rules (verification chains, constrained decoding, formal checks).
    - **Testimony / authority:** curated sources, citations, and provenance; also “epistemic humility” when testimony is absent or unreliable.

    **In this paper’s terms**
    Explicitly encodes ‘valid cognition requires support’: if perception/testimony is absent and inference is weak, abstain rather than fabricate—very close to a pramāṇa discipline.

