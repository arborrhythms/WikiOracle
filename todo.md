
# todo.md
For all of the following, after the completion of the task
- verify that documentation reflects the changed code in both markdown files in ./doc and the code comments.
- add testpoints as appropriate
- run make test to verify all testpoints pass
- run make all to deploy


## All config and settings files should be XML, with well-defined schemas.
- They should be translated as necessary to JSONL.
- Pass as XML to the AIs
- Remove the YAML replace with XML, since an indented and formatted XML is almost as good.

### Plan
- [x] 1. **Create XSD schema** (`data/config.xsd`) defining the full config structure: `<config>` root with `<user>`, `<providers>`, `<chat>`, `<ui>`, `<server>` sections. Each provider is a `<provider name="...">` element. Lists like `allowed_urls` use repeated `<url>` children.
- [x] 2. **Create `config.xml`** at project root as the canonical config file, migrated from `config.yaml`. Also update `data/config.xml` (template). Keep `config.yaml` as a deprecated fallback until migration is stable, then remove.
- [x] 3. **Update `bin/config.py`**:
   - Replace `_load_config_yaml()` → `_load_config_xml()` using `xml.etree.ElementTree` (stdlib only, no new deps).
   - Keep `_CONFIG_YAML` dict name temporarily for compat but populate from XML.
   - Replace `config_to_yaml()` → `config_to_xml()` that writes pretty-printed XML with the XSD reference.
   - Update `CONFIG_SCHEMA` to emit XML comments instead of YAML inline comments.
   - Update `reload_config_yaml()` → `reload_config_xml()`.
   - Update `parse_args()`: `--config` now accepts `.xml` files.
- [x] 4. **Update `bin/wikioracle.py`**: all YAML references → XML (config endpoint reads/writes XML).
- [x] 5. **Update `client/config.js` and `client/util.js`**: config editor shows XML instead of YAML.
- [x] 6. **Update `Makefile`**: `WO_CHAT_EXTRA` changes from `config.yaml` to `config.xml`.
- [x] 7. **Update tests**: `test_prompt_bundle.py` and any test reading config.
- [x] 8. **Update docs**: `Architecture.md`, `Installation.md`, `Training.md` — all YAML references → XML.
9. **Validation**: Add `validate_config_xml(path)` that checks against the XSD at load time.


## No spacetime implies no worldline capture.
- News facts (direct perception) need a place and time (so we should add a <place> attribute in addition to the currently existing <time>) Both exist on<facts> and <feelings> as optional.
- Knowledge facts (inferential cognitions) do not, but in order to say anything about the world, they must be applied to news.
- The server keeps truth, but in keeping news facts, there is risk because of direct involvement in the worldlines (panopticon as magic destroyer). So it is better to keep only knowledge facts, and to have news facts contributed by the user on a per-session basis (that means keeping facts that are independent of space and time).
- There is already some theory for this: Zero-Knowledge and Selective Disclosure vs Identity. In systems which rely on identity to make decisions, it is better to determine the location of a space in which an individual occupies rather than a point which identifies them. So don't base my credit rating on an ID: base it on a question (do you have more than x dollars?). Don't ask me when I was born: verify only that I am above a certain age (are you over 21?). These questions are not just rhetoric: they have to do with constraining an observed object to be point-based instead of allowing it some space of freedom within which to operate. And point-based observation kills magic, which is what forces magical people to try to move about from one point to another within an overly-constrained system that does not understand spirituality.
- Feelings should not have a trust attribute, and they are not used in training the model. They are orthogonal to truth, so ternary truth values correspond to true/false/both, and feeling=neither: please update tetralemm and ternary ogic sections of the doc appropriately. Poetry is an example of feeling content.
- We should have a check in the server for idenitifying information. For example, we can strip the Place and Time attributes of a fact, but there still might be exposure of identifying information: <feeling> sadness correlates with sleep deprivation </feeling> is allowed, but <feeling> user123 felt sad at 9:14 PM in Seattle </feeling> needs to be disallowed, becuase it collapses on identity.

### Plan
1. **Fact classification** (`bin/truth.py`):
   - Add `<place>` as an optional attribute on `<fact>` and `<feeling>` tags (alongside existing `spacetime`/`trust`).
   - Introduce a `fact_kind` attribute: `"news"` (spatiotemporally bound, direct perception) vs `"knowledge"` (inferential, universal).
   - `_normalize_trust_entry()`: parse and preserve `place` and `fact_kind` attributes.
   - `is_news_fact(entry)` → True if the entry has non-empty `place` or `time` attributes that are not `[unverified]`.
   - `is_knowledge_fact(entry)` → True if no spatiotemporal binding.

2. **Server-side filtering** (`bin/truth.py` + `bin/response.py`):
   - In the online training merge (Stage 3), only merge **knowledge facts** into the server truth table. News facts are session-only.
   - Add `filter_knowledge_only(entries)` that strips news facts before server-side persistence.
   - In `_normalize_trust_entry()`: if entry is a `<feeling>`, remove the `trust` attribute (set to `None` / omit from serialization). Feelings are orthogonal to truth.

3. **Feeling semantics** (`bin/sensation.py`):
   - `_wrap_feeling()` no longer emits `trust=` attribute.
   - `_extract_facts()` skips feelings entirely (no truth records from feelings).
   - Update `tag_message()`: feelings get no trust/spacetime attributes.

4. **PII / identity collapse detection** (`bin/truth.py`):
   - Add `detect_identity_collapse(content: str) -> bool` that scans for PII patterns:
     - Usernames / handles (`user123`, `@handle`)
     - Specific times (`9:14 PM`, `2026-03-05T...`)
     - Specific places (city names from a small gazetteer, GPS coords, street addresses)
     - Email addresses, phone numbers, IP addresses
   - In `_normalize_trust_entry()`: if `detect_identity_collapse(content)` is True for a feeling, reject/flag the entry.
   - In the `/chat` pipeline: strip or warn on entries that collapse identity.

5. **Documentation updates**:
   - `doc/BuddhistLogic.md`: update tetralemma table — True/False/Both map to ternary truth, Neither = feeling (orthogonal).
   - `doc/Logic.md`: add section on feelings being outside the truth lattice.
   - `doc/Training.md`: document that feelings are excluded from training, news facts are session-only, only knowledge facts persist.
   - `doc/WhatIsTruth.md`: add section on spacetime binding and identity collapse.

6. **Tests** (`test/test_spacetime.py`):
   - Test `is_news_fact()` / `is_knowledge_fact()` classification.
   - Test `detect_identity_collapse()` with positive/negative examples.
   - Test that feelings have no trust attribute after normalization.
   - Test that server truth merge filters out news facts.


## Create ./openclaw submodule to use as a "front-end" that talks to WikiOracle via ./bin/wo.py
- OpenClaw receives a message (Slack/Discord/Telegram/etc.).
- OpenClaw forwards the user message to WikiOracle's /chat endpoint.
- WikiOracle does its normal truth/RAG/voting pipeline and calls NanoChat upstream.
- NanoChat does online learning by next word prediction on the QUERY, and delivers a response.
- OpenClaw relays the final answer back to the originating channel.
- Benefit: OpenClaw adds distribution + "always-on assistant" ergonomics, while WikiOracle continues to own truth/state and NanoChat continues to be the model.

### Plan
1. **Create `./openclaw/` directory** with its own `README.md`, `requirements.txt`, `config.xml`, and Python package structure.
2. **Core bridge** (`openclaw/bridge.py`):
   - `WikiOracleBridge` class wrapping `bin/wo` functionality: connects to a WikiOracle server URL, sends messages via `POST /chat`, manages session state (JSONL file per channel/user).
   - Stateless by default (sends state with each request); optionally stateful.
3. **Channel adapters** (plugin pattern):
   - `openclaw/adapters/slack.py` — Slack Bot (slack_bolt)
   - `openclaw/adapters/discord.py` — Discord Bot (discord.py)
   - `openclaw/adapters/telegram.py` — Telegram Bot (python-telegram-bot)
   - Each adapter: receive message → call `bridge.send(message, channel_id, user_id)` → relay response.
4. **Configuration** (`openclaw/config.xml`):
   - WikiOracle server URL, API token, channel adapter settings, per-channel state file paths.
5. **Entry point** (`openclaw/__main__.py`):
   - CLI: `python -m openclaw --adapter slack` (or discord/telegram).
   - Loads config, instantiates bridge + adapter, runs event loop.
6. **Git submodule**: `git submodule add` to register `./openclaw` as a submodule pointing to a new GitHub repo.
7. **Makefile additions**: `openclaw-setup`, `openclaw-run` targets.
8. **Documentation**: `doc/OpenClaw.md` describing the architecture and setup.


## Second Round Corrections

### XML State Migration
- State files (state.xml, etc.) should ALSO use XML, not just config.
- Specification name: "WikiOracle State" (with XSD schema at `data/state.xsd`).
- All fields in config XSD should be required (remove `minOccurs="0"`).
- Specification name for config: "WikiOracle Config".
- Conversations nest naturally in XML (no flatten/unflatten needed).

### Spacetime Corrections
- `<place>` and `<time>` should be **child elements** (not attributes) on both `<fact>` and `<feeling>`.
- There is no `<spacetime>` attribute — remove it entirely.
- There is no `kind` attribute on `<fact>` — remove `fact_kind`.
- Only `<fact>` has a `trust` attribute; `<feeling>` never does.
- `is_news()` and `is_knowledge()` apply to both facts and feelings. They check XHTML content for `<place>`/`<time>` child elements or content that identifies spatiotemporal binding.
- Valid XML feelings never have trust, so normalization should not need to strip it.
- Correct XML structure:
  ```xml
  <fact trust="0.5"><place>Paris</place><time>2026-03-05</time>The event occurred</fact>
  <feeling><place>London</place>A sense of wonder</feeling>
  ```

### OpenClaw Corrections
- `./openclaw` is a **git submodule** at `https://github.com/openclaw/openclaw.git`, NOT inline code.
- Follows the same pattern as `./nanochat` (see `.gitmodules`).
- Integration files go in `./bin/openclaw_ext.py`, NOT inside the openclaw directory.
- Delete all inline openclaw files created in round 1.
