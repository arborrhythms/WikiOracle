    # A Survey on the Honesty of Large Language Models
    **Authors:** Siheng Li et al.  
    **Year:** 2024 (arXiv Sep 2024)  
    **arXiv:** https://arxiv.org/abs/2409.18786  
    **PDF:** https://arxiv.org/pdf/2409.18786  

    ## What problem this addresses
    Large language models often produce **plausible but untrue** outputs (“hallucinations”), and can also present claims with **miscalibrated confidence**. This paper contributes to methods (or taxonomies of methods) to make LLM outputs more **truthful**, **grounded**, and **auditable**.

    ## Core contribution
    A survey that defines and systematizes ‘honesty’ in LLMs—covering what it means for a model to know/express uncertainty, to avoid confident wrong answers, and to resist incentives to mislead.

    ## Specific mechanisms proposed or synthesized
    - Clarifies definitions (honesty vs. accuracy vs. calibration vs. deception).
- Evaluation: benchmarks for overconfidence, selective answering, refusal/abstention, and truthfulness under pressure.
- Improvement strategies: calibration, uncertainty estimation, truthful preference optimization, self-checking, and tool-grounded answering.

    ## How it reduces hallucination and/or deception
    Targets hallucination as *epistemic failure*: the model answers beyond its knowledge boundary and fails to signal uncertainty. By improving calibration and selective answering, it reduces the frequency of confident fabrications and makes residual errors easier to detect.

    ## What it can and cannot guarantee
    **Can help guarantee / improve**
    - Improve *epistemic humility* (knowing/expressing ‘I don’t know’).
- Reduce confident wrong answers through calibration + abstention.
- Provide a framework to evaluate deceptive tendencies separately from factual errors.

    **Cannot guarantee**
    - Perfect honesty in all adversarial contexts without robust oversight, incentives, and audits.
- Substitute for external grounding when the model lacks access to evidence.

    ## Practical takeaways for system builders
    Separate three objectives in system design: (1) factual accuracy, (2) calibrated expression of uncertainty, (3) anti-deception constraints. Optimize and evaluate each explicitly.

    ## Mapping to “valid cognition” (pramāṇa-inspired lens)
    - **Perception / direct evidence:** what counts as externally checkable grounding (retrieved documents, tool outputs, measurements).
    - **Inference:** structured reasoning steps that preserve truth under valid rules (verification chains, constrained decoding, formal checks).
    - **Testimony / authority:** curated sources, citations, and provenance; also “epistemic humility” when testimony is absent or unreliable.

    **In this paper’s terms**
    Treats honesty as correct alignment between **inference strength** and **assertion strength**; encourages abstention when pramāṇa is absent, and supports testimony via tool/retrieval grounding.

