import unittest
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "skills" / "tdd-implementation-packet" / "SKILL.md"
ROUTER = ROOT / "skills" / "model-router" / "SKILL.md"


class ContractTests(unittest.TestCase):
    def test_packet_requires_evidence_not_tool_ceremony(self):
        text = PACKET.read_text()
        for category in (
            "Desired behavior",
            "Exact source and test anchors",
            "Existing implementation or test patterns to reuse",
            "Relevant architecture boundaries",
        ):
            self.assertIn(category, text)
        for method in ("direct file inspection", "Serena", "ast-grep", "Graphify"):
            self.assertIn(method, text)
        self.assertNotIn("explicit `NOT_REQUIRED` reason for each", text)
        self.assertNotIn("Graphify, Serena, and ast-grep evidence when applicable", text)

    def test_missing_evidence_routes_before_packet_build(self):
        rows = {}
        order = []
        for line in ROUTER.read_text().splitlines():
            if not line.startswith("| `R-"):
                continue
            cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
            rows[cells[0]] = cells
            order.append(cells[0])

        expected = {
            "R-GATE": "LOCAL",
            "R-EVIDENCE": "GATHER_EVIDENCE",
            "R-BUILD": "BUILD_PACKET",
        }
        for rule, action in expected.items():
            self.assertIn(rule, rows)
            self.assertEqual(rows[rule][2], action)
        self.assertLess(order.index("R-GATE"), order.index("R-EVIDENCE"))
        self.assertLess(order.index("R-EVIDENCE"), order.index("R-BUILD"))

        cases = (
            ({"ungated_delta": True, "missing_evidence": True}, "R-GATE"),
            ({"missing_evidence": True}, "R-EVIDENCE"),
            ({"evidence_complete": True, "packet_exists": False}, "R-BUILD"),
        )
        for facts, expected_rule in cases:
            if facts.get("ungated_delta"):
                actual = "R-GATE"
            elif facts.get("missing_evidence"):
                actual = "R-EVIDENCE"
            elif facts.get("evidence_complete") and not facts.get("packet_exists"):
                actual = "R-BUILD"
            else:
                actual = "NONE"
            self.assertEqual(actual, expected_rule)

    def test_packet_completeness_is_checked_by_script(self):
        valid = """\
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
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "packet.md"
            packet.write_text(valid)
            result = subprocess.run(
                [ROOT / "scripts" / "check-packet", packet],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            packet.write_text(valid.replace("## Verification commands\n", ""))
            result = subprocess.run(
                [ROOT / "scripts" / "check-packet", packet],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Verification commands", result.stderr)

            packet.write_text(valid.replace("TEST_FIRST: REQUIRED", "TEST_FIRST: NOT_APPLICABLE"))
            result = subprocess.run(
                [ROOT / "scripts" / "check-packet", packet],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("behavior task contract", result.stderr)

    def test_critique_is_uncertainty_only_and_stops_after_second_block(self):
        text = ROUTER.read_text()
        for field in (
            "VERDICT: PASS | BLOCK",
            "REVIEWED_UNCERTAINTY:",
            "PACKET_CHECK: PASS",
            "TYPE: SPECIFICATION | ARCHITECTURE",
            "ISSUE:",
            "REQUIRED_EVIDENCE:",
            "REMAINING_RISKS:",
        ):
            self.assertIn(field, text)

        rows = {}
        for line in text.splitlines():
            if line.startswith("| `R-"):
                cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
                rows[cells[0]] = cells
        self.assertIn("unresolved specification or architecture uncertainty", rows["R-CRITIQUE"][1])
        self.assertEqual(rows["R-REBUILD"][2], "BUILD_PACKET")
        self.assertEqual(rows["R-RECRITIQUE"][2], "CRITIQUE_PACKET")
        self.assertEqual(rows["R-CRITIQUE-STOP"][2], "STOP")
        self.assertNotIn("dispatch after the next rebuild", text)
        self.assertIn("after one rebuild", rows["R-DELEGATE"][1])
        self.assertNotIn("no critique returned", rows["R-DELEGATE"][1])
        self.assertIn("records unresolved specification or architecture uncertainty", text)

    def test_implementation_lane_precedence_for_representative_cases(self):
        text = ROUTER.read_text()
        risk = text.index("Authentication, security, data-loss, backend")
        cheap = text.index("Routine docs, generated cleanup")
        frontend = text.index("Frontend UI behavior with bounded files")
        fallback = text.index("No lane matched")
        self.assertLess(risk, cheap)
        self.assertLess(cheap, frontend)
        self.assertLess(frontend, fallback)

        def lane(*, high_risk=False, frontend_ui=False, files=1, lines=10):
            if high_risk:
                return "GLM"
            if files <= 2 and lines <= 60:
                return "MINIMAX"
            if frontend_ui:
                return "CURSOR"
            return "GLM"

        self.assertEqual(lane(high_risk=True, files=1), "GLM")
        self.assertEqual(lane(frontend_ui=True, files=2, lines=40), "MINIMAX")
        self.assertEqual(lane(frontend_ui=True, files=3, lines=100), "CURSOR")
        self.assertEqual(lane(files=3, lines=100), "GLM")

    def test_documentation_states_expected_call_counts(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("## Expected model calls", readme)
        for scenario in (
            "Localized bounded change",
            "Unfamiliar cross-module change",
            "High-risk backend change",
            "Failed cheap-model implementation",
        ):
            self.assertIn(scenario, readme)
        self.assertIn("pre-versus-post", readme)


if __name__ == "__main__":
    unittest.main()
