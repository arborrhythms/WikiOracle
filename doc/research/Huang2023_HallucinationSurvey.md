    # A Survey on Hallucination in Large Language Models
    **Authors:** Lei Huang et al.  
    **Year:** 2023 (arXiv v1 Nov 2023; later versions/venues exist)  
    **arXiv:** https://arxiv.org/abs/2311.05232  
    **PDF:** https://arxiv.org/pdf/2311.05232  

    ## What problem this addresses
    Large language models often produce **plausible but untrue** outputs (“hallucinations”), and can also present claims with **miscalibrated confidence**. This paper contributes to methods (or taxonomies of methods) to make LLM outputs more **truthful**, **grounded**, and **auditable**.

    ## Core contribution
    A broad survey that defines and taxonomizes hallucinations in LLMs, analyzes causes across data/model/decoding, and organizes detection + mitigation methods into a coherent framework.

    ## Specific mechanisms proposed or synthesized
    - Layered taxonomy distinguishing types of hallucination (e.g., factual vs. faithfulness), with causal factors.
- Mitigation buckets: improved training data/curation, instruction tuning, decoding constraints, retrieval/tool augmentation, and post-hoc verification.
- Evaluation: benchmarks/metrics to measure hallucination propensity across tasks.

    ## How it reduces hallucination and/or deception
    By connecting *mitigations to causes*, the survey clarifies when to use retrieval grounding vs. calibration vs. verification. It also highlights that many hallucinations arise from optimization for fluency rather than truth, motivating additional objectives and evaluations focused on factual consistency.

    ## What it can and cannot guarantee
    **Can help guarantee / improve**
    - Better diagnosis of hallucination subtype and selection of the right mitigation stack.
- Evidence-grounded generation when combined with retrieval and citation.
- Reduced error rates in practice by combining data, training, retrieval, and verification.

    **Cannot guarantee**
    - Formal truth guarantees in open-world settings without trusted external evidence.
- Prevent all hallucinations when the model is asked to answer beyond available evidence or source coverage.
- Ensure non-deceptive behavior by itself (needs alignment / honesty constraints).

    ## Practical takeaways for system builders
    Use the taxonomy as an engineering checklist: decide your target failure modes, then combine (1) retrieval + provenance, (2) verification loops, (3) calibration/abstention, and (4) domain-specific evaluation. Treat “hallucination” as multiple problems, not one.

    ## Mapping to “valid cognition” (pramāṇa-inspired lens)
    - **Perception / direct evidence:** what counts as externally checkable grounding (retrieved documents, tool outputs, measurements).
    - **Inference:** structured reasoning steps that preserve truth under valid rules (verification chains, constrained decoding, formal checks).
    - **Testimony / authority:** curated sources, citations, and provenance; also “epistemic humility” when testimony is absent or unreliable.

    **In this paper’s terms**
    Emphasizes **testimony/perception** via retrieval and citations as antidotes to unsupported claims, and motivates **inference** via verification stages and consistency checks; also implicitly supports humility/abstention when pramāṇa is missing.

