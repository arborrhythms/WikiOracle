    # Chain-of-Verification Reduces Hallucination in Large Language Models
    **Authors:** Shehzaad Dhuliawala et al.  
    **Year:** 2023 (arXiv Sep 2023; ACL Findings 2024)  
    **arXiv:** https://arxiv.org/abs/2309.11495  
    **PDF:** https://arxiv.org/pdf/2309.11495  

    ## What problem this addresses
    Large language models often produce **plausible but untrue** outputs (“hallucinations”), and can also present claims with **miscalibrated confidence**. This paper contributes to methods (or taxonomies of methods) to make LLM outputs more **truthful**, **grounded**, and **auditable**.

    ## Core contribution
    Proposes Chain-of-Verification (CoVe): a structured deliberation loop where the model drafts an answer, generates verification questions, answers them independently, then revises the final output.

    ## Specific mechanisms proposed or synthesized
    - Step (i) draft answer.
- Step (ii) plan verification questions targeting factual claims.
- Step (iii) answer verification questions independently (reduce anchoring bias).
- Step (iv) synthesize a revised, verified response.
- Evaluated on multiple tasks (list questions, QA, long-form generation).

    ## How it reduces hallucination and/or deception
    CoVe reduces hallucination by creating explicit checkpoints that (a) expose unsupported claims and (b) give the model a chance to correct them before final output. Independence in step (iii) is key to reduce self-confirmation.

    ## What it can and cannot guarantee
    **Can help guarantee / improve**
    - Reduce hallucinations in many settings without external tools.
- Provide an internal audit trail (verification Qs) useful for monitoring.
- Combine well with retrieval/fact-checking tools for stronger grounding.

    **Cannot guarantee**
    - Guarantee truth if the model’s internal knowledge is wrong and no external evidence is used.
- Prevent strategic deception if incentives favor misleading outputs; needs alignment/monitoring.

    ## Practical takeaways for system builders
    Implement verification as a product primitive: generate claim-level checks, require pass/fail thresholds, and optionally integrate retrieval for each verification question.

    ## Mapping to “valid cognition” (pramāṇa-inspired lens)
    - **Perception / direct evidence:** what counts as externally checkable grounding (retrieved documents, tool outputs, measurements).
    - **Inference:** structured reasoning steps that preserve truth under valid rules (verification chains, constrained decoding, formal checks).
    - **Testimony / authority:** curated sources, citations, and provenance; also “epistemic humility” when testimony is absent or unreliable.

    **In this paper’s terms**
    Operationalizes **inference** as a disciplined process: break claims into testable sub-claims; optionally attach **testimony/perception** by retrieving evidence for each verification question.

