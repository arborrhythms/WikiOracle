#!/usr/bin/env python3
"""Tests for prompt_bundle module: PromptBundle, adapters, and RAG ranking."""

import sys
import unittest
from pathlib import Path

# Ensure bin/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

from prompt_bundle import (
    DEFAULT_OUTPUT,
    PromptBundle,
    Source,
    _build_provider_query_bundle,
    build_prompt_bundle,
    evaluate_providers,
    rank_retrieval_entries,
    to_anthropic_payload,
    to_nanochat_messages,
    to_openai_messages,
)
from wikioracle_state import SCHEMA_URL


def _make_state(**overrides):
    """Create a minimal valid v2 state dict."""
    base = {
        "version": 2,
        "schema": SCHEMA_URL,
        "time": "2026-02-23T00:00:00Z",
        "context": "<div>You are a helpful assistant.</div>",
        "conversations": [],
        "selected_conversation": None,
        "truth": {"trust": []},
    }
    base.update(overrides)
    return base


def _make_trust_entry(title, certainty, content="Some fact", entry_id="", time=""):
    entry = {
        "title": title,
        "certainty": certainty,
        "content": f"<p>{content}</p>",
    }
    if entry_id:
        entry["id"] = entry_id
    if time:
        entry["time"] = time
    return entry


# ---------------------------------------------------------------------------
# PromptBundle construction
# ---------------------------------------------------------------------------
class TestBuildPromptBundle(unittest.TestCase):
    """Test build_prompt_bundle() produces correct bundles."""

    def test_basic_bundle(self):
        state = _make_state()
        bundle = build_prompt_bundle(state, "Hello!", {})
        self.assertIsInstance(bundle, PromptBundle)
        self.assertEqual(bundle.query, "Hello!")
        self.assertEqual(bundle.system, "You are a helpful assistant.")
        self.assertEqual(bundle.history, [])
        self.assertEqual(bundle.sources, [])
        self.assertEqual(bundle.output, "")

    def test_empty_context(self):
        state = _make_state(context="")
        bundle = build_prompt_bundle(state, "Hi", {})
        self.assertEqual(bundle.system, "")

    def test_rag_sources_populated(self):
        trust = [
            _make_trust_entry("Doc A", 0.9, "Fact A", "t1"),
            _make_trust_entry("Doc B", 0.5, "Fact B", "t2"),
        ]
        state = _make_state(truth={"trust": trust})
        bundle = build_prompt_bundle(state, "query", {"tools": {"rag": True}})
        self.assertEqual(len(bundle.sources), 2)
        self.assertEqual(bundle.sources[0].title, "Doc A")
        self.assertGreaterEqual(bundle.sources[0].certainty, bundle.sources[1].certainty)

    def test_rag_disabled(self):
        trust = [_make_trust_entry("Doc", 0.9)]
        state = _make_state(truth={"trust": trust})
        bundle = build_prompt_bundle(state, "q", {"tools": {"rag": False}})
        self.assertEqual(len(bundle.sources), 0)

    def test_min_certainty_filter(self):
        trust = [
            _make_trust_entry("High", 0.9, entry_id="t1"),
            _make_trust_entry("Low", 0.3, entry_id="t2"),
        ]
        state = _make_state(truth={"trust": trust})
        bundle = build_prompt_bundle(state, "q", {"tools": {"rag": True}, "retrieval": {"min_certainty": 0.5}})
        self.assertEqual(len(bundle.sources), 1)
        self.assertEqual(bundle.sources[0].title, "High")

    def test_history_windowing(self):
        """History should be limited to message_window."""
        convs = [{
            "id": "c1",
            "title": "Test",
            "messages": [
                {"role": "user", "content": f"<p>msg {i}</p>"}
                for i in range(50)
            ],
            "children": [],
        }]
        state = _make_state(conversations=convs)
        bundle = build_prompt_bundle(
            state, "new query", {"message_window": 10},
            conversation_id="c1",
        )
        self.assertEqual(len(bundle.history), 10)

    def test_transient_snippets(self):
        state = _make_state()
        snippets = [{"source": "GPT-4", "certainty": 0.8, "content": "Some answer"}]
        bundle = build_prompt_bundle(state, "q", {}, transient_snippets=snippets)
        self.assertEqual(len(bundle.transient_sources), 1)
        self.assertEqual(bundle.transient_sources[0].title, "GPT-4")

    def test_provider_entries_excluded_from_sources(self):
        """Trust entries with <provider> blocks should NOT appear in sources."""
        trust = [
            _make_trust_entry("Normal", 0.9, "Normal fact", "t1"),
            {"title": "LLM Provider", "certainty": 0.95, "id": "t2",
             "content": "<provider><name>GPT-4</name><api_url>https://api.openai.com</api_url></provider>"},
        ]
        state = _make_state(truth={"trust": trust})
        bundle = build_prompt_bundle(state, "q", {"tools": {"rag": True}})
        titles = [s.title for s in bundle.sources]
        self.assertIn("Normal", titles)
        self.assertNotIn("LLM Provider", titles)


# ---------------------------------------------------------------------------
# RAG ranking
# ---------------------------------------------------------------------------
class TestRankRetrievalEntries(unittest.TestCase):
    """Test rank_retrieval_entries with different weights."""

    def test_certainty_only(self):
        entries = [
            _make_trust_entry("Low", 0.3, entry_id="e1"),
            _make_trust_entry("High", 0.9, entry_id="e2"),
            _make_trust_entry("Mid", 0.6, entry_id="e3"),
        ]
        ranked = rank_retrieval_entries(entries, {"certainty_weight": 1.0, "recency_weight": 0.0})
        self.assertEqual(ranked[0]["title"], "High")
        self.assertEqual(ranked[1]["title"], "Mid")
        self.assertEqual(ranked[2]["title"], "Low")

    def test_max_entries_limit(self):
        entries = [_make_trust_entry(f"E{i}", 0.5 + i * 0.01, entry_id=f"e{i}") for i in range(20)]
        ranked = rank_retrieval_entries(entries, {"max_entries": 5})
        self.assertEqual(len(ranked), 5)

    def test_min_certainty(self):
        entries = [
            _make_trust_entry("Keep", 0.8, entry_id="e1"),
            _make_trust_entry("Drop", 0.2, entry_id="e2"),
        ]
        ranked = rank_retrieval_entries(entries, {"min_certainty": 0.5})
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["title"], "Keep")

    def test_excludes_providers(self):
        entries = [
            _make_trust_entry("Fact", 0.9, "plain fact", "e1"),
            {"title": "Provider", "certainty": 0.95, "id": "e2",
             "content": "<provider><name>X</name></provider>"},
        ]
        ranked = rank_retrieval_entries(entries, {}, exclude_providers=True)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["title"], "Fact")

    def test_excludes_srcs(self):
        entries = [
            _make_trust_entry("Fact", 0.9, "plain", "e1"),
            {"title": "File", "certainty": 0.95, "id": "e2",
             "content": "<src><path>file://test.txt</path></src>"},
        ]
        ranked = rank_retrieval_entries(entries, {}, exclude_srcs=True)
        self.assertEqual(len(ranked), 1)

    def test_deterministic_tiebreaking(self):
        """Entries with the same certainty should have deterministic ordering."""
        entries = [
            _make_trust_entry("A", 0.8, entry_id="e_a", time="2026-01-02T00:00:00Z"),
            _make_trust_entry("B", 0.8, entry_id="e_b", time="2026-01-01T00:00:00Z"),
        ]
        ranked1 = rank_retrieval_entries(entries, {"certainty_weight": 1.0, "recency_weight": 0.0})
        ranked2 = rank_retrieval_entries(entries, {"certainty_weight": 1.0, "recency_weight": 0.0})
        self.assertEqual([r["title"] for r in ranked1], [r["title"] for r in ranked2])


# ---------------------------------------------------------------------------
# OpenAI adapter
# ---------------------------------------------------------------------------
class TestToOpenAIMessages(unittest.TestCase):
    """Test to_openai_messages() output."""

    def test_system_message_present(self):
        bundle = PromptBundle(system="You are helpful.", query="Hi")
        msgs = to_openai_messages(bundle)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("You are helpful.", msgs[0]["content"])

    def test_no_system_when_empty(self):
        bundle = PromptBundle(system="", query="Hi", output="")
        msgs = to_openai_messages(bundle)
        # First message should be user, not system
        self.assertEqual(msgs[0]["role"], "user")

    def test_context_in_system_not_fake_turns(self):
        """Context must be in system message, NOT as fake user/assistant exchange."""
        bundle = PromptBundle(system="Project rules here.", query="Hi")
        msgs = to_openai_messages(bundle)
        # Check no "[Context]" fake turn exists
        for m in msgs:
            if m["role"] == "user":
                self.assertNotIn("[Context]", m["content"])
        # System should have the context
        system_msgs = [m for m in msgs if m["role"] == "system"]
        self.assertTrue(len(system_msgs) == 1)
        self.assertIn("Project rules here.", system_msgs[0]["content"])

    def test_history_preserved(self):
        bundle = PromptBundle(
            query="latest?",
            history=[
                {"role": "user", "content": "First"},
                {"role": "assistant", "content": "Reply"},
            ],
            output="",
        )
        msgs = to_openai_messages(bundle)
        roles = [m["role"] for m in msgs]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)
        # History should come before the final query
        user_msgs = [m for m in msgs if m["role"] == "user"]
        self.assertEqual(user_msgs[-1]["content"], "latest?")

    def test_sources_in_final_user_message(self):
        bundle = PromptBundle(
            query="What?",
            sources=[Source("t1", "Doc A", 0.9, "fact content")],
            output="",
        )
        msgs = to_openai_messages(bundle)
        final_user = [m for m in msgs if m["role"] == "user"][-1]
        self.assertIn("[Reference Documents]", final_user["content"])
        self.assertIn("Doc A", final_user["content"])
        self.assertIn("What?", final_user["content"])

    def test_output_format_in_system(self):
        bundle = PromptBundle(system="ctx", query="q", output="Format: answer + evidence")
        msgs = to_openai_messages(bundle)
        system = msgs[0]
        self.assertIn("Format: answer + evidence", system["content"])


# ---------------------------------------------------------------------------
# Anthropic adapter
# ---------------------------------------------------------------------------
class TestToAnthropicPayload(unittest.TestCase):
    """Test to_anthropic_payload() output."""

    def test_system_field(self):
        bundle = PromptBundle(system="You are helpful.", query="Hi")
        payload = to_anthropic_payload(bundle)
        self.assertIn("system", payload)
        self.assertIn("You are helpful.", payload["system"])

    def test_no_system_when_empty(self):
        bundle = PromptBundle(system="", query="Hi", output="")
        payload = to_anthropic_payload(bundle)
        self.assertNotIn("system", payload)

    def test_messages_alternate(self):
        """Anthropic requires strict user/assistant alternation."""
        bundle = PromptBundle(
            query="end",
            history=[
                {"role": "user", "content": "A"},
                {"role": "user", "content": "B"},  # consecutive same role
                {"role": "assistant", "content": "C"},
            ],
        )
        payload = to_anthropic_payload(bundle)
        msgs = payload["messages"]
        for i in range(1, len(msgs)):
            self.assertNotEqual(msgs[i]["role"], msgs[i - 1]["role"],
                                f"Consecutive same role at index {i}: {msgs[i-1]['role']}")

    def test_first_message_is_user(self):
        bundle = PromptBundle(
            query="end",
            history=[{"role": "assistant", "content": "first"}],
        )
        payload = to_anthropic_payload(bundle)
        self.assertEqual(payload["messages"][0]["role"], "user")

    def test_model_and_temperature(self):
        bundle = PromptBundle(query="q")
        payload = to_anthropic_payload(bundle, model="claude-test", temperature=0.5)
        self.assertEqual(payload["model"], "claude-test")
        self.assertEqual(payload["temperature"], 0.5)

    def test_context_in_system_not_messages(self):
        """Context should be in system field, not in messages."""
        bundle = PromptBundle(system="Project context", query="q")
        payload = to_anthropic_payload(bundle)
        # System field should have context
        self.assertIn("Project context", payload["system"])
        # Messages should NOT have "[Context]" prefix
        for m in payload["messages"]:
            self.assertNotIn("[Context]", m["content"])


# ---------------------------------------------------------------------------
# NanoChat adapter
# ---------------------------------------------------------------------------
class TestToNanochatMessages(unittest.TestCase):
    """Test to_nanochat_messages() output."""

    def test_context_as_first_user_message(self):
        bundle = PromptBundle(system="Rules", query="Hi")
        msgs = to_nanochat_messages(bundle)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertIn("[Context] Rules", msgs[0]["content"])
        self.assertEqual(msgs[1]["role"], "assistant")

    def test_no_context_no_preamble(self):
        bundle = PromptBundle(system="", query="Hi", output="", sources=[])
        msgs = to_nanochat_messages(bundle)
        # Should just be the query with no preamble pair
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["content"], "Hi")

    def test_history_after_preamble(self):
        bundle = PromptBundle(
            system="ctx",
            query="end",
            history=[
                {"role": "user", "content": "prev"},
                {"role": "assistant", "content": "reply"},
            ],
        )
        msgs = to_nanochat_messages(bundle)
        # Should be: preamble user, preamble assistant, prev user, reply assistant, end user
        self.assertEqual(len(msgs), 5)
        self.assertEqual(msgs[2]["content"], "prev")
        self.assertEqual(msgs[3]["content"], "reply")
        self.assertEqual(msgs[4]["content"], "end")

    def test_sources_in_preamble(self):
        bundle = PromptBundle(
            system="ctx",
            query="q",
            sources=[Source("t1", "Doc", 0.9, "content")],
        )
        msgs = to_nanochat_messages(bundle)
        preamble = msgs[0]["content"]
        self.assertIn("[Reference Documents]", preamble)
        self.assertIn("Doc", preamble)


# ---------------------------------------------------------------------------
# Adapter parity
# ---------------------------------------------------------------------------
class TestAdapterParity(unittest.TestCase):
    """Verify semantic parity across provider adapters."""

    def _make_full_bundle(self):
        return PromptBundle(
            system="Project rules",
            history=[
                {"role": "user", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
            ],
            sources=[Source("t1", "Policy", 0.93, "Policy content")],
            transient_sources=[Source("t2", "GPT", 0.8, "GPT says...")],
            query="How should we implement X?",
            output="Answer with evidence.",
        )

    def test_all_adapters_include_context(self):
        bundle = self._make_full_bundle()

        oai_msgs = to_openai_messages(bundle)
        anth_payload = to_anthropic_payload(bundle)
        nano_msgs = to_nanochat_messages(bundle)

        # OpenAI: system message has context
        system = [m for m in oai_msgs if m["role"] == "system"]
        self.assertTrue(any("Project rules" in m["content"] for m in system))

        # Anthropic: system field has context
        self.assertIn("Project rules", anth_payload.get("system", ""))

        # NanoChat: first user message has context
        self.assertIn("Project rules", nano_msgs[0]["content"])

    def test_all_adapters_include_query(self):
        bundle = self._make_full_bundle()

        oai_msgs = to_openai_messages(bundle)
        anth_msgs = to_anthropic_payload(bundle)["messages"]
        nano_msgs = to_nanochat_messages(bundle)

        # Query should be in the last user message of each
        oai_last_user = [m for m in oai_msgs if m["role"] == "user"][-1]
        self.assertIn("How should we implement X?", oai_last_user["content"])

        anth_last_user = [m for m in anth_msgs if m["role"] == "user"][-1]
        self.assertIn("How should we implement X?", anth_last_user["content"])

        nano_last_user = [m for m in nano_msgs if m["role"] == "user"][-1]
        self.assertIn("How should we implement X?", nano_last_user["content"])

    def test_all_adapters_include_sources(self):
        bundle = self._make_full_bundle()

        oai_msgs = to_openai_messages(bundle)
        anth_msgs = to_anthropic_payload(bundle)["messages"]
        nano_msgs = to_nanochat_messages(bundle)

        def _has_policy(msgs):
            return any("Policy" in m["content"] for m in msgs)

        self.assertTrue(_has_policy(oai_msgs))
        self.assertTrue(_has_policy(anth_msgs))
        self.assertTrue(_has_policy(nano_msgs))

    def test_all_adapters_include_history(self):
        bundle = self._make_full_bundle()

        oai_msgs = to_openai_messages(bundle)
        anth_msgs = to_anthropic_payload(bundle)["messages"]
        nano_msgs = to_nanochat_messages(bundle)

        def _has_first_question(msgs):
            return any("First question" in m["content"] for m in msgs)

        self.assertTrue(_has_first_question(oai_msgs))
        self.assertTrue(_has_first_question(anth_msgs))
        self.assertTrue(_has_first_question(nano_msgs))


# ---------------------------------------------------------------------------
# HME: provider evaluation
# ---------------------------------------------------------------------------
class TestBuildProviderQueryBundle(unittest.TestCase):
    """Test _build_provider_query_bundle creates a RAG-free bundle."""

    def test_no_sources(self):
        bundle = _build_provider_query_bundle("ctx", [], "question", "output fmt")
        self.assertEqual(bundle.system, "ctx")
        self.assertEqual(bundle.query, "question")
        self.assertEqual(bundle.output, "output fmt")
        self.assertEqual(bundle.sources, [])
        self.assertEqual(bundle.transient_sources, [])

    def test_history_copied(self):
        hist = [{"role": "user", "content": "prev"}]
        bundle = _build_provider_query_bundle("", hist, "q", "")
        self.assertEqual(len(bundle.history), 1)
        # Verify it's a copy, not the same list
        bundle.history.append({"role": "assistant", "content": "added"})
        self.assertEqual(len(hist), 1)



class TestEvaluateProviders(unittest.TestCase):
    """Test evaluate_providers() HME evaluation."""

    def _make_provider_entry(self, name, certainty=0.8, entry_id="t1"):
        entry = {"id": entry_id, "title": name, "certainty": certainty,
                 "time": "2026-02-23T00:00:00Z"}
        config = {"name": name, "api_url": "http://test", "api_key": "k",
                  "model": "m", "timeout": 30, "max_tokens": 1024}
        return (entry, config)

    def test_single_provider_success(self):
        def mock_call(pconfig, messages):
            return f"Response from {pconfig['name']}"
        pairs = [self._make_provider_entry("GPT-4")]
        results = evaluate_providers(
            pairs, "system", [], "question", "output", mock_call,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].kind, "provider")
        self.assertEqual(results[0].title, "GPT-4")
        self.assertIn("Response from GPT-4", results[0].content)
        self.assertIn('<div class="provider-response"', results[0].content)
        self.assertIn('data-provider="GPT-4"', results[0].content)

    def test_multiple_providers_parallel(self):
        def mock_call(pconfig, messages):
            return f"Answer from {pconfig['name']}"
        pairs = [
            self._make_provider_entry("Claude", 0.9, "t1"),
            self._make_provider_entry("GPT", 0.8, "t2"),
        ]
        results = evaluate_providers(
            pairs, "ctx", [], "q", "out", mock_call,
        )
        self.assertEqual(len(results), 2)
        names = {r.title for r in results}
        self.assertEqual(names, {"Claude", "GPT"})

    def test_error_response_excluded(self):
        def mock_call(pconfig, messages):
            return "[Error: HTTP 500] server error"
        pairs = [self._make_provider_entry("GPT")]
        results = evaluate_providers(
            pairs, "", [], "q", "", mock_call,
        )
        self.assertEqual(len(results), 0)

    def test_exception_excluded(self):
        def mock_call(pconfig, messages):
            raise ConnectionError("timeout")
        pairs = [self._make_provider_entry("GPT")]
        results = evaluate_providers(
            pairs, "", [], "q", "", mock_call,
        )
        self.assertEqual(len(results), 0)

    def test_empty_providers(self):
        results = evaluate_providers(
            [], "", [], "q", "", lambda p, m: "nope",
        )
        self.assertEqual(results, [])

    def test_certainty_preserved(self):
        def mock_call(pconfig, messages):
            return "ok"
        pairs = [self._make_provider_entry("P", certainty=0.95)]
        results = evaluate_providers(
            pairs, "", [], "q", "", mock_call,
        )
        self.assertAlmostEqual(results[0].certainty, 0.95)

    def test_rag_free_messages(self):
        """Verify the messages sent to providers contain no RAG sources."""
        captured = {}
        def mock_call(pconfig, messages):
            captured["messages"] = messages
            return "ok"
        pairs = [self._make_provider_entry("P")]
        evaluate_providers(
            pairs, "system ctx", [], "my question", "output fmt", mock_call,
        )
        msgs = captured["messages"]
        full_text = " ".join(m["content"] for m in msgs)
        self.assertIn("system ctx", full_text)
        self.assertIn("my question", full_text)
        self.assertNotIn("[Reference Documents]", full_text)
        self.assertNotIn("[Provider Consultations]", full_text)


class TestProviderSourcesInBundle(unittest.TestCase):
    """Test that provider_sources are included in build_prompt_bundle."""

    def test_provider_sources_appear_in_bundle(self):
        provider_src = Source(
            source_id="t_prov",
            title="Claude",
            certainty=0.9,
            content='<div class="provider-response">Claude says yes</div>',
            kind="provider",
        )
        state = _make_state()
        bundle = build_prompt_bundle(
            state, "query", {"tools": {"rag": False}},
            provider_sources=[provider_src],
        )
        self.assertEqual(len(bundle.sources), 1)
        self.assertEqual(bundle.sources[0].kind, "provider")
        self.assertEqual(bundle.sources[0].title, "Claude")

    def test_provider_sources_alongside_rag(self):
        provider_src = Source(
            source_id="t_prov", title="GPT", certainty=0.85,
            content='<div class="provider-response">GPT says</div>',
            kind="provider",
        )
        trust = [_make_trust_entry("Fact A", 0.9, "Some fact", "t1")]
        state = _make_state(truth={"trust": trust})
        bundle = build_prompt_bundle(
            state, "q", {"tools": {"rag": True}},
            provider_sources=[provider_src],
        )
        kinds = [s.kind for s in bundle.sources]
        self.assertIn("fact", kinds)
        self.assertIn("provider", kinds)

    def test_provider_sources_in_adapter_output(self):
        """Provider sources should appear in all adapter outputs."""
        provider_src = Source(
            source_id="t_prov", title="Claude-resp", certainty=0.9,
            content='<div class="provider-response">Answer: 42</div>',
            kind="provider",
        )
        bundle = PromptBundle(
            system="ctx", query="q",
            sources=[provider_src],
        )
        oai = to_openai_messages(bundle)
        anth = to_anthropic_payload(bundle)["messages"]
        nano = to_nanochat_messages(bundle)

        def _has_provider(msgs):
            return any("Claude-resp" in m["content"] for m in msgs)

        self.assertTrue(_has_provider(oai))
        self.assertTrue(_has_provider(anth))
        self.assertTrue(_has_provider(nano))


# ---------------------------------------------------------------------------
# Output resolution from state
# ---------------------------------------------------------------------------
class TestOutputResolution(unittest.TestCase):
    """Test that bundle.output resolves from state.output with fallback."""

    def test_default_output_is_empty(self):
        """DEFAULT_OUTPUT constant should be empty string."""
        self.assertEqual(DEFAULT_OUTPUT, "")

    def test_no_output_no_format(self):
        """No output and no output_format yields empty string."""
        state = _make_state()
        bundle = build_prompt_bundle(state, "q", {})
        self.assertEqual(bundle.output, "")

    def test_state_output_used_when_present(self):
        """When state.output is set, bundle uses it."""
        state = _make_state()
        state["output"] = "Return JSON only."
        bundle = build_prompt_bundle(state, "q", {})
        self.assertEqual(bundle.output, "Return JSON only.")

    def test_output_format_appended(self):
        """output_format from prefs is appended as a line."""
        state = _make_state()
        state["output"] = "Be concise."
        prefs = {"output_format": "XHTML"}
        bundle = build_prompt_bundle(state, "q", prefs)
        self.assertEqual(bundle.output, "Be concise.\noutput_format: XHTML")

    def test_output_format_nested_chat_appended(self):
        """Nested prefs.chat.output_format is accepted."""
        state = _make_state()
        state["output"] = "Be concise."
        prefs = {"chat": {"output_format": "JSON"}}
        bundle = build_prompt_bundle(state, "q", prefs)
        self.assertEqual(bundle.output, "Be concise.\noutput_format: JSON")

    def test_output_format_alone(self):
        """output_format works even when state output is empty."""
        state = _make_state()
        state["output"] = ""
        prefs = {"output_format": "XHTML"}
        bundle = build_prompt_bundle(state, "q", prefs)
        self.assertEqual(bundle.output, "output_format: XHTML")

    def test_empty_output_format_no_effect(self):
        """Empty output_format doesn't alter output."""
        state = _make_state()
        state["output"] = "Custom."
        prefs = {"output_format": ""}
        bundle = build_prompt_bundle(state, "q", prefs)
        self.assertEqual(bundle.output, "Custom.")

    def test_no_output_format_in_prefs(self):
        """Missing output_format in prefs doesn't alter output."""
        state = _make_state()
        state["output"] = "Custom."
        bundle = build_prompt_bundle(state, "q", {})
        self.assertEqual(bundle.output, "Custom.")


if __name__ == "__main__":
    unittest.main()
