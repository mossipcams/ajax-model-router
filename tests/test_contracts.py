#!/usr/bin/env python3
"""Outcome and boundary contracts for the thin router control plane."""

import re
import tempfile
import unittest
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "skills" / "model-router" / "SKILL.md"
CHECK_REPORT = ROOT / "scripts" / "check-report"

VALID_COMPLETE = """\
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


class ContractTests(unittest.TestCase):
    def test_one_execution_decision_leads_to_execute(self):
        text = ROUTER.read_text()
        self.assertIn("route → execute → verify", text)
        self.assertIn("EXECUTION:", text)
        self.assertNotIn("GATHER_EVIDENCE", text)
        self.assertNotIn("BUILD_PACKET", text)
        self.assertNotIn("CRITIQUE_PACKET", text)
        # No multi-stage reroute theater between route and execute.
        self.assertIn("Do not reroute between artificial lifecycle stages.", text)

    def test_parent_must_not_pre_explore_before_dispatch(self):
        text = ROUTER.read_text()
        self.assertIn(
            "Before dispatch, the parent must not Grep, Read, or search the repository",
            text,
        )
        self.assertIn("do not explore to perfect scope first", text)
        self.assertIn("no pre-dispatch repo exploration", text)

    def test_delegate_autonomy_inside_scope(self):
        text = ROUTER.read_text()
        for phrase in (
            "Investigate the repository as needed.",
            "Choose the implementation approach.",
            "Run appropriate verification.",
            "delegate owns investigation, edit selection, test selection, and",
        ):
            self.assertIn(phrase, text)
        self.assertNotIn("Follow Code anchors when provided.", text)
        self.assertNotIn("Edit instructions", text)

    def test_scope_expansion_rejected(self):
        text = ROUTER.read_text()
        self.assertIn(
            "Stop if completing the task requires expanding beyond the allowed scope.",
            text,
        )
        self.assertIn("Expanding scope requires a new `EXECUTION`.", text)

    def test_reroute_after_executor_failure(self):
        text = ROUTER.read_text()
        self.assertIn("the selected executor fails", text)
        self.assertIn("reroute once via `FALLBACK`", text)
        self.assertIn("Stop after two failed execute rounds", text)

    def test_proportional_review_by_risk(self):
        text = ROUTER.read_text()
        self.assertIn("## Risk-based review", text)
        self.assertIn("Delegate verification is sufficient by default.", text)
        self.assertIn("Parent reads all changed hunks.", text)
        self.assertIn("Parent independently reviews affected behavior.", text)
        self.assertIn(
            "Do not apply high-risk ceremony to routine changes.", text
        )

    def test_absent_obsolete_packet_and_tdd_requirements(self):
        text = ROUTER.read_text()
        for forbidden in (
            "tdd-implementation-packet",
            "PACKET_STATUS",
            "TEST_FIRST",
            "PACKET_REVIEW",
            "dispatch_level",
            "estimated_lines",
            "R-SIZE-SPLIT",
            "check-packet",
            "check-dispatch",
        ):
            self.assertNotIn(forbidden, text)
        self.assertFalse((ROOT / "skills" / "tdd-implementation-packet").exists())
        self.assertFalse((ROOT / "scripts" / "check-packet").exists())
        self.assertFalse((ROOT / "scripts" / "check-dispatch").exists())
        self.assertFalse((ROOT / "CALIBRATION.md").exists())

    def test_codex_uses_requested_model_and_xhigh_effort(self):
        router = ROUTER.read_text()
        adapter = (ROOT / "skills" / "codex-delegate" / "SKILL.md").read_text()
        self.assertIn("| `CODEX` | `gpt-6-astra` |", router)
        self.assertNotIn("gpt-5.5", router)
        self.assertIn("--reasoning-effort xhigh", adapter)
        self.assertIn("--tool codex", adapter)
        self.assertIn("acpx", adapter)
        self.assertIn("workspace-write", adapter)
        self.assertNotIn("packet-critique", adapter)
        self.assertNotIn("codex app-server", adapter)

    def test_implementation_lane_defaults_to_cursor(self):
        rows = []
        for line in ROUTER.read_text().splitlines():
            if not line.startswith("| `R-"):
                continue
            cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
            rows.append(cells)
        ids = [row[0] for row in rows]
        self.assertLess(ids.index("R-GLM"), ids.index("R-MINIMAX"))
        self.assertLess(ids.index("R-MINIMAX"), ids.index("R-CURSOR"))
        cursor = next(row for row in rows if row[0] == "R-CURSOR")
        self.assertEqual(cursor[2], "cursor")
        self.assertEqual(cursor[3], "CURSOR")

    def test_check_report_requires_verification_for_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.yaml"
            path.write_text(VALID_COMPLETE)
            result = subprocess.run(
                [CHECK_REPORT, path], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            bad = Path(tmp) / "bad.yaml"
            bad.write_text(
                "DELEGATE_REPORT:\n"
                "  STATUS: COMPLETE\n"
                "  CHANGED_FILES: []\n"
                "  VERIFICATION: []\n"
                "  CONCERNS: []\n"
            )
            result = subprocess.run(
                [CHECK_REPORT, bad], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)

    def test_route_table_has_no_packet_stages(self):
        actions = re.findall(r"\| `R-[A-Z-]+` \|.*?\| `(parent|cursor|codex|pi|—)` \|", ROUTER.read_text())
        self.assertTrue(actions)
        text = ROUTER.read_text()
        self.assertNotRegex(text, r"ACTION:.*GATHER_EVIDENCE")
        self.assertNotRegex(text, r"ACTION:.*BUILD_PACKET")


if __name__ == "__main__":
    unittest.main()
