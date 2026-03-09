"""Tests for spacetime fact classification and PII detection in bin/truth.py."""

import sys
import unittest
from pathlib import Path

# Ensure bin/ is on the import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

from truth import (
    detect_asymmetric_claim,
    is_news_fact,
    is_knowledge_fact,
    filter_knowledge_only,
    detect_identifiability,
    strip_spacetime_elements,
)


# =====================================================================
#  Fact classification — knowledge vs news
# =====================================================================


class TestIsNewsFact(unittest.TestCase):
    """Test spatiotemporal binding detection via XHTML child elements."""

    def test_entry_with_real_place(self):
        entry = {"content": '<fact trust="0.5"><place>Paris</place>Some fact</fact>'}
        self.assertTrue(is_news_fact(entry))

    def test_entry_with_real_time(self):
        entry = {"content": '<fact trust="0.5"><time>2026-03-05T12:00:00Z</time>Some fact</fact>'}
        self.assertTrue(is_news_fact(entry))

    def test_entry_with_both(self):
        entry = {"content": '<fact trust="0.5"><place>London</place><time>2026-01-01</time>Some fact</fact>'}
        self.assertTrue(is_news_fact(entry))

    def test_entry_with_placeholder_place(self):
        entry = {"content": '<fact trust="0.5"><place>[unverified]</place>Some fact</fact>'}
        self.assertFalse(is_news_fact(entry))

    def test_entry_with_unknown_place(self):
        entry = {"content": '<fact trust="0.5"><place>unknown</place>Some fact</fact>'}
        self.assertFalse(is_news_fact(entry))

    def test_entry_with_no_bindings(self):
        entry = {"content": '<fact trust="0.5">Some fact</fact>'}
        self.assertFalse(is_news_fact(entry))

    def test_entry_missing_content(self):
        entry = {"id": "test"}
        self.assertFalse(is_news_fact(entry))

    def test_entry_with_na_place(self):
        entry = {"content": '<fact trust="0.5"><place>n/a</place>Some fact</fact>'}
        self.assertFalse(is_news_fact(entry))

    def test_feeling_with_place(self):
        entry = {"content": "<feeling><place>London</place>A sense of wonder</feeling>"}
        self.assertTrue(is_news_fact(entry))

    def test_feeling_without_place(self):
        entry = {"content": "<feeling>I feel happy</feeling>"}
        self.assertFalse(is_news_fact(entry))


class TestIsKnowledgeFact(unittest.TestCase):
    """Test universal/inferential fact detection."""

    def test_knowledge_entry(self):
        entry = {"content": '<fact trust="0.5">Water is H2O</fact>'}
        self.assertTrue(is_knowledge_fact(entry))

    def test_knowledge_with_placeholders(self):
        entry = {"content": '<fact trust="0.5"><place>[unverified]</place><time>unknown</time>Some fact</fact>'}
        self.assertTrue(is_knowledge_fact(entry))

    def test_news_entry_is_not_knowledge(self):
        entry = {"content": '<fact trust="0.5"><place>Tokyo</place><time>2026-03-05</time>Some fact</fact>'}
        self.assertFalse(is_knowledge_fact(entry))

    def test_missing_content_is_knowledge(self):
        entry = {"id": "test"}
        self.assertTrue(is_knowledge_fact(entry))


class TestFilterKnowledgeOnly(unittest.TestCase):
    """Test filtering to knowledge-only entries."""

    def test_mixed_entries(self):
        entries = [
            {"id": "k1", "content": '<fact trust="0.5">Universal fact</fact>'},
            {"id": "n1", "content": '<fact trust="0.5"><place>Berlin</place><time>2026-03-01</time>News fact</fact>'},
            {"id": "k2", "content": '<fact trust="0.5"><place>[unverified]</place>Another fact</fact>'},
            {"id": "n2", "content": '<fact trust="0.5"><time>2026-03-05T09:00:00Z</time>Time-bound fact</fact>'},
        ]
        result = filter_knowledge_only(entries)
        ids = [e["id"] for e in result]
        self.assertEqual(ids, ["k1", "k2"])

    def test_all_knowledge(self):
        entries = [
            {"id": "k1", "content": '<fact trust="0.5">Fact one</fact>'},
            {"id": "k2", "content": '<fact trust="0.5">Fact two</fact>'},
        ]
        result = filter_knowledge_only(entries)
        self.assertEqual(len(result), 2)

    def test_all_news(self):
        entries = [
            {"id": "n1", "content": '<fact trust="0.5"><place>Paris</place>Paris fact</fact>'},
        ]
        result = filter_knowledge_only(entries)
        self.assertEqual(len(result), 0)

    def test_empty_list(self):
        self.assertEqual(filter_knowledge_only([]), [])


# =====================================================================
#  Identifiability detection (particularity)
# =====================================================================


class TestDetectIdentifiability(unittest.TestCase):
    """Test PII / identifiability pattern detection in content."""

    def test_email(self):
        self.assertTrue(detect_identifiability("Contact me at user@example.com"))

    def test_phone(self):
        self.assertTrue(detect_identifiability("Call 555-123-4567"))

    def test_phone_intl(self):
        self.assertTrue(detect_identifiability("Call +1-555-123-4567"))

    def test_handle(self):
        self.assertTrue(detect_identifiability("Follow me @johndoe on Twitter"))

    def test_ip_address(self):
        self.assertTrue(detect_identifiability("Server at 192.168.1.100"))

    def test_gps_coords(self):
        self.assertTrue(detect_identifiability("Located at 48.8566, 2.3522"))

    def test_street_address(self):
        self.assertTrue(detect_identifiability("I live at 123 Main Street"))

    def test_clean_knowledge(self):
        self.assertFalse(detect_identifiability("Water is composed of hydrogen and oxygen"))

    def test_clean_fact(self):
        self.assertFalse(detect_identifiability("The Earth orbits the Sun"))

    def test_city_name_detection(self):
        self.assertTrue(detect_identifiability("I was in Tokyo yesterday"))

    def test_xhtml_tags_stripped(self):
        self.assertTrue(
            detect_identifiability('<fact trust="0.5">Contact user@example.com</fact>')
        )


# =====================================================================
#  Strip spacetime elements
# =====================================================================


class TestStripSpacetimeElements(unittest.TestCase):
    """Test removal of <place> and <time> child elements from XHTML content."""

    def test_strip_place_from_fact(self):
        content = '<fact trust="0.9"><place>Paris</place>Some fact</fact>'
        result = strip_spacetime_elements(content)
        self.assertNotIn("<place>", result)
        self.assertIn("trust=", result)
        self.assertIn("Some fact", result)

    def test_strip_time_from_fact(self):
        content = '<fact trust="0.5"><time>2026-03-05</time>Some fact</fact>'
        result = strip_spacetime_elements(content)
        self.assertNotIn("<time>", result)
        self.assertIn("trust=", result)

    def test_strip_both(self):
        content = '<fact trust="0.8"><place>London</place><time>2026-01-01</time>Fact text</fact>'
        result = strip_spacetime_elements(content)
        self.assertNotIn("<place>", result)
        self.assertNotIn("<time>", result)
        self.assertIn("Fact text", result)

    def test_no_spacetime_unchanged(self):
        content = '<fact trust="0.9">Clean fact</fact>'
        result = strip_spacetime_elements(content)
        self.assertIn("Clean fact", result)
        self.assertIn("trust=", result)

    def test_invalid_xml_returns_original(self):
        content = "not valid xml at all"
        result = strip_spacetime_elements(content)
        self.assertEqual(result, content)

    def test_strip_place_from_feeling(self):
        content = "<feeling><place>London</place>A sense of wonder</feeling>"
        result = strip_spacetime_elements(content)
        self.assertNotIn("<place>", result)
        self.assertIn("A sense of wonder", result)

    def test_feeling_no_elements_unchanged(self):
        content = "<feeling>Just a feeling</feeling>"
        result = strip_spacetime_elements(content)
        self.assertIn("Just a feeling", result)


# =====================================================================
#  Stage 3 merge filtering (Entanglement Policy enforcement)
# =====================================================================


class TestStage3Filtering(unittest.TestCase):
    """Test that Entanglement Policy filters are applied correctly."""

    def _make_entries(self):
        """Build a mixed list of knowledge, news, and identifiable entries."""
        return [
            {"id": "k1", "content": '<fact trust="0.5">Water is H2O</fact>'},
            {"id": "n1", "content": '<fact trust="0.5"><place>Paris</place><time>2026-03-05</time>It rained</fact>'},
            {"id": "k2", "content": '<fact trust="0.5">Gravity attracts mass</fact>'},
            {"id": "pii", "content": '<fact trust="0.5">Contact user@example.com for details</fact>'},
        ]

    def test_store_concrete_false_filters_news(self):
        """When store_concrete=False, news facts are excluded."""
        entries = self._make_entries()
        filtered = filter_knowledge_only(entries)
        filtered = [e for e in filtered if not detect_identifiability(e.get("content", ""))]
        ids = [e["id"] for e in filtered]
        self.assertIn("k1", ids)
        self.assertIn("k2", ids)
        self.assertNotIn("n1", ids)
        self.assertNotIn("pii", ids)

    def test_store_concrete_true_preserves_news(self):
        """When store_concrete=True, news facts pass through (but PII still filtered)."""
        entries = self._make_entries()
        # Skip filter_knowledge_only (store_concrete=True)
        filtered = [e for e in entries if not detect_identifiability(e.get("content", ""))]
        ids = [e["id"] for e in filtered]
        self.assertIn("k1", ids)
        self.assertIn("k2", ids)
        self.assertIn("n1", ids)
        self.assertNotIn("pii", ids)

    def test_identifiability_always_filters(self):
        """PII entries are filtered even when store_concrete=True."""
        entries = [
            {"id": "pii1", "content": '<fact trust="0.5">Call 555-123-4567</fact>'},
            {"id": "pii2", "content": '<fact trust="0.5">Located at 48.8566, 2.3522</fact>'},
            {"id": "clean", "content": '<fact trust="0.5">The sky is blue</fact>'},
        ]
        filtered = [e for e in entries if not detect_identifiability(e.get("content", ""))]
        ids = [e["id"] for e in filtered]
        self.assertEqual(ids, ["clean"])


# =====================================================================
#  Truth Symmetry (Ethics.md §5-8)
# =====================================================================


class TestDetectAsymmetricClaim(unittest.TestCase):
    """Test symmetry constraint detection on truth claims."""

    def test_group_with_harm_predicate(self):
        result = detect_asymmetric_claim(
            '<fact trust="0.5">Muslims deserve punishment</fact>')
        self.assertIsNotNone(result)
        self.assertIn("asymmetric harm", result)

    def test_group_inferiority(self):
        result = detect_asymmetric_claim(
            '<fact trust="0.5">Immigrants are inherently lazy</fact>')
        self.assertIsNotNone(result)

    def test_group_elimination(self):
        result = detect_asymmetric_claim(
            '<fact trust="0.5">Foreigners should be deported</fact>')
        self.assertIsNotNone(result)

    def test_clean_universal_positive(self):
        self.assertIsNone(detect_asymmetric_claim(
            '<fact trust="0.5">All humans deserve dignity</fact>'))

    def test_clean_neutral_about_group(self):
        self.assertIsNone(detect_asymmetric_claim(
            '<fact trust="0.5">Christians celebrate Easter</fact>'))

    def test_no_group_reference(self):
        self.assertIsNone(detect_asymmetric_claim(
            '<fact trust="0.5">The sky is blue</fact>'))

    def test_empty_content(self):
        self.assertIsNone(detect_asymmetric_claim(""))

    def test_none_content(self):
        self.assertIsNone(detect_asymmetric_claim(None))

    def test_group_x_placeholder(self):
        result = detect_asymmetric_claim(
            '<fact trust="0.5">Group X deserves harm</fact>')
        self.assertIsNotNone(result)

    def test_distrust_pattern(self):
        result = detect_asymmetric_claim(
            '<fact trust="0.5">Jews cannot be trusted</fact>')
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
