#!/usr/bin/env python3
"""Unit tests for bin/sensation.py — Korzybski IS detection, XML tagging,
feeling stripping, and SFT corpus preparation.

These are pure-Python tests that do NOT require torch, NanoChat, or a running
server.  They exercise the Sensation preprocessing pipeline end-to-end.

Run via:
    python3 -m pytest test/test_sensation_preprocessing.py -v
    # or: make test_unit
"""

import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

# Ensure bin/ is on the path for direct imports
_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project / "bin"))

from sensation import (
    classify_statement,
    detect_is_type,
    is_subjective,
    tag_message,
    preprocess_training_example,
    strip_feelings_from_training,
    preprocess_conversation,
    prepare_sft_corpus,
    _split_sentences,
    _wrap_fact,
    _wrap_feeling,
)


# =====================================================================
#  Korzybski IS detection
# =====================================================================

class TestDetectIsType(unittest.TestCase):
    """detect_is_type() should classify IS-pattern subtypes."""

    def test_identity(self):
        """'X is a Y' → identity."""
        self.assertEqual(detect_is_type("Socrates is a man"), "identity")

    def test_identity_are(self):
        """'X are Y' → identity."""
        self.assertEqual(detect_is_type("Cats are mammals"), "identity")

    def test_existence(self):
        """'There are N X' → existence."""
        self.assertEqual(detect_is_type("There are eight planets in our solar system"), "existence")

    def test_existence_is(self):
        """'There is X' → existence."""
        self.assertEqual(detect_is_type("There is a god"), "existence")

    def test_mereological_contains(self):
        """'X contains Y' → mereological."""
        self.assertEqual(detect_is_type("Water contains hydrogen"), "mereological")

    def test_mereological_part_of(self):
        """'X is part of Y' → mereological."""
        self.assertEqual(detect_is_type("The engine is part of the car"), "mereological")

    def test_quantity(self):
        """'X has N Y' → quantity."""
        self.assertEqual(detect_is_type("Earth has 1 moon"), "quantity")

    def test_definition(self):
        """'X is called Y' → definition."""
        self.assertEqual(detect_is_type("A polygon is called a triangle when it has 3 sides"), "definition")

    def test_definition_known_as(self):
        """'X is known as Y' → definition."""
        self.assertEqual(detect_is_type("It is known as the Mona Lisa"), "definition")

    def test_no_is_pattern(self):
        """Sentences without IS patterns → None."""
        self.assertIsNone(detect_is_type("Hello world"))

    def test_plain_verb(self):
        """Action sentences without IS → None."""
        self.assertIsNone(detect_is_type("She ran to the store"))


class TestClassifyStatement(unittest.TestCase):
    """classify_statement() top-level classifier."""

    def test_fact_identity(self):
        """IS-pattern with identity → ('fact', 'identity')."""
        tag_type, subtype = classify_statement("Paris is the capital of France.")
        self.assertEqual(tag_type, "fact")
        self.assertEqual(subtype, "identity")

    def test_feeling_question(self):
        """Questions → ('feeling', None)."""
        tag_type, subtype = classify_statement("What is the capital of France?")
        self.assertEqual(tag_type, "feeling")
        self.assertIsNone(subtype)

    def test_feeling_subjective(self):
        """Subjective markers override IS detection → ('feeling', None)."""
        tag_type, subtype = classify_statement("I think Paris is the capital of France.")
        self.assertEqual(tag_type, "feeling")
        self.assertIsNone(subtype)

    def test_feeling_hedged(self):
        """Hedged claims → ('feeling', None)."""
        tag_type, subtype = classify_statement("Maybe the earth is round.")
        self.assertEqual(tag_type, "feeling")
        self.assertIsNone(subtype)

    def test_feeling_meta_discourse(self):
        """Meta-discourse → ('feeling', None)."""
        tag_type, subtype = classify_statement("That's a great question!")
        self.assertEqual(tag_type, "feeling")
        self.assertIsNone(subtype)

    def test_feeling_empty(self):
        """Empty string → ('feeling', None)."""
        tag_type, subtype = classify_statement("")
        self.assertEqual(tag_type, "feeling")

    def test_fact_existence(self):
        """Existence pattern → ('fact', 'existence')."""
        tag_type, subtype = classify_statement("There are 206 bones in the human body.")
        self.assertEqual(tag_type, "fact")
        self.assertEqual(subtype, "existence")

    def test_fact_mereological(self):
        """Mereological pattern → ('fact', 'mereological')."""
        tag_type, subtype = classify_statement("DNA contains four nucleotide bases.")
        self.assertEqual(tag_type, "fact")
        self.assertEqual(subtype, "mereological")

    def test_no_is_pattern_feeling(self):
        """Sentences without IS and without subjective markers → ('feeling', None)."""
        tag_type, subtype = classify_statement("Hello there!")
        self.assertEqual(tag_type, "feeling")


class TestIsSubjective(unittest.TestCase):
    """is_subjective() hedging / subjective marker detection."""

    def test_i_think(self):
        self.assertTrue(is_subjective("I think it might rain."))

    def test_i_feel(self):
        self.assertTrue(is_subjective("I feel that this is wrong."))

    def test_maybe(self):
        self.assertTrue(is_subjective("Maybe we should go."))

    def test_probably(self):
        self.assertTrue(is_subjective("It is probably true."))

    def test_in_my_opinion(self):
        self.assertTrue(is_subjective("In my opinion, cats are better."))

    def test_not_subjective(self):
        self.assertFalse(is_subjective("The sky is blue."))


# =====================================================================
#  Sentence splitting
# =====================================================================

class TestSplitSentences(unittest.TestCase):
    """_split_sentences() boundary detection."""

    def test_single_sentence(self):
        result = _split_sentences("Hello world.")
        self.assertEqual(result, ["Hello world."])

    def test_two_sentences(self):
        result = _split_sentences("Hello world. This is a test.")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "Hello world.")
        self.assertEqual(result[1], "This is a test.")

    def test_question_and_statement(self):
        result = _split_sentences("Is it true? Yes it is.")
        self.assertEqual(len(result), 2)

    def test_empty_string(self):
        result = _split_sentences("")
        self.assertEqual(result, [])


# =====================================================================
#  XML tag wrapping
# =====================================================================

class TestWrapFact(unittest.TestCase):
    """_wrap_fact() XML tag construction."""

    def test_basic(self):
        result = _wrap_fact("The sky is blue.", trust=0.8)
        self.assertIn('<fact trust="0.8">', result)
        self.assertIn("The sky is blue.", result)
        self.assertIn("</fact>", result)

    def test_default_trust(self):
        result = _wrap_fact("Test.")
        self.assertIn('trust="0.5"', result)

    def test_with_place(self):
        result = _wrap_fact("The tower is tall.", place="Paris")
        self.assertIn("<place>Paris</place>", result)

    def test_with_time(self):
        result = _wrap_fact("It rained.", time="2024-01-01")
        self.assertIn("<time>2024-01-01</time>", result)

    def test_xml_escaping(self):
        """Ampersands and angle brackets are escaped."""
        result = _wrap_fact("A & B < C")
        self.assertIn("&amp;", result)
        self.assertIn("&lt;", result)


class TestWrapFeeling(unittest.TestCase):
    """_wrap_feeling() XML tag construction."""

    def test_basic(self):
        result = _wrap_feeling("I love this!")
        self.assertIn("<feeling>", result)
        self.assertIn("I love this!", result)
        self.assertIn("</feeling>", result)
        # Feelings have no trust attribute
        self.assertNotIn("trust=", result)

    def test_with_place_and_time(self):
        result = _wrap_feeling("Felt great.", place="Beach", time="Summer")
        self.assertIn("<place>Beach</place>", result)
        self.assertIn("<time>Summer</time>", result)


# =====================================================================
#  Message tagging
# =====================================================================

class TestTagMessage(unittest.TestCase):
    """tag_message() wraps content in <Q>/<R> with <fact>/<feeling> segments."""

    def test_user_message_wraps_in_Q(self):
        result = tag_message("Hello", "user")
        self.assertTrue(result.startswith("<Q>"))
        self.assertTrue(result.endswith("</Q>"))

    def test_assistant_message_wraps_in_R(self):
        result = tag_message("Hello", "assistant")
        self.assertTrue(result.startswith("<R>"))
        self.assertTrue(result.endswith("</R>"))

    def test_fact_detection(self):
        """IS-pattern sentences produce <fact> tags."""
        result = tag_message("Paris is the capital of France.", "assistant")
        self.assertIn("<fact", result)
        self.assertIn("trust=", result)

    def test_feeling_detection(self):
        """Questions and subjective markers produce <feeling> tags."""
        result = tag_message("How are you?", "user")
        self.assertIn("<feeling>", result)

    def test_mixed_content(self):
        """A message with both fact and feeling sentences."""
        content = "That's a great question! Paris is the capital of France."
        result = tag_message(content, "assistant")
        self.assertIn("<feeling>", result)
        self.assertIn("<fact", result)

    def test_empty_content(self):
        """Empty content produces a feeling wrapper."""
        result = tag_message("", "user")
        self.assertIn("<feeling>", result)

    def test_explicit_trust_override(self):
        """When trust is explicitly provided, ALL sentences become facts."""
        result = tag_message("I love cats. Maybe dogs too.", "user", trust=0.9)
        # Even subjective content should be wrapped as fact with explicit trust
        self.assertIn('trust="0.9"', result)
        # No feelings when trust is explicit
        self.assertNotIn("<feeling>", result)


# =====================================================================
#  Training example preprocessing
# =====================================================================

class TestPreprocessTrainingExample(unittest.TestCase):
    """preprocess_training_example() tags and strips feelings."""

    def test_basic_tagging(self):
        """Messages get XML-tagged."""
        messages = [
            {"role": "user", "content": "What is the capital of France?"},
            {"role": "assistant", "content": "Paris is the capital of France."},
        ]
        result = preprocess_training_example(messages, degree_of_truth=0.8)
        self.assertTrue(len(result) > 0)
        # All results should have role and content
        for msg in result:
            self.assertIn("role", msg)
            self.assertIn("content", msg)

    def test_feelings_stripped(self):
        """Feelings are removed from training examples (Entanglement policy)."""
        messages = [
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I think I'm doing well! Paris is the capital."},
        ]
        result = preprocess_training_example(messages, degree_of_truth=1.0)
        for msg in result:
            self.assertNotIn("<feeling>", msg["content"])
            self.assertNotIn("</feeling>", msg["content"])

    def test_fact_content_preserved(self):
        """Fact content survives feeling stripping."""
        messages = [
            {"role": "user", "content": "Tell me a fact."},
            {"role": "assistant", "content": "Water is composed of hydrogen and oxygen."},
        ]
        result = preprocess_training_example(messages, degree_of_truth=1.0)
        # At least one message should contain fact content
        has_fact = any("<fact" in msg["content"] for msg in result)
        self.assertTrue(has_fact, "Expected at least one <fact> tag to survive stripping")

    def test_empty_messages_after_stripping(self):
        """Messages that become empty after feeling stripping are removed."""
        messages = [
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm doing great!"},
        ]
        result = preprocess_training_example(messages, degree_of_truth=1.0)
        # All remaining messages should have non-empty content
        for msg in result:
            self.assertTrue(len(msg["content"].strip()) > 0)


# =====================================================================
#  Feeling stripping
# =====================================================================

class TestStripFeelingsFromTraining(unittest.TestCase):
    """strip_feelings_from_training() removes <feeling> blocks."""

    def test_removes_feeling_blocks(self):
        messages = [
            {"role": "assistant", "content": '<R><feeling>Great question!</feeling><fact trust="0.5">Paris is in France.</fact></R>'},
        ]
        result = strip_feelings_from_training(messages)
        self.assertEqual(len(result), 1)
        self.assertNotIn("<feeling>", result[0]["content"])
        self.assertIn("<fact", result[0]["content"])

    def test_removes_self_closing_feelings(self):
        messages = [
            {"role": "user", "content": '<Q><feeling /><fact trust="0.5">Test fact.</fact></Q>'},
        ]
        result = strip_feelings_from_training(messages)
        self.assertNotIn("<feeling", result[0]["content"])

    def test_drops_empty_messages(self):
        """Messages that are only feelings become empty and are dropped."""
        messages = [
            {"role": "user", "content": "<Q><feeling>How are you?</feeling></Q>"},
            {"role": "assistant", "content": '<R><fact trust="0.5">I am a program.</fact></R>'},
        ]
        result = strip_feelings_from_training(messages)
        # The user message was only feeling → should be dropped
        # The assistant message has a fact → should survive
        self.assertTrue(any("<fact" in m["content"] for m in result))

    def test_preserves_non_feeling_content(self):
        messages = [
            {"role": "assistant", "content": '<R><fact trust="0.5">The earth is round.</fact></R>'},
        ]
        result = strip_feelings_from_training(messages)
        self.assertEqual(len(result), 1)
        self.assertIn("The earth is round.", result[0]["content"])


# =====================================================================
#  Conversation-level processing
# =====================================================================

class TestPreprocessConversation(unittest.TestCase):
    """preprocess_conversation() processes full conversations."""

    def test_returns_tagged_messages(self):
        messages = [
            {"role": "user", "content": "Hello there."},
            {"role": "assistant", "content": "Paris is the capital of France."},
        ]
        result = preprocess_conversation(messages)
        self.assertIn("messages", result)
        self.assertIn("truth_entries", result)
        self.assertEqual(len(result["messages"]), 2)

    def test_extracts_truth_entries(self):
        """Facts are extracted as truth entries when extract_truth=True."""
        messages = [
            {"role": "assistant", "content": "Water is composed of H2O."},
        ]
        result = preprocess_conversation(messages, extract_truth=True)
        # Should have at least one truth entry for the fact
        self.assertTrue(len(result["truth_entries"]) > 0)

    def test_no_truth_when_disabled(self):
        """No truth entries when extract_truth=False."""
        messages = [
            {"role": "assistant", "content": "Water is composed of H2O."},
        ]
        result = preprocess_conversation(messages, extract_truth=False)
        self.assertEqual(len(result["truth_entries"]), 0)

    def test_truth_entries_have_required_fields(self):
        messages = [
            {"role": "assistant", "content": "The sun is a star."},
        ]
        result = preprocess_conversation(messages, extract_truth=True)
        for entry in result["truth_entries"]:
            self.assertIn("type", entry)
            self.assertEqual(entry["type"], "truth")
            self.assertIn("title", entry)
            self.assertIn("trust", entry)
            self.assertIn("content", entry)
            self.assertIn("id", entry)


# =====================================================================
#  SFT corpus batch processing
# =====================================================================

class TestPrepareSftCorpus(unittest.TestCase):
    """prepare_sft_corpus() batch-converts JSONL for NanoChat SFT."""

    def test_basic_conversion(self):
        """A simple 2-message conversation round-trips correctly."""
        corpus = [
            [
                {"role": "user", "content": "What is the capital of France?"},
                {"role": "assistant", "content": "Paris is the capital of France."},
            ],
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as fin:
            for conv in corpus:
                fin.write(json.dumps(conv) + "\n")
            in_path = fin.name

        out_path = in_path + ".out.jsonl"
        try:
            stats = prepare_sft_corpus(Path(in_path), Path(out_path))
            self.assertEqual(stats["processed"], 1)
            self.assertEqual(stats["errors"], 0)

            # Read output and verify structure
            with open(out_path) as f:
                lines = [json.loads(l) for l in f if l.strip()]
            self.assertEqual(len(lines), 1)
            # Output line should be a list of tagged messages
            self.assertIsInstance(lines[0], list)
            self.assertTrue(len(lines[0]) > 0)
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_feelings_stripped_from_output(self):
        """SFT output should not contain <feeling> tags."""
        corpus = [
            [
                {"role": "user", "content": "How are you doing?"},
                {"role": "assistant", "content": "I think I'm great! The earth is round."},
            ],
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as fin:
            for conv in corpus:
                fin.write(json.dumps(conv) + "\n")
            in_path = fin.name

        out_path = in_path + ".out.jsonl"
        try:
            stats = prepare_sft_corpus(Path(in_path), Path(out_path))
            with open(out_path) as f:
                content = f.read()
            self.assertNotIn("<feeling>", content)
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_empty_corpus(self):
        """An empty input file produces empty output."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as fin:
            in_path = fin.name  # empty file

        out_path = in_path + ".out.jsonl"
        try:
            stats = prepare_sft_corpus(Path(in_path), Path(out_path))
            self.assertEqual(stats["processed"], 0)
            self.assertEqual(stats["errors"], 0)
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_invalid_json_counted_as_error(self):
        """Malformed lines are counted as errors, not crashes."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as fin:
            fin.write("not json\n")
            fin.write(json.dumps([{"role": "user", "content": "Hi"}]) + "\n")
            in_path = fin.name

        out_path = in_path + ".out.jsonl"
        try:
            stats = prepare_sft_corpus(Path(in_path), Path(out_path))
            self.assertEqual(stats["errors"], 1)
            # The valid line should still be processed
            self.assertGreaterEqual(stats["processed"] + stats["skipped_empty"], 1)
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_multi_conversation_corpus(self):
        """Multiple conversations are processed independently."""
        corpus = [
            [
                {"role": "user", "content": "Paris is in France."},
                {"role": "assistant", "content": "Yes, Paris is the capital of France."},
            ],
            [
                {"role": "user", "content": "London is in England."},
                {"role": "assistant", "content": "Yes, London is the capital of England."},
            ],
            [
                {"role": "user", "content": "Berlin is in Germany."},
                {"role": "assistant", "content": "Yes, Berlin is the capital of Germany."},
            ],
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as fin:
            for conv in corpus:
                fin.write(json.dumps(conv) + "\n")
            in_path = fin.name

        out_path = in_path + ".out.jsonl"
        try:
            stats = prepare_sft_corpus(Path(in_path), Path(out_path))
            self.assertEqual(stats["processed"], 3)
            self.assertEqual(stats["errors"], 0)
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)


# =====================================================================
#  XHTML roundtrip
# =====================================================================

class TestXhtmlRoundtrip(unittest.TestCase):
    """Tagged output should be valid XML fragments."""

    def test_tagged_message_is_valid_xml(self):
        """tag_message output should parse as valid XML."""
        import xml.etree.ElementTree as ET
        content = "The sky is blue."
        tagged = tag_message(content, "assistant")
        # Should parse without error
        elem = ET.fromstring(tagged)
        self.assertEqual(elem.tag, "R")

    def test_mixed_message_is_valid_xml(self):
        """Mixed fact/feeling message should be valid XML."""
        import xml.etree.ElementTree as ET
        content = "Great question! The earth is round."
        tagged = tag_message(content, "assistant")
        elem = ET.fromstring(tagged)
        self.assertEqual(elem.tag, "R")
        # Should have both fact and feeling children
        tags = {child.tag for child in elem}
        self.assertTrue(len(tags) > 0)

    def test_special_chars_dont_break_xml(self):
        """XML special characters (&, <, >) are properly escaped."""
        import xml.etree.ElementTree as ET
        content = "A & B > C and 1 < 2 is a comparison."
        tagged = tag_message(content, "user")
        elem = ET.fromstring(tagged)
        self.assertEqual(elem.tag, "Q")


if __name__ == "__main__":
    unittest.main()
