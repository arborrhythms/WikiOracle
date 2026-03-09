# WikiOracle
Revision: 2026.02.27

## Architectural Overview

The system is governed by two file types:

* **State files** (`.xml`): contains header information, conversations, and trust entries (validated by `data/state.xsd`).
* **Config files** (`.xml`): contains provider credentials, chat and UI settings, and retrieval parameters (validated by `data/config.xsd`).

## The Client

The state of WikiOracle is maintained by the client.
It has the following information:

* **Header**: has information about the user and the file itself
* **Conversation**: consists of queries, responses, and sub-conversations
  * **Query**: text from the user
  * **Response**: text from the (main) provider or LLM
* **Truth**: a set of beleiefs, each of which has a Degree of Truth
  * **Direct Truth**: corresponds to things we experience directly
    * **Fact**: concrete and abstract propositions about the world and language itself
    * **Feeling**: statements which are beyond true or not true, like poetry
  * **Indirect Truth**: inferences about truth that are based on direct truth
    * **Reference**: a reference is basically a URL
    * **Provider**: a provider is another oracle that can provide truth or even participate in the conversation.
    * **Operator**: a set of logical operators (And, Or, Not, and Non)
    * **Authority**: an authority is a reference to another set of conversations and truths

## The Server

The server executes the client state, based on a configuration file and a corpus of truth that it maintains which is identical to the Truth section of a state file.


## Conversation 

WikiOracle implements a **Hierarchical Mixture of Experts (HME)** architecture for evaluating claims.

The WikiOracle logic is similar to a hierarchical mixture of experts, where trust is based on truth values with associated certainty values in the range [-1, 1]. Those propositions can be static facts, references to other bodies of knowledge, or computed by other minds that are trusted and/or distrusted. Finally, truth is computed by logical operators (and/or/not under Strong Kleene semantics) over that body of propositions; see [Logic.md](./Logic.md) (Operator documentation).

WikiOracle implements a Hierarchical Mixture of Experts (HME) architecture for evaluating truth. 


## Truth

* **Trust entries** carry certainty values in [-1, +1] using Kleene ternary/fuzzy logic — from certainly true (+1) through ignorance (0) to certainly false (-1).
* **Logical operators** (and/or/not/non under Strong Kleene semantics) compute derived certainty over the truth table.
* **Authorities** reference external knowledge bases, enabling transitive trust with certainty scaling.
* **Providers** are external LLMs used as expert consultants whose responses become sources with associated certainty.
* **Feelings** are subjective statements (opinions, poetry, hedged claims) occupying the "neither" position in the tetralemma. They influence evaluation but are excluded from training and truth tables.
* **References** are external source citations (Wikipedia, Snopes, etc.) that ground claims in verifiable sources, participating in the truth table alongside facts.

The UI-selected provider acts as the "mastermind," synthesizing all evidence — facts, references, operator-derived certainty, authority imports, and provider consultations — into a final response.

## Example

As a somewhat fun example, we consider how WikiOracle can be used to create a voting system that operates in real-time as a Hierarchical Mixture of Experts composed of multiple LLMS (or even a single LLM with mutliple truth sets).

The "alpha" conducts the vote. So there is a conversation in which the user asks a question. The state file of the alpha contains, in addition to various facts, feelings, and other sources of truth, two providers which we will call the "betas". When the user directs a query to the alpha, the alpha first turns its indirect truth into direct truth: that means evlauating the providers. So, the Query from the user is passed to the Betas.

Each of the Betas sees the query and is asked to respond with a Response to the Query, and optionally to provide its Facts and Feelings that are relevant to that Query. In a sense, they are voting on that query, and providing their own reasons for having done so.

Finally, the Alpha see the query and the Responses (or votes) cast by the betas. It also sees the facts and feelings that they have returned, which are incorporated into the Truth Set. So it has this mixture of its own truth and truth provided by each of the Betas, and based on their advice and its trust of each Beta, it concludes with a Respons of its own. This construct is a bit non-traditional in terms of a linear conversation, and it fact it creates a diamond pattern in the tree view of the conversation.

For more information, see [Voting](./Voting.md).
