# WikiOracle
Revision: 2026.02.27

## Architectural Overview

The system is governed by two file types:

* **State files** (`.xml`): contain client identity, UI preferences, conversations, and truth entries (validated by `data/state.xsd`).
* **Config files** (`.xml`): contain provider defaults and credentials, server policy, and runtime defaults (validated by `data/config.xsd`).

## Client

The state of WikiOracle is maintained by the client.
It has the following information:

* **Client**: has information about the user and the file itself
  * **Client Name**: display name shown for user-role messages
  * **Client ID**: stable client identifier
  * **UI**: browser-side default interface settings
    * **Layout**: horizontal or vertical layout, with legacy `flat` still supported
    * **Theme**: system, light, or dark
    * **Model**: currently selected model override
    * **Confirm Actions**: whether deletes and merges require confirmation
    * **Splitter**: saved tree/chat panel split position
* **Conversation**: consists of queries, responses, and sub-conversations arranged as a tree
  * **Query**: text from the user
  * **Response**: text from the selected main provider
  * **Selection**: the currently selected conversation path
  * **Branching**: child conversations can diverge from any earlier point
* **TruthSet**: a set of beliefs, each of which has a Degree of Truth
  * **Direct Truth**: things that we know directly
    * **Feeling**: statements which are beyond true or not true, like poetry or opinion
    * **Fact**: concrete and abstract propositions about the world and language itself
    * **Operator**: logical operators such as And, Or, Not, and Non
  * **Indirect Truth**: things that we know only indirectly
    * **Reference**: a URL or citation that grounds a claim
    * **Provider**: another oracle that can provide truth and optionally participate in the conversation
    * **Authority**: a reference to another set of conversations and truths

## Server

The server executes the client state, based on a configuration file and a corpus of truth that it maintains which is identical to the TruthSet of a state file.

The configuration file on the server has information such as the following:

* **Server**: runtime and training parameters
  * **Server Name**: human-readable server name
  * **Server ID**: stable server identifier
  * **Stateless**: whether the server is allowed to write to disk
  * **URL Prefix**: optional route prefix for reverse-proxy deployments
  * **TruthSet**: parameters governing the server's TruthSet
    * **Truth Symmetry**: asymmetric-harm checking under identity exchange
    * **Store Concrete**: whether spatiotemporally-bound facts persist
    * **Truth Weight**: how much the TruthSet affects RAG and training
  * **Evaluation**:
    * **Temperature**: sampling temperature
    * **Max Tokens**: maximum response length
    * **Timeout**: request timeout for provider calls
    * **URL Fetch**: whether URL fetching is allowed during evaluation
  * **Training**: continuous learning subsystem
    * **Enabled**: master switch for post-response learning
    * **Truth Corpus Path**: path to the server TruthSet
    * **Truth Max Entries**: max server truth entries before trimming
    * **Learning Rates**: `alpha_base`, `alpha_min`, `alpha_max`
    * **Merge Rate**: moving-average merge speed for truth updates
    * **Device**: `cpu`, `cuda`, or `auto`
    * **Dissonance**: contradiction detection and penalty
    * **Warmup / Clipping / Anchoring**: `warmup_steps`, `grad_clip`, `anchor_decay`
  * **Allowed URLs**: whitelist for authority and provider fetches
* **Providers**: one or more upstream LLM provider definitions
  * **Default Provider**: provider selected on startup when the request does not override it
  * **Shared Prompt Fields**: `context`, `output`, `truth_context`, and `conversation_context`
  * **Provider**: a single provider entry keyed by name
    * **Display Name**: label shown in assistant messages
    * **Username**: account login or email
    * **URL**: API endpoint
    * **API Key**: authentication credential
    * **Default Model**: model used when none is selected explicitly
    * **Timeout / Streaming**: per-provider request behavior
  * **Built-in Providers**: WikiOracle, OpenAI, Anthropic, Gemini, Grok, and OpenRouter

## Conversation 

A conversation happens first by processing the Indirect Truth entries of the TruthSet: single references are fetched, the truth of authorities are collected, and providers (which are other minds) are asked for their input to the current Query.
The result of that is a TruthSet that consists only of Direct Truths.

All truths (except Feelings) have a Degree of Trust in the range [-1, 1], where -1 is fully untrusted, 0 is unknown, and 1 is fully trusted. 
Feelings are always trusted, but do not count as evidence when deliberating.
So computation over these truths looks like a network of trust that involves various sources and our own intuitions (whihc count, even though they cant provide evidence). 

Each of those facts is then compared to the TruthSet stored by the server.

## TruthSet

* **Trust entries** carry certainty values in [-1, +1] using Kleene ternary/fuzzy logic -- from certainly true (+1) through ignorance (0) to certainly false (-1).
* **Logical operators** (and/or/not/non under Strong Kleene semantics) compute derived certainty over the TruthSet.
* **Authorities** reference external knowledge bases, enabling transitive trust with certainty scaling.
* **Providers** are external LLMs used as expert consultants whose responses become sources with associated certainty.
* **Feelings** are subjective statements (opinions, poetry, hedged claims) occupying the "neither" position in the tetralemma. They influence evaluation but are excluded from training and TruthSets.
* **References** are external source citations (Wikipedia, Snopes, etc.) that ground claims in verifiable sources, participating in the TruthSet alongside facts.

The UI-selected provider acts as the "mastermind," synthesizing all evidence -- facts, references, operator-derived certainty, authority imports, and provider consultations -- into a final response.

## Example

As a somewhat fun example, we consider how WikiOracle can be used to create a voting system that operates in real-time as a Hierarchical Mixture of Experts composed of multiple LLMS (or even a single LLM with mutliple truth sets).

The "alpha" conducts the vote. So there is a conversation in which the user asks a question. The state file of the alpha contains, in addition to various facts, feelings, and other sources of truth, two providers which we will call the "betas". When the user directs a query to the alpha, the alpha first turns its indirect truth into direct truth: that means evlauating the providers. So, the Query from the user is passed to the Betas.

Each of the Betas sees the query and is asked to respond with a Response to the Query, and optionally to provide its Facts and Feelings that are relevant to that Query. In a sense, they are voting on that query, and providing their own reasons for having done so.

Finally, the Alpha see the query and the Responses (or votes) cast by the betas. It also sees the facts and feelings that they have returned, which are incorporated into the TruthSet. So it has this mixture of its own truth and truth provided by each of the Betas, and based on their advice and its trust of each Beta, it concludes with a Respons of its own. This construct is a bit non-traditional in terms of a linear conversation, and it fact it creates a diamond pattern in the tree view of the conversation.

For more information, see [Voting](./Voting.md).
