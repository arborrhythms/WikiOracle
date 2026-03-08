
# todo.md

* We need proper handling of the 'prelim' entry on the providers.

A provider entry in the truth table XML is another mind. As with all other indirect truth fields in the truth table, it is evaluated and turned into direct truth (facts and feelings) before evaluation by the main provider.

The "prior" field had controlled whether the beta sees the alpha's preliminary response as steering context. that field should be replaced with the "conversation" field. that field allows the beta to participate in the conversation, as opposed to just generating facts and feelings for the truth table.

Flow with conversation=true (not default):

Beta receives: conversation history (selected nodes) + Q and the evaluated truth table (free of any indirect truths).

Beta returns: its A to the Q (possibly within the scope of the conversation history) and whatever direct truths it wishes to provide.

That process repeats over all betas. for simplicity, the betas are called in parallel, so neither is privileged with respect to seeing the other responses. Thus their nodes in the tree are parallel.

Alpha is called after that, with the integrated conversation and truth table that consists of only direct truths (facts and feelings) 

Flow with conversation=false: (default)

Betas are not allowed to contribute to the conversation, they only offer direct truths for the truth table. 

Since providers other than WikiOracle will not necessary respond with well-formatted truth tables, default provider CONTEXT for the main provider, truth providers with conversation, and truth providers without conversation should be stored in the config.xml . We already have that for the main provider: it's displayed in the Context popup dialog as static text. we can just copy that for the other two as a start. 


