# OpenClaw + MCP (Model Context Protocol)

This note summarizes **OpenClaw** and **MCP**, then sketches a few ways they could integrate with WikiOracle’s **NanoChat**-based runtime.

## OpenClaw (what it is)

OpenClaw is an open-source, self-hosted “gateway” for connecting messaging/chat apps to AI *agents* (especially coding agents). It’s designed to:

- Provide a single place to route conversations from multiple channels to one or more agent backends.
- Run agent backends via **ACP** (Agent Client Protocol), which OpenClaw uses to talk to coding harnesses (e.g., Codex/Claude Code-style CLIs) over a standard interface.
- Extend capabilities via “skills/tools” so the gateway can do more than just chat (e.g., call utilities, integrate with backends, or orchestrate workflows).

In short: **OpenClaw is the multi-channel “front door” + agent orchestration layer.**

References: [OpenClaw Docs](https://docs.openclaw.ai/), [OpenClaw (GitHub)](https://github.com/openclaw/openclaw)

## MCP (what it is)

The **Model Context Protocol (MCP)** is an open, vendor-neutral protocol for connecting an AI “host” (chat app, IDE assistant, agent runtime) to external *capabilities* in a consistent way.

MCP standardizes three key primitives:

- **Tools**: callable functions with structured inputs/outputs (side effects optional).
- **Resources**: read-only (or mostly read-only) data that can be fetched on demand.
- **Prompts**: reusable prompt templates/recipes exposed by a server.

Architecturally, MCP uses a **host ↔ client ↔ server** model (often speaking JSON-RPC) and supports multiple transports (commonly stdio for local servers, and HTTP variants for remote servers).

In short: **MCP is the interoperability layer for “tools + data + prompt packs”.**

Reference: [Model Context Protocol](https://modelcontextprotocol.io/)

## Where NanoChat fits in WikiOracle today

In this repo, NanoChat is the “upstream” LLM that WikiOracle talks to via an OpenAI-compatible chat-completions-style endpoint (see `bin/config.py`). WikiOracle then layers on its local-first state (`llm.jsonl`), trust table, authority imports, and voting/HME logic before returning an answer to the UI (see `doc/Architecture.md`).

So NanoChat is already a *provider backend*; OpenClaw and MCP mainly affect **how requests arrive** and **how external capabilities are attached**.

## Practical ways to tie OpenClaw + MCP into NanoChat here

### 1) Use OpenClaw as a “front-end” that talks to WikiOracle

If you want OpenClaw’s channel integrations and agent UX, one straightforward approach is:

1. OpenClaw receives a message (Slack/Discord/Telegram/etc.).
2. OpenClaw forwards the user message to WikiOracle’s `/chat` endpoint.
3. WikiOracle does its normal truth/RAG/voting pipeline and calls NanoChat upstream.
4. OpenClaw relays the final answer back to the originating channel.

Benefit: OpenClaw adds distribution + “always-on assistant” ergonomics, while WikiOracle continues to own truth/state and NanoChat continues to be the model.

### 2) Expose WikiOracle as an MCP server (so agents can *use* it as a tool)

Instead of treating WikiOracle only as a chat endpoint, you can treat it as a *capability server*:

- **MCP tools** could wrap WikiOracle operations like:
  - `wikioracle.ask(query, conversation_id, …)` → returns answer + citations/sources.
  - `wikioracle.add_truth(entry)` / `wikioracle.search_truth(query)` → manage trust entries.
  - `wikioracle.merge_state(file)` → merge imported `llm_*.jsonl` snapshots.
- **MCP resources** could expose read-only views like:
  - the current `llm.jsonl` header/context (sanitized),
  - a derived “trust graph” export,
  - resolved authority snapshots (cached).

Benefit: Any MCP-capable host (including an OpenClaw-deployed agent, an IDE assistant, or a local automation) can *query and update* WikiOracle’s truth/state in a controlled, auditable way, while NanoChat remains the underlying model.

### 3) Use MCP servers as “Authorities” (or authority-adjacent) inputs

WikiOracle already has an authority mechanism that imports remote truth tables and scales certainty. MCP can complement this by providing a standardized way to fetch structured knowledge from diverse backends (issue trackers, wikis, document stores, code search, etc.), then:

- Convert MCP resource/tool outputs into WikiOracle `<reference>` / `<fact>` entries.
- Treat MCP-backed sources as configurable “authorities” with explicit certainty and scope.

Benefit: Authority imports become less “custom integration per source” and more “plug in an MCP server.”

## A sane integration order (lowest risk first)

1. **Front-end first:** route OpenClaw → WikiOracle `/chat` (no new execution surface area).
2. **Read-only MCP:** add MCP resources/tools that only *read* WikiOracle state/truth.
3. **Write MCP with guardrails:** allow adds/edits/merges behind explicit user consent + strong local-only defaults.

This keeps WikiOracle’s local-first and security posture intact while still letting OpenClaw/MCP add agentic ergonomics around NanoChat.

