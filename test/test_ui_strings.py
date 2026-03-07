#!/usr/bin/env python3
"""Consistency checks: client/util.js UI strings vs doc/UserInterface.md.

The markdown file is the canonical source.  This test ensures the
hard-coded JavaScript strings stay in sync with the documentation.
"""

import re
import sys
import unittest
from pathlib import Path

_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project / "bin"))

_UI_MD = _project / "doc" / "UserInterface.md"
_UTIL_JS = _project / "client" / "util.js"

_TRUTH_TYPES = frozenset({
    "feeling", "fact", "reference", "and", "or",
    "not", "non", "provider", "authority",
})


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

def _parse_md_table(md_text: str, heading: str) -> dict:
    """Extract rows from the markdown table under ``### <heading>``.

    Returns ``{key: value}`` with backtick delimiters stripped.
    """
    pattern = rf"###\s+{re.escape(heading)}\s*\n"
    match = re.search(pattern, md_text)
    if not match:
        return {}

    section = md_text[match.end():]
    next_heading = re.search(r"\n###?\s", section)
    if next_heading:
        section = section[: next_heading.start()]

    rows: dict = {}
    table_lines = [
        line.strip()
        for line in section.strip().splitlines()
        if line.strip().startswith("|")
    ]
    for line in table_lines[2:]:  # skip header + separator
        cells = [c.strip().strip("`") for c in line.split("|")[1:-1]]
        if len(cells) >= 2:
            rows[cells[0]] = cells[1]
    return rows


# ---------------------------------------------------------------------------
# JavaScript parsers
# ---------------------------------------------------------------------------

def _extract_js_dict(js_text: str, var_name: str) -> dict:
    """Extract a JS object literal assigned to *var_name*.

    Handles ``var _name = { key: 'value', ... };``
    Returns ``{key: value}``.
    """
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*\{{"
    match = re.search(pattern, js_text)
    if not match:
        return {}

    start = match.end()
    depth = 1
    i = start
    while i < len(js_text) and depth > 0:
        if js_text[i] == "{":
            depth += 1
        elif js_text[i] == "}":
            depth -= 1
        i += 1

    body = js_text[start : i - 1]

    result: dict = {}
    for m in re.finditer(r"""(\w+)\s*:\s*(['"])((?:(?!\2)[\s\S]|\\.)*)\2""", body):
        key = m.group(1)
        value = m.group(3)
        # Unescape JS unicode escapes like \u2014 → —
        value = re.sub(
            r"\\u([0-9a-fA-F]{4})",
            lambda x: chr(int(x.group(1), 16)),
            value,
        )
        result[key] = value
    return result


def _extract_js_options(js_text: str) -> dict:
    """Extract ``<option value="key">Label</option>`` from the truthAddType select.

    Returns ``{value: label}``.
    """
    result: dict = {}
    for m in re.finditer(
        r'<option\s+value="(\w+)">(.*?)</option>', js_text
    ):
        result[m.group(1)] = m.group(2)
    return result


def _extract_js_empty_message(js_text: str) -> str:
    """Extract the empty-state text from the trust-empty div, stripping HTML tags."""
    m = re.search(r'class="trust-empty">(.*?)</div>', js_text)
    if not m:
        return ""
    return re.sub(r"<[^>]+>", "", m.group(1))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestUIStringsConsistency(unittest.TestCase):
    """Verify client/util.js UI strings match doc/UserInterface.md."""

    @classmethod
    def setUpClass(cls):
        cls.md_text = _UI_MD.read_text(encoding="utf-8")
        cls.js_text = _UTIL_JS.read_text(encoding="utf-8")

    def test_dropdown_labels_match(self):
        """Dropdown <option> labels in JS match the Labels table in MD."""
        md_labels = _parse_md_table(self.md_text, "Dropdown labels")
        js_labels = _extract_js_options(self.js_text)

        self.assertEqual(
            set(md_labels.keys()), set(js_labels.keys()),
            "Dropdown label keys differ between MD and JS",
        )
        for key in md_labels:
            self.assertEqual(
                md_labels[key], js_labels[key],
                f"Dropdown label mismatch for '{key}'",
            )

    def test_descriptions_match(self):
        """_truthDescriptions in JS match the Descriptions table in MD."""
        md_descs = _parse_md_table(self.md_text, "Descriptions")
        js_descs = _extract_js_dict(self.js_text, "_truthDescriptions")

        self.assertEqual(
            set(md_descs.keys()), set(js_descs.keys()),
            "Description keys differ between MD and JS",
        )
        for key in md_descs:
            self.assertEqual(
                md_descs[key], js_descs[key],
                f"Description mismatch for '{key}'",
            )

    def test_templates_match(self):
        """_truthTemplates in JS match the Templates table in MD."""
        md_templates = _parse_md_table(self.md_text, "Templates")
        js_templates = _extract_js_dict(self.js_text, "_truthTemplates")

        self.assertEqual(
            set(md_templates.keys()), set(js_templates.keys()),
            "Template keys differ between MD and JS",
        )
        for key in md_templates:
            self.assertEqual(
                md_templates[key], js_templates[key],
                f"Template mismatch for '{key}'",
            )

    def test_empty_state_message_matches(self):
        """The trust-empty div text in JS matches the Empty state table in MD."""
        md_empty = _parse_md_table(self.md_text, "Empty state")
        js_empty = _extract_js_empty_message(self.js_text)

        self.assertIn(
            "truth_empty", md_empty,
            "Missing 'truth_empty' key in Empty state table",
        )
        self.assertEqual(
            md_empty["truth_empty"], js_empty,
            "Empty state message mismatch",
        )

    def test_all_nine_truth_types_present(self):
        """All 9 truth types appear in all three tables."""
        for heading in ("Dropdown labels", "Descriptions", "Templates"):
            md_keys = set(_parse_md_table(self.md_text, heading).keys())
            self.assertEqual(
                md_keys, _TRUTH_TYPES,
                f"MD table '{heading}' missing/extra keys",
            )


if __name__ == "__main__":
    unittest.main()
