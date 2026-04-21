"""
Unit tests for core.canonical_types lifecycle transitions and legacy mappers.

These tests pin the state-machine contract that the canonical mission
status and risk types must preserve. They run in milliseconds with no
external deps.
"""
from __future__ import annotations

import unittest

from core.canonical_types import (
    CanonicalMissionStatus,
    CanonicalRiskLevel,
    map_legacy_mission_status,
    map_legacy_risk_level,
    validate_transition,
)


class TestValidateTransition(unittest.TestCase):
    def test_created_to_planning_allowed(self):
        self.assertTrue(
            validate_transition(
                CanonicalMissionStatus.CREATED, CanonicalMissionStatus.PLANNING
            )
        )

    def test_completed_is_terminal(self):
        # From COMPLETED, no forward transitions are allowed
        for target in CanonicalMissionStatus:
            self.assertFalse(
                validate_transition(CanonicalMissionStatus.COMPLETED, target),
                f"COMPLETED → {target} should not be allowed",
            )

    def test_failed_is_terminal(self):
        for target in CanonicalMissionStatus:
            self.assertFalse(
                validate_transition(CanonicalMissionStatus.FAILED, target),
                f"FAILED → {target} should not be allowed",
            )

    def test_cancelled_is_terminal(self):
        for target in CanonicalMissionStatus:
            self.assertFalse(
                validate_transition(CanonicalMissionStatus.CANCELLED, target),
                f"CANCELLED → {target} should not be allowed",
            )

    def test_self_transition_not_allowed(self):
        # A status should not transition to itself (idempotent updates go
        # through a different code path, not through validate_transition)
        self.assertFalse(
            validate_transition(
                CanonicalMissionStatus.RUNNING, CanonicalMissionStatus.RUNNING
            )
        )


class TestMapLegacyMissionStatus(unittest.TestCase):
    def test_known_legacy_strings(self):
        # Whatever mapping is implemented, mapping must be total (no None
        # for common strings) and deterministic.
        mapped = map_legacy_mission_status("COMPLETED")
        self.assertIsInstance(mapped, CanonicalMissionStatus)

    def test_unknown_defaults_safely(self):
        # Unknown input must not raise; it can default to CREATED or
        # None — just assert no exception.
        try:
            map_legacy_mission_status("NOT_A_REAL_STATUS")
        except Exception as exc:  # pragma: no cover
            self.fail(f"map_legacy_mission_status raised: {exc!r}")


class TestMapLegacyRiskLevel(unittest.TestCase):
    def test_known_risk_strings(self):
        for level in ("low", "medium", "high", "critical"):
            mapped = map_legacy_risk_level(level)
            self.assertIsInstance(mapped, CanonicalRiskLevel)

    def test_upper_case_accepted(self):
        low_lower = map_legacy_risk_level("low")
        low_upper = map_legacy_risk_level("LOW")
        # Either they map to the same level or at least both produce a
        # CanonicalRiskLevel. Require the former.
        self.assertEqual(low_lower, low_upper)

    def test_unknown_safe(self):
        try:
            map_legacy_risk_level("pink")
        except Exception as exc:  # pragma: no cover
            self.fail(f"map_legacy_risk_level raised: {exc!r}")


if __name__ == "__main__":
    unittest.main()
