#!/usr/bin/env python3
"""Unit tests for user GUID generation and state persistence.

Tests:
  - Deterministic from same name
  - Different names → different GUIDs
  - GUID format (valid UUID)
  - GUID stored in state and round-trips through XML
"""

import os
import sys
import unittest
import uuid

# Add bin/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))

from truth import user_guid, WIKIORACLE_UUID_NS
from state import ensure_minimal_state, state_to_xml, xml_to_state


class TestUserGuid(unittest.TestCase):

    def test_deterministic_same_name(self):
        """Same name always produces the same GUID."""
        g1 = user_guid("Alec")
        g2 = user_guid("Alec")
        assert g1 == g2

    def test_different_names_different_guids(self):
        """Different names produce different GUIDs."""
        g1 = user_guid("Alice")
        g2 = user_guid("Bob")
        assert g1 != g2

    def test_valid_uuid_format(self):
        """The GUID is a valid UUID string."""
        g = user_guid("TestUser")
        parsed = uuid.UUID(g)
        assert parsed.version == 5

    def test_uses_wikioracle_namespace(self):
        """The GUID uses the WikiOracle UUID namespace."""
        g = user_guid("TestUser")
        expected = str(uuid.uuid5(WIKIORACLE_UUID_NS, "TestUser"))
        assert g == expected

    def test_empty_name(self):
        """Empty string is a valid input (produces a deterministic GUID)."""
        g1 = user_guid("")
        g2 = user_guid("")
        assert g1 == g2
        # Should still be a valid UUID
        uuid.UUID(g1)

    def test_explicit_uid_preferred(self):
        """When uid is provided, it is returned as-is (no UUID derivation)."""
        g = user_guid("Alec", uid="my-explicit-uid-123")
        assert g == "my-explicit-uid-123"

    def test_explicit_uid_overrides_name(self):
        """uid takes priority even when name differs."""
        g1 = user_guid("Alice", uid="shared-uid")
        g2 = user_guid("Bob", uid="shared-uid")
        assert g1 == g2 == "shared-uid"

    def test_empty_uid_falls_back_to_name(self):
        """Empty uid string falls back to name-based UUID-5."""
        g = user_guid("TestUser", uid="")
        expected = str(uuid.uuid5(WIKIORACLE_UUID_NS, "TestUser"))
        assert g == expected

    def test_none_uid_falls_back_to_name(self):
        """None uid falls back to name-based UUID-5."""
        g = user_guid("TestUser", uid=None)
        expected = str(uuid.uuid5(WIKIORACLE_UUID_NS, "TestUser"))
        assert g == expected


class TestUserGuidInState(unittest.TestCase):

    def test_guid_round_trips_through_xml(self):
        """user_id stored in user dict round-trips through XML."""
        state = ensure_minimal_state({})
        state.setdefault("user", {})["user_id"] = user_guid("Alec")
        state["user"]["name"] = "Alec"

        xml = state_to_xml(state)
        restored = xml_to_state(xml)

        assert restored["user"]["user_id"] == user_guid("Alec")
        assert restored["user"]["name"] == "Alec"

    def test_user_absent_if_not_set(self):
        """State without user set does not inject a fake one."""
        state = ensure_minimal_state({})
        xml = state_to_xml(state)
        restored = xml_to_state(xml)
        # user should not be present or should have empty user_id
        user = restored.get("user")
        assert not user or not user.get("user_id")

    def test_old_user_guid_migrated_on_normalize(self):
        """ensure_minimal_state migrates user_guid to user.user_id."""
        raw = {"user_guid": "test-guid-123"}
        state = ensure_minimal_state(raw)
        assert state["user"]["user_id"] == "test-guid-123"
        assert "user_guid" not in state
