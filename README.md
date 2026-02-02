# WikiOracle
WikiOracle is an open-sourced Oracle designed as a truth-engine for user-contributed content.

TL;DR : The oracle is an open-source LLM (based on GPT or Apertus) which is truthful, capable of online learning, and which serves as a public good.

Right now LLMs are using our data (sourced from a billion people) to train its LLMs. The world is using LLMs to train its children. This raises privacy concerns (how do we prevent malicious commercial use?), concerns about the psychological health of our children (do we want them imprinting on a prediction-engine based on arbitrary internet content?), and good opportunities (can we create a public good similar to Wikipedia?).

The proposal is to develop a simple truthful AI. This is an unsolved problem: LLMs currently hallucinate wildly, and AI architectures that are trained online are often “captured” (the new data drives them to hallucinate, become ideologically corrupt and less grounded in truth). But a simple GPT model is available for us to modify (GPT-2), training it is feasible ($100 on rented machines), and there are known mechanisms that attempt to ground answers in truth (such as RAG and ‘thinking’).

Concretely, the goal for 2026 is to augment NanoChat ( https://github.com/karpathy/nanochat ) with Retrieval-augmented generation (RAG) and a user-specified list of trusted sources and allow online learning. Architecture prototypes that utilize symbolic/syntactic/thought-based ways to ensure truth can be developed and tested insofar as our creativity allows. If encoding truthfulness has some measure of success, and truthfulness ensures honest introspection  (which would satisfy a number of safety constraints), we might scale the architecture using Apertus as a reference in 2027.
