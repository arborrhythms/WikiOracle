    # Survey on Factuality in Large Language Models: Knowledge, Retrieval and Domain-Specificity
    **Authors:** Cunxiang Wang et al.  
    **Year:** 2023 (arXiv Oct 2023)  
    **arXiv:** https://arxiv.org/abs/2310.07521  
    **PDF:** https://arxiv.org/pdf/2310.07521  

    ## What problem this addresses
    Large language models often produce **plausible but untrue** outputs (“hallucinations”), and can also present claims with **miscalibrated confidence**. This paper contributes to methods (or taxonomies of methods) to make LLM outputs more **truthful**, **grounded**, and **auditable**.

    ## Core contribution
    A structured survey defining ‘factuality’ as consistency with established facts, analyzing why factual errors occur, and cataloging evaluation + improvement methods for both standalone and retrieval-augmented LLMs.

    ## Specific mechanisms proposed or synthesized
    - Mechanisms: how LLMs store and use factual knowledge; failure modes.
- Evaluation: metrics and benchmarks for factual consistency in generation.
- Improvement: data curation, factuality-oriented fine-tuning, retrieval augmentation, and post-hoc checking; plus domain-specific techniques.

    ## How it reduces hallucination and/or deception
    Factuality-focused pipelines reduce hallucination by: (i) constraining generation to verified facts, (ii) retrieving evidence rather than guessing, and (iii) applying factual consistency checks after generation.

    ## What it can and cannot guarantee
    **Can help guarantee / improve**
    - Improve factual consistency and domain robustness.
- Provide a blueprint for evaluation regimes tied to factual risk.
- Support more reliable RAG by clarifying its unique error modes.

    **Cannot guarantee**
    - Guarantee truth when ‘established facts’ are ambiguous, contested, or time-sensitive without up-to-date sources.
- Solve honesty/deception by itself (it’s about factuality, not intent).

    ## Practical takeaways for system builders
    Use factuality as an explicit product requirement: define target sources of truth, pick metrics/benchmarks accordingly, and instrument RAG with provenance + answerability detection.

    ## Mapping to “valid cognition” (pramāṇa-inspired lens)
    - **Perception / direct evidence:** what counts as externally checkable grounding (retrieved documents, tool outputs, measurements).
    - **Inference:** structured reasoning steps that preserve truth under valid rules (verification chains, constrained decoding, formal checks).
    - **Testimony / authority:** curated sources, citations, and provenance; also “epistemic humility” when testimony is absent or unreliable.

    **In this paper’s terms**
    Elevates **testimony/perception** (retrieval from trusted corpora) as primary support for factual claims; then uses **inference** to integrate evidence into coherent answers.

