    # Factuality of Large Language Models: A Survey
    **Authors:** Yiming Wang et al.  
    **Year:** 2024 (arXiv Feb 2024)  
    **arXiv:** https://arxiv.org/abs/2402.02420  
    **PDF:** https://arxiv.org/pdf/2402.02420  

    ## What problem this addresses
    Large language models often produce **plausible but untrue** outputs (“hallucinations”), and can also present claims with **miscalibrated confidence**. This paper contributes to methods (or taxonomies of methods) to make LLM outputs more **truthful**, **grounded**, and **auditable**.

    ## Core contribution
    A newer survey that critically analyzes factuality evaluation and improvement, emphasizing the difficulty of automated factuality scoring for open-ended text and outlining mitigation directions.

    ## Specific mechanisms proposed or synthesized
    - Taxonomy of factuality challenges and causes in open-ended generation.
- Review of automated evaluators (LLM-as-judge, NLI-based, reference-based) and their failure modes.
- Mitigation techniques: retrieval grounding, constrained generation, and iterative verification; plus human evaluation guidance.

    ## How it reduces hallucination and/or deception
    Highlights that some hallucination persists because evaluation is weak: if you cannot reliably score factuality, you cannot reliably train it. The survey therefore motivates better evaluators and multi-signal monitoring (citations, consistency, abstention).

    ## What it can and cannot guarantee
    **Can help guarantee / improve**
    - Improve system design by clarifying evaluator limitations (reducing ‘false confidence’ in metrics).
- Guide selection of factuality mitigations appropriate to open-ended outputs.

    **Cannot guarantee**
    - Provide a single automatic metric that robustly certifies truth across domains and styles.
- Eliminate hallucination without trustworthy evidence sources and rigorous evaluation.

    ## Practical takeaways for system builders
    Treat factuality evaluation as a core subsystem: use multiple evaluators, measure uncertainty, and keep humans in the loop for high-impact claims. Avoid training to a single brittle automatic judge.

    ## Mapping to “valid cognition” (pramāṇa-inspired lens)
    - **Perception / direct evidence:** what counts as externally checkable grounding (retrieved documents, tool outputs, measurements).
    - **Inference:** structured reasoning steps that preserve truth under valid rules (verification chains, constrained decoding, formal checks).
    - **Testimony / authority:** curated sources, citations, and provenance; also “epistemic humility” when testimony is absent or unreliable.

    **In this paper’s terms**
    Warns against overreliance on weak ‘testimony’ (automatic scorers) and encourages returning to direct **perception/evidence** plus disciplined **inference** with verification.

