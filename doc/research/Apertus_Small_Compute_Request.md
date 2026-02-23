# Swiss AI Initiative – Small Compute Project Request (Apertus)

Principal Investigator: Alec Rogers (ArborRhythms)\
Project Type: Small Compute Request (Apertus / Swiss AI Initiative)\
Requested Resources: ~50,000 GPU hours (Alps infrastructure)

## Project Title

Syntax-Structured Inference for Truth-Grounded Language Models

## Abstract / Project Summary

Large language models currently optimize for next-token prediction,
yielding fluent but often epistemically unstable outputs. This project
proposes a retrofit to open-weight models such as Apertus that
introduces an explicit syntactic planning layer and belief-maintenance
mechanism. Instead of emitting unconstrained token streams, the model
iteratively emits structured syntactic objects (e.g., NP/VP units with
reference links, semantic roles, and modality), which are validated
against grammatical constraints and an explicit belief state tracking
evidential provenance (direct perception, testimony, inference).\
\
Truth is operationalized as the degree of stable referential existence
supported by evidence, rather than binary correspondence or narrative
coherence. The aim is to reduce hallucination, improve inferential
consistency, and make reasoning commitments explicit and auditable,
while preserving the expressive power of modern LLMs.

## Scientific Objectives

1\. Define a compact intermediate representation combining syntax,
reference, semantic roles, and evidence tags.\
2. Fine-tune Apertus to emit and condition on this representation.\
3. Implement constrained decoding and belief revision to enforce logical
and referential consistency.\
4. Evaluate improvements in contradiction rate, entailment stability,
and provenance tracking.

## Methodology

\- Supervised fine-tuning using syntactically and semantically annotated
corpora.\
- Constraint-based decoding enforcing grammar, reference, and
belief-state compatibility.\
- External truth-maintenance system to manage inference dependencies and
revision.\
- Comparative evaluation against baseline Apertus generations.

## Relevance and Community Engagement

This project is informed by ongoing public engagement around epistemic
integrity in open knowledge systems. The PI has recently contributed
discussion threads under the username ArborRhythms to r/wikipedia,
r/eff, and r/solid, all titled with the prefix 'WikiOracle', exploring
the limits of narrative coherence, testimony, and truth in large-scale
digital knowledge infrastructures. These discussions motivate the need
for transparent, truth-maintaining AI systems aligned with open-data and
open-governance values.

## Proposed Collaborators / Advisors

\- Francesca Rossi (AI ethics, governance, alignment)\
- Sara Hooker (trustworthy AI, transparency, global AI governance)\
- Melanie Mitchell (conceptual abstraction, limits of statistical
reasoning)\
- Mehul Bhatt (spatial cognition, knowledge representation,
neuro-symbolic reasoning)

## Expected Outcomes

\- Open-source code and documentation.\
- Fine-tuned Apertus checkpoints demonstrating structured inference.\
- Technical report evaluating truth-maintenance and logical stability.\
- Public-facing write-up connecting technical results to open knowledge
communities.

## Ethical and Open Science Commitments

All artifacts will be released under permissive open-source licenses. No
new data collection is proposed. Emphasis is placed on auditability,
provenance tracking, and resistance to deceptive or unsupported outputs,
in alignment with the Swiss AI Initiative’s goals.
