    # Large Language Models Hallucination: A Comprehensive Survey
    **Authors:** Aisha Alansari, Hamzah Luqman  
    **Year:** 2025 (arXiv Oct 2025)  
    **arXiv:** https://arxiv.org/abs/2510.06265  
    **PDF:** https://arxiv.org/pdf/2510.06265  

    ## What problem this addresses
    Large language models often produce **plausible but untrue** outputs (“hallucinations”), and can also present claims with **miscalibrated confidence**. This paper contributes to methods (or taxonomies of methods) to make LLM outputs more **truthful**, **grounded**, and **auditable**.

    ## Core contribution
    A later comprehensive survey focusing on hallucination causes, detection, and mitigation across the *full LLM lifecycle* (data → training → inference), with an updated taxonomy and engineering guidance.

    ## Specific mechanisms proposed or synthesized
    - Lifecycle analysis: where hallucinations originate in data pipelines, training objectives, alignment tuning, and decoding.
- Detection methods: automatic metrics, model-based detectors, human evaluation protocols.
- Mitigation methods: retrieval grounding, prompt/process controls, fine-tuning/continual updates, and post-generation verification.

    ## How it reduces hallucination and/or deception
    Frames hallucination as a pipeline property: errors can be introduced early (data noise), reinforced by objective mismatch, and amplified by decoding. This helps prevent ‘patch-only’ fixes by showing which interventions address root cause vs. symptoms.

    ## What it can and cannot guarantee
    **Can help guarantee / improve**
    - More current map of mitigation techniques and where they apply best.
- Practical guidance for combining detection + mitigation into evaluation loops.
- Better governance of hallucination risk via stage-specific controls.

    **Cannot guarantee**
    - Guarantee truth without trusted external grounding.
- Guarantee the model won’t strategically mislead (deception) in adversarial settings without additional alignment and monitoring.

    ## Practical takeaways for system builders
    If you own deployment risk, implement stage-appropriate controls: data governance; training objectives for factual consistency; inference-time retrieval + verification; and continuous monitoring with human-in-the-loop for high-stakes domains.

    ## Mapping to “valid cognition” (pramāṇa-inspired lens)
    - **Perception / direct evidence:** what counts as externally checkable grounding (retrieved documents, tool outputs, measurements).
    - **Inference:** structured reasoning steps that preserve truth under valid rules (verification chains, constrained decoding, formal checks).
    - **Testimony / authority:** curated sources, citations, and provenance; also “epistemic humility” when testimony is absent or unreliable.

    **In this paper’s terms**
    Strongly supports a pramāṇa-like separation: use **perception/testimony** (retrieval, curated sources) when available; reserve **inference** (reasoning) for connecting grounded facts; require abstention when neither is present.

