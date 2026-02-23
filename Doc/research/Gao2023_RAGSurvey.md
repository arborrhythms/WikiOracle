    # Retrieval-Augmented Generation for Large Language Models: A Survey
    **Authors:** Yunfan Gao et al.  
    **Year:** 2023 (arXiv Dec 2023; v5 Mar 2024)  
    **arXiv:** https://arxiv.org/abs/2312.10997  
    **PDF:** https://arxiv.org/pdf/2312.10997  

    ## What problem this addresses
    Large language models often produce **plausible but untrue** outputs (“hallucinations”), and can also present claims with **miscalibrated confidence**. This paper contributes to methods (or taxonomies of methods) to make LLM outputs more **truthful**, **grounded**, and **auditable**.

    ## Core contribution
    A comprehensive survey of Retrieval-Augmented Generation (RAG) for LLMs—covering paradigms (naïve/advanced/modular), components (retrieval, augmentation, generation), and evaluation.

    ## Specific mechanisms proposed or synthesized
    - RAG architectures: retrieve-then-generate, iterative retrieval, reranking, multi-hop retrieval.
- Augmentation: prompt injection of passages, citation/provenance, tool calling.
- Evaluation: retrieval quality, answer correctness, grounding/attribution, and system-level benchmarks.

    ## How it reduces hallucination and/or deception
    RAG reduces hallucination by shifting from parametric recall to evidence-backed answering: the model conditions on retrieved passages, can cite them, and can abstain when retrieval fails. It also supports updates without retraining.

    ## What it can and cannot guarantee
    **Can help guarantee / improve**
    - Substantially reduce factual hallucination when retrieval corpus is high-quality and retrieval is accurate.
- Improve transparency via citations/provenance.
- Support domain-specific truth by swapping/curating corpora.

    **Cannot guarantee**
    - Guarantee truth if the corpus is wrong, biased, or adversarially poisoned.
- Prevent ‘citation laundering’ (citing irrelevant passages) without attribution checks.
- Solve deception; it mainly addresses factual grounding.

    ## Practical takeaways for system builders
    Build RAG as an end-to-end system: retrieval eval, anti-poisoning controls, attribution checks, and ‘answerability’ gating (don’t answer if evidence isn’t there).

    ## Mapping to “valid cognition” (pramāṇa-inspired lens)
    - **Perception / direct evidence:** what counts as externally checkable grounding (retrieved documents, tool outputs, measurements).
    - **Inference:** structured reasoning steps that preserve truth under valid rules (verification chains, constrained decoding, formal checks).
    - **Testimony / authority:** curated sources, citations, and provenance; also “epistemic humility” when testimony is absent or unreliable.

    **In this paper’s terms**
    Makes **testimony/perception** explicit: retrieved documents act as evidence; **inference** is then constrained to what’s supported by that evidence, aligning with a pramāṇa-like requirement for valid support.

