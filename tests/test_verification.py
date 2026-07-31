#!/usr/bin/env python3
"""Outcome-based verification contracts (no mandatory TDD)."""

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK_PACKET = ROOT / "scripts" / "check-packet"
CHECK_REPORT = ROOT / "scripts" / "check-report"
CHECK_DISPATCH = ROOT / "scripts" / "check-dispatch"
ROUTER = ROOT / "skills" / "model-router" / "SKILL.md"
PACKET = ROOT / "skills" / "tdd-implementation-packet" / "SKILL.md"


NEW_PACKET = """\
PACKET_STATUS: READY
UNRESOLVED_UNCERTAINTY: NONE
BLOCKERS: []
## Task
Change VALUE to 2.
## Scope
Allowed:
- src/example.py
Forbidden:
- unrelated refactors
## Acceptance
- VALUE equals 2
## Constraints
NONE
## Verification
methods:
  - type: test
    command: python -m unittest tests.test_example
    expected: pass
reason: focused unit test covers the pure logic change
## Stop if
- edits outside allowed scope
"""

LEGACY_PACKET = """\
PACKET_STATUS: READY
TASK_KIND: behavior
TEST_FIRST: REQUIRED
PRODUCTION_EDIT: REQUIRED
UNRESOLVED_UNCERTAINTY: NONE
BLOCKERS: []
## Goal
Change one behavior.
## Allowed files
src/example.py
## Forbidden changes
No unrelated edits.
## Context evidence
Desired behavior and exact anchors recorded.
## Code anchors
src/example.py:10
## Test-first instructions
tests/test_example.py assertion and focused command.
## Edit instructions
Edit example at line 10.
## Verification commands
python -m unittest tests.test_example
## Acceptance criteria
Focused test passes.
## Stop conditions
Anchor moved or scope grows.
"""

COMPLETE_REPORT = """\
DELEGATE_REPORT:
  STATUS: COMPLETE
  CHANGED_FILES: [src/example.py]
  VERIFICATION:
    - TYPE: test
      COMMAND: python -m unittest tests.test_example
      STEPS: []
      RESULT: pass
      DETAILS: ok
  CONCERNS: []
"""


class VerificationContractTests(unittest.TestCase):
    def test_router_rejects_mandatory_tdd_language(self):
        text = ROUTER.read_text()
        self.assertIn("does not require test-first development or TDD", text)
        self.assertIn("Review evidence quality, not adherence to TDD.", text)
        self.assertNotIn("TEST_FIRST: PROVEN | NOT_APPLICABLE | NOT_PROVEN", text)
        self.assertNotIn("PHASE: RED | GREEN | VERIFY | OTHER", text)
        packet = PACKET.read_text()
        self.assertIn("does **not** require test-first development", packet)
        self.assertNotIn("TEST_FIRST: REQUIRED | NOT_APPLICABLE", packet)

    def test_behavior_packet_does_not_require_test_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packet.md"
            path.write_text(NEW_PACKET)
            result = subprocess.run(
                [CHECK_PACKET, path], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("TEST_FIRST", path.read_text())

    def test_new_packet_without_new_tests_is_accepted(self):
        packet = NEW_PACKET.replace(
            "  - type: test\n    command: python -m unittest tests.test_example\n    expected: pass",
            "  - type: typecheck\n    command: tsc --noEmit\n    expected: exit 0\n"
            "  - type: build\n    command: npm run build\n    expected: exit 0",
        ).replace(
            "reason: focused unit test covers the pure logic change",
            "reason: typecheck and build validate the wiring change",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packet.md"
            path.write_text(packet)
            result = subprocess.run(
                [CHECK_PACKET, path], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_vague_verification_is_rejected(self):
        bad = NEW_PACKET.replace(
            "## Verification\nmethods:\n  - type: test\n    command: python -m unittest tests.test_example\n    expected: pass\nreason: focused unit test covers the pure logic change\n",
            "## Verification\n\nlooks good\n",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packet.md"
            path.write_text(bad)
            result = subprocess.run(
                [CHECK_PACKET, path], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Verification", result.stderr)

    def test_legacy_tdd_packet_still_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packet.md"
            path.write_text(LEGACY_PACKET)
            result = subprocess.run(
                [CHECK_PACKET, path], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("deprecated", result.stderr)
            # Behavior + TEST_FIRST NOT_APPLICABLE no longer rejected.
            path.write_text(
                LEGACY_PACKET.replace("TEST_FIRST: REQUIRED", "TEST_FIRST: NOT_APPLICABLE")
            )
            result = subprocess.run(
                [CHECK_PACKET, path], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_delegate_report_accepts_non_test_verification(self):
        cases = (
            "typecheck",
            "build",
            "browser",
            "manual",
            "existing_test",
            "integration",
        )
        for kind in cases:
            with self.subTest(kind=kind):
                report = COMPLETE_REPORT.replace("TYPE: test", f"TYPE: {kind}")
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "report.yaml"
                    path.write_text(report)
                    result = subprocess.run(
                        [CHECK_REPORT, path], text=True, capture_output=True
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_complete_without_verification_fails(self):
        report = """\
DELEGATE_REPORT:
  STATUS: COMPLETE
  CHANGED_FILES: [src/example.py]
  VERIFICATION: []
  CONCERNS: []
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.yaml"
            path.write_text(report)
            result = subprocess.run(
                [CHECK_REPORT, path], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)

    def test_failed_verification_cannot_be_complete(self):
        report = COMPLETE_REPORT.replace("RESULT: pass", "RESULT: fail")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.yaml"
            path.write_text(report)
            result = subprocess.run(
                [CHECK_REPORT, path], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)

    def test_direct_dispatch_without_tdd_packet(self):
        direct = """\
DISPATCH_LEVEL: direct
## User request

Change VALUE to 2
## Allowed files

- src/example.py
## Acceptance criteria

- VALUE equals 2
## Stop conditions

- edit outside allowed files
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "direct.md"
            path.write_text(direct)
            result = subprocess.run(
                [CHECK_DISPATCH, "direct", path], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_compact_dispatch_without_test_anchors(self):
        compact = """\
PACKET_STATUS: READY
UNRESOLVED_UNCERTAINTY: NONE
BLOCKERS: []
DISPATCH_LEVEL: compact
## Task

Change VALUE to 2
## Allowed files

- src/example.py
## Forbidden changes

- unrelated refactors
## Acceptance

- VALUE equals 2
## Constraints

- NONE
## Verification

methods:
  - type: existing_test
    command: python -m unittest tests.test_example
    expected: pass
reason: existing focused test covers the change
## Stop if

- scope grows
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compact.md"
            path.write_text(compact)
            result = subprocess.run(
                [CHECK_DISPATCH, "compact", path], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Code anchors", path.read_text())

    def test_manual_verification_requires_structure_in_report(self):
        report = """\
DELEGATE_REPORT:
  STATUS: COMPLETE
  CHANGED_FILES: [ui/button.tsx]
  VERIFICATION:
    - TYPE: manual
      COMMAND: NONE
      STEPS: [open settings, toggle theme, confirm dark mode]
      RESULT: pass
      DETAILS: dark mode applied
  CONCERNS: []
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.yaml"
            path.write_text(report)
            result = subprocess.run(
                [CHECK_REPORT, path], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_review_gate_docs_reject_tdd_only_failures(self):
        text = ROUTER.read_text()
        self.assertIn("no new tests were added", text)
        self.assertIn("no RED evidence exists", text)
        self.assertIn("no meaningful verification was performed", text)
        self.assertIn("scope was exceeded", text)


if __name__ == "__main__":
    unittest.main()
