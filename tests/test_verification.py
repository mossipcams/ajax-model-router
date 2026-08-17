#!/usr/bin/env python3
"""Verification and report boundary checks (no packet/TDD ceremony)."""

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK_REPORT = ROOT / "scripts" / "check-report"
ROUTER = ROOT / "skills" / "model-router" / "SKILL.md"

COMPLETE_REPORT = """\
DELEGATE_REPORT:
  STATUS: COMPLETE
  CHANGED_FILES: [src/example.py]
  VERIFICATION:
    - TYPE: test
      COMMAND: python -m unittest tests.test_example
      RESULT: pass
      DETAILS: ok
  CONCERNS: []
"""

BLOCKED_REPORT = """\
DELEGATE_REPORT:
  STATUS: BLOCKED
  CHANGED_FILES: []
  VERIFICATION: []
  CONCERNS:
    - TYPE: scope_expansion
      DETAIL: needs edits outside allowed scope
      RECOMMENDED_ACTION: emit a new EXECUTION with expanded SCOPE
"""

FAILED_COMPLETE = """\
DELEGATE_REPORT:
  STATUS: COMPLETE
  CHANGED_FILES: [src/example.py]
  VERIFICATION:
    - TYPE: test
      COMMAND: python -m unittest tests.test_example
      RESULT: fail
      DETAILS: assertion error
  CONCERNS: []
"""


class VerificationTests(unittest.TestCase):
    def test_router_has_no_tdd_requirements(self):
        text = ROUTER.read_text()
        self.assertNotIn("TEST_FIRST", text)
        self.assertNotIn("RED | GREEN", text)
        self.assertNotIn("tdd-implementation-packet", text)
        self.assertIn("Choose the implementation approach.", text)
        self.assertIn("Run appropriate verification.", text)

    def test_complete_report_requires_passing_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.yaml"
            good.write_text(COMPLETE_REPORT)
            result = subprocess.run(
                [CHECK_REPORT, good], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            bad = Path(tmp) / "bad.yaml"
            bad.write_text(FAILED_COMPLETE)
            result = subprocess.run(
                [CHECK_REPORT, bad], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("failing verification", result.stderr)

    def test_blocked_requires_concerns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blocked.yaml"
            path.write_text(BLOCKED_REPORT)
            result = subprocess.run(
                [CHECK_REPORT, path], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            empty = Path(tmp) / "empty.yaml"
            empty.write_text(
                "DELEGATE_REPORT:\n"
                "  STATUS: BLOCKED\n"
                "  CHANGED_FILES: []\n"
                "  VERIFICATION: []\n"
                "  CONCERNS: []\n"
            )
            result = subprocess.run(
                [CHECK_REPORT, empty], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)

    def test_packet_review_schema_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packet.yaml"
            path.write_text(
                "PACKET_REVIEW:\n"
                "  VERDICT: PASS\n"
                "  REVIEWED_UNCERTAINTY: SPECIFICATION\n"
                "  PACKET_CHECK: PASS\n"
                "  BLOCKERS: []\n"
                "  REMAINING_RISKS: []\n"
            )
            result = subprocess.run(
                [CHECK_REPORT, path], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown report schema", result.stderr)

    def test_review_report_schema_rejected(self):
        """Fixed parent REVIEW_REPORT restate schema is gone; review is risk-proportional."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.yaml"
            path.write_text(
                "REVIEW_REPORT:\n"
                "  VERDICT: ACCEPT\n"
                "  FINDINGS: []\n"
                "  VERIFICATION: []\n"
                "  SCOPE_VIOLATIONS: []\n"
                "  REMAINING_RISKS: []\n"
            )
            result = subprocess.run(
                [CHECK_REPORT, path], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
