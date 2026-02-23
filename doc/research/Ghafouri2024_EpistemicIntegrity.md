    # Epistemic Integrity in Large Language Models
    **Authors:** Bijean Ghafouri et al.  
    **Year:** 2024 (arXiv Nov 2024)  
    **arXiv:** https://arxiv.org/abs/2411.06528  
    **PDF:** https://arxiv.org/pdf/2411.06528  

    ## What problem this addresses
    Large language models often produce **plausible but untrue** outputs (“hallucinations”), and can also present claims with **miscalibrated confidence**. This paper contributes to methods (or taxonomies of methods) to make LLM outputs more **truthful**, **grounded**, and **auditable**.

    ## Core contribution
    Addresses epistemic miscalibration: LLMs’ linguistic assertiveness often does not match their actual correctness; proposes methods to measure assertiveness and diagnose misalignment.

    ## Specific mechanisms proposed or synthesized
    - Human-labeled dataset for assertiveness / confidence expression.
- Measurement method for linguistic assertiveness; benchmarking against prior approaches.
- Analysis of misalignment between assertiveness and accuracy; suggests paths to correction (calibration).

    ## How it reduces hallucination and/or deception
    Many harmful hallucinations are amplified by *overconfident tone*. By detecting and reducing unjustified assertiveness (or by calibrating it), you reduce user over-trust and encourage abstention or verification.

    ## What it can and cannot guarantee
    **Can help guarantee / improve**
    - Improve calibration of expressed confidence.
- Reduce harm from hallucinations by lowering unjustified certainty.
- Enable UI/UX that uses confidence signals responsibly.

    **Cannot guarantee**
    - Make incorrect answers correct; it primarily aligns presentation with reliability.
- Provide a universal scalar ‘truth score’ across domains without evidence and domain calibration.

    ## Practical takeaways for system builders
    Treat ‘confidence expression’ as a safety-critical output channel. Calibrate tone, add uncertainty displays, and gate high-stakes advice on evidence and confidence thresholds.

    ## Mapping to “valid cognition” (pramāṇa-inspired lens)
    - **Perception / direct evidence:** what counts as externally checkable grounding (retrieved documents, tool outputs, measurements).
    - **Inference:** structured reasoning steps that preserve truth under valid rules (verification chains, constrained decoding, formal checks).
    - **Testimony / authority:** curated sources, citations, and provenance; also “epistemic humility” when testimony is absent or unreliable.

    **In this paper’s terms**
    Aligns with pramāṇa by demanding proportionality: strong assertion only when there is strong support (perception/testimony/inference); otherwise, weaken claim strength or abstain.

