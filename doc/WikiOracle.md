# WikiOracle
Revision: 2026.02.27

## Architectural Overview

The system is governed by two file types:

* **State files** (`.xml`): contains header information, conversations, and trust entries (validated by `data/state.xsd`).
* **Config files** (`.xml`): contains provider credentials, chat and UI settings, and retrieval parameters (validated by `data/config.xsd`).

## Client

The state of WikiOracle is maintained by the client.
It has the following information:

* **Client**: has information about the user and the file itself
  * **Client Name**: client name
  * **Client ID**: stable client identifier
  * **UI**: browser-side default interface settings
    * **Layout**: horizontal, vertical, or flat layout
    * **Theme**: system, light, or dark
* **Conversation**: consists of queries, responses, and sub-conversations
  * **Query**: text from the user
  * **Response**: text from the (main) provider or LLM
* **TruthSet**: a set of beliefs, each of which has a Degree of Truth
  * **Direct Truth**: things that we know directly
    * **Feeling**: statements which are beyond true or not true, like poetry
    * **Fact**: concrete and abstract propositions about the world and language itself
    * **Operator**: a set of logical operators (And, Or, Not, and Non)
  * **Indirect Truth**: things that we know only indirectly
    * **Reference**: a reference is basically a URL
    * **Provider**: a provider is another oracle that can provide truth or even participate in the conversation.
    * **Authority**: an authority is a reference to another set of conversations and truths

## Server

The server executes the client state, based on a configuration file and a corpus of truth that it maintains which is identical to the TruthSet of a state file.

The configuration file on the server has information such as the following:

* **Server**: runtime and training parameters
  * **Server Name**: server name
  * **Server ID**: stable server identifier
  * **TruthSet**: parameters governing the server's TruthSet
    * **Truth Symmetry**: asymmetric-harm checking under identity exchange
    * **Store Concrete**: whether spatiotemporally-bound facts persist
    * **Truth Weight**: how much the TruthSet affects RAG and training
  * **Evaluation**: 
    * **Temperature**: sampling temperature
    * **Max Tokens**: maximum response length
  * **Training**: continuous learning subsystem
    * **Enabled**: master switch for post-response learning
    * **Truth Corpus Path**: path to the server TruthSet
    * **Truth Max Entries**: max server truth entries before trimming
  * **Allowed URLs**: whitelist for authority and provider fetches
* **Providers**: one or more upstream LLM provider definitions
  * **Provider**: a single provider entry keyed by name
    * **Username**: account login or email
    * **API Key**: authentication credential
  * **Default Provider**: provider selected on startup

## Conversation 

A conversation happens first by processing the Indirect Truth entries of the TruthSet: single references are fetched, the truth of authorities are collected, and providers (which are other minds) are asked for their input to the current Query.
The result of that is a TruthSet that consists only of Direct Truths.

All truths (except Feelings) have a Degree of Trust in the range [-1, 1], where -1 is fully untrusted, 0 is unknown, and 1 is fully trusted. 
Feelings are always trusted, but do not count as evidence when deliberating.
So computation over these truths looks like a network of trust that involves various sources and our own intuitions (whihc count, even though they cant provide evidence). 

Each of those facts is then compared to the TruthSet stored by the server.

## TruthSet

* **Trust entries** carry certainty values in [-1, +1] using Kleene ternary/fuzzy logic — from certainly true (+1) through ignorance (0) to certainly false (-1).
* **Logical operators** (and/or/not/non under Strong Kleene semantics) compute derived certainty over the TruthSet.
* **Authorities** reference external knowledge bases, enabling transitive trust with certainty scaling.
* **Providers** are external LLMs used as expert consultants whose responses become sources with associated certainty.
* **Feelings** are subjective statements (opinions, poetry, hedged claims) occupying the "neither" position in the tetralemma. They influence evaluation but are excluded from training and TruthSets.
* **References** are external source citations (Wikipedia, Snopes, etc.) that ground claims in verifiable sources, participating in the TruthSet alongside facts.

The UI-selected provider acts as the "mastermind," synthesizing all evidence — facts, references, operator-derived certainty, authority imports, and provider consultations — into a final response.

## Example

As a somewhat fun example, we consider how WikiOracle can be used to create a voting system that operates in real-time as a Hierarchical Mixture of Experts composed of multiple LLMS (or even a single LLM with mutliple truth sets).

The "alpha" conducts the vote. So there is a conversation in which the user asks a question. The state file of the alpha contains, in addition to various facts, feelings, and other sources of truth, two providers which we will call the "betas". When the user directs a query to the alpha, the alpha first turns its indirect truth into direct truth: that means evlauating the providers. So, the Query from the user is passed to the Betas.

Each of the Betas sees the query and is asked to respond with a Response to the Query, and optionally to provide its Facts and Feelings that are relevant to that Query. In a sense, they are voting on that query, and providing their own reasons for having done so.

Finally, the Alpha see the query and the Responses (or votes) cast by the betas. It also sees the facts and feelings that they have returned, which are incorporated into the TruthSet. So it has this mixture of its own truth and truth provided by each of the Betas, and based on their advice and its trust of each Beta, it concludes with a Respons of its own. This construct is a bit non-traditional in terms of a linear conversation, and it fact it creates a diamond pattern in the tree view of the conversation.

For more information, see [Voting](./Voting.md).
