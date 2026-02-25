# TODO

## Logical Inference
Test hme.jsonl

## Code Review Feedback (Uncommitted Changes)

### P0 (must fix before release)
1. Stateless chat sends optimistic UI mutations back to server, causing duplicated user turns and orphan optimistic conversations.
   - Client mutates `state` before request and then includes it in `chatBody.state`: `html/wikioracle.js:759`, `html/wikioracle.js:813`.
   - Server then appends another user+assistant turn to that already-mutated state: `WikiOracle.py:948`, `WikiOracle.py:949`, `WikiOracle.py:972`.
   - New-root path is worst: temporary optimistic root is preserved and a second real root is created.

### P1 (high priority)
1. Stateless provider contract is incomplete: runtime config/provider keys are not used for OpenAI/Anthropic calls.
   - Chat captures `runtime_config` but does not pass provider API keys into `_call_provider`: `WikiOracle.py:826`, `WikiOracle.py:915`.
   - `_call_provider` still depends on global `PROVIDERS` and returns no-key errors in stateless mode: `WikiOracle.py:407`, `WikiOracle.py:417`, `WikiOracle.py:427`.
   - Result: stateless clients cannot reliably use client-owned provider credentials.

2. localStorage -> sessionStorage migration drops existing client data.
   - Reads are now sessionStorage-only for state/config: `html/wikioracle.js:50`, `html/wikioracle.js:141`.
   - Migration helper checks old prefs in sessionStorage, not localStorage: `html/wikioracle.js:88`.
   - Existing users with data only in localStorage will appear to lose state/config on upgrade.

### P2 (should fix)
1. Stateless import merge semantics diverge from server merge and can silently skip imported updates.
   - Stateless import uses `_clientMerge`: `html/wikioracle.js:1431`.
   - `_clientMerge` only appends missing root conversations and does not perform collision-safe/tree-aware merging: `html/wikioracle.js:170`, `html/wikioracle.js:177`.

2. `/bootstrap` increases key-exposure surface by returning parsed/raw config content.
   - Endpoint returns `config_yaml` and `parsed` directly: `WikiOracle.py:730`, `WikiOracle.py:738`.
   - If disk config contains provider secrets, bootstrap leaks them to any same-origin script context.

3. New `spec/hme.jsonl` provider example does not match current parser shape.
   - Spec uses attribute-style `<provider ... />`: `spec/hme.jsonl:13`.
   - Parser expects child tags (`<name>`, `<api_url>`, etc.): `bin/wikioracle_state.py:1009`, `bin/wikioracle_state.py:1020`.
   - This sample likely resolves to `"unknown"` provider with empty URL/model.

4. Consolidated simulator script appears v1-only and may not reflect v2 conversation records.
   - Parser only ingests `type === "message"` records: `html/test.js:33`.
   - Current exported files are conversation-based (`type: "conversation"`), so tooling can report empty/incorrect views.

### P3 (cleanup/docs)
1. `html/README.md` is stale after script consolidation.
   - References deleted scripts (`simulate_rendering.js`, `show_conversations.js`, etc.): `html/README.md:34`, `html/README.md:39`.
   - Should document `html/test.js` command usage instead.
