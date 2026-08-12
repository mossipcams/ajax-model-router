#!/usr/bin/env python3
"""Harness-boundary contracts for Ajax Model Router."""

import tempfile
import unittest
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "skills" / "model-router" / "SKILL.md"
CURSOR_ADAPTER = ROOT / "skills" / "model-router-cursor" / "SKILL.md"
CODEX_ADAPTER = ROOT / "skills" / "model-router-codex" / "SKILL.md"
CLAUDE_ADAPTER = ROOT / "skills" / "model-router-claude" / "SKILL.md"
CHECK_REPORT = ROOT / "scripts" / "check-report"

VALID_COMPLETE = """\
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


class ContractTests(unittest.TestCase):
    def test_harness_boundary_decision_contract(self):
        text = ROUTER.read_text()
        self.assertIn("ROUTING_DECISION:", text)
        self.assertIn("MODEL_ROUTING_REQUEST:", text)
        self.assertIn("CALLER_HARNESS: cursor | codex | claude | pi | other", text)
        self.assertIn("TARGET_TRANSPORT: cursor | codex | pi", text)
        self.assertIn("ACTION: USE_NATIVE | DELEGATE | STOP", text)
        self.assertNotIn("EXECUTION:", text)
        self.assertNotIn("CURRENT_HARNESS: cursor | codex | pi", text)
        self.assertNotIn("TARGET_HARNESS: cursor | codex | pi", text)

    def test_adapters_bind_caller_harness(self):
        self.assertIn("CALLER_HARNESS is always `cursor`", CURSOR_ADAPTER.read_text())
        self.assertIn("CALLER_HARNESS is always `codex`", CODEX_ADAPTER.read_text())
        self.assertIn("CALLER_HARNESS is always `claude`", CLAUDE_ADAPTER.read_text())
        self.assertIn("never emits `USE_NATIVE`", CLAUDE_ADAPTER.read_text())

    def test_caller_without_transport_documented(self):
        text = ROUTER.read_text()
        self.assertIn("without Ajax supporting it as a DELEGATE target", text)
        self.assertIn("Claude can invoke Ajax Model Router to launch Cursor", text)

    def test_delegate_prompt_carries_request_fields(self):
        text = ROUTER.read_text()
        for phrase in (
            "Task:",
            "Allowed files:",
            "Acceptance criteria:",
            "Verification requirements:",
            "Stop if:",
            "Investigate the repository as needed.",
            "Choose the implementation approach.",
            "STEPS: []",
        ):
            self.assertIn(phrase, text)

    def test_scope_expansion_rejected(self):
        text = ROUTER.read_text()
        self.assertIn(
            "Stop if completing the task requires expanding beyond the allowed files.",
            text,
        )
        self.assertIn("Expanding scope", text)
        self.assertIn("requires a new request and decision.", text)

    def test_parent_reviews_actual_delta(self):
        text = ROUTER.read_text()
        self.assertIn("## Parent review", text)
        self.assertIn("inspect the actual delta", text)
        self.assertNotIn("## Risk-based review", text)

    def test_absent_obsolete_packet_and_semantic_routing(self):
        text = ROUTER.read_text()
        for forbidden in (
            "tdd-implementation-packet",
            "PACKET_STATUS",
            "R-CURSOR",
            "R-MINIMAX",
            "Default implementation agent is",
            "CALIBRATION.md",
            "## Calibration",
        ):
            self.assertNotIn(forbidden, text)
        self.assertFalse((ROOT / "skills" / "tdd-implementation-packet").exists())
        self.assertFalse((ROOT / "CALIBRATION.md").exists())

    def test_codex_uses_requested_model_and_xhigh_effort(self):
        router = ROUTER.read_text()
        adapter = (ROOT / "skills" / "codex-delegate" / "SKILL.md").read_text()
        self.assertIn("| `codex` | `gpt-5.6-sol` |", router)
        self.assertIn("TARGET_TRANSPORT: codex", adapter)
        self.assertIn("--reasoning-effort xhigh", adapter)

    def test_registry_is_transport_keyed(self):
        text = ROUTER.read_text()
        self.assertIn("| Transport | Model ID |", text)
        self.assertIn("| `cursor` | `composer-2.5` |", text)
        self.assertIn("| `cursor` | `cursor-grok-4.6-high` |", text)
        self.assertIn("| `pi` | `opencode-go/minimax-m3` |", text)

    def test_check_report_requires_verification_for_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.yaml"
            path.write_text(VALID_COMPLETE)
            result = subprocess.run(
                [CHECK_REPORT, path], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_pstack_independence_documented(self):
        text = ROUTER.read_text()
        self.assertIn("Pstack is independent and Cursor-native.", text)
        self.assertIn("Do not vendor, modify, duplicate,", text)
        self.assertIn("or integrate pstack here.", text)


if __name__ == "__main__":
    unittest.main()
