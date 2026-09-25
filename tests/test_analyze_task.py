#!/usr/bin/env python3
"""analyze-task CLI output: execution block, SCOPE/VERIFY mapping, Laya fallback."""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic import run_analyze_task  # noqa: E402
from semantic.analyzer import DisabledSemanticAnalyzer  # noqa: E402
from semantic.schema import RouteDecision  # noqa: E402


def _laya(route: str, confidence: float) -> RouteDecision:
    other = "CURSOR" if route != "CURSOR" else "MINIMAX"
    return RouteDecision(
        route=route,
        probabilities={route: confidence, other: max(0.0, 1 - confidence)},
        complexity=3,
        ambiguity=2,
        confidence=confidence,
    )


class AnalyzeTaskTests(unittest.TestCase):
    def test_deterministic_execution_when_laya_disabled(self):
        output = run_analyze_task(
            {"task": "update readme"}, analyzer=DisabledSemanticAnalyzer()
        )
        execution = output["execution"]
        self.assertEqual(execution["AGENT"], "pi")
        self.assertEqual(execution["MODEL"], "qwen3.8-27b")
        self.assertIn("RISK", execution)
        self.assertIn("REASON", execution)
        self.assertIn("FALLBACK", execution)
        self.assertEqual(output["explanation"]["analysis_source"], "disabled")
        self.assertTrue(output["explanation"]["fallback_used"])

    def test_laya_decision_flows_into_execution(self):
        with mock.patch(
            "semantic.analyze_with_fallback",
            return_value=(_laya("GLM", 0.85), None, "laya"),
        ):
            output = run_analyze_task(
                {"task": "design new billing subsystem"},
                analyzer=DisabledSemanticAnalyzer(),
            )
        execution = output["execution"]
        self.assertEqual(execution["AGENT"], "pi")
        self.assertEqual(execution["MODEL"], "glm-5.2")
        self.assertEqual(output["explanation"]["selected_route"], "GLM")
        self.assertEqual(output["explanation"]["analysis_source"], "laya")
        self.assertEqual(output["decision"]["rule_id"], "R-LAYA")

    def test_hard_override_skips_laya(self):
        output = run_analyze_task(
            {"task": "use codex for this", "user_asked_codex": True},
            analyzer=DisabledSemanticAnalyzer(),
        )
        self.assertEqual(output["execution"]["MODEL"], "gpt-6-astra")
        self.assertEqual(
            output["explanation"]["analysis_source"], "skipped_hard_override"
        )
        self.assertEqual(output["decision"]["rule_id"], "R-CODEX")

    def test_single_eligible_skips_laya(self):
        output = run_analyze_task(
            {
                "task": "fix typo",
                "changed_file_count": 1,
                "diff_line_count": 5,
                "unavailable_routes": ["MINIMAX", "QWEN", "GLM", "CODEX"],
            },
            analyzer=DisabledSemanticAnalyzer(),
        )
        self.assertEqual(output["execution"]["MODEL"], "composer-2.5")
        self.assertEqual(
            output["explanation"]["analysis_source"], "skipped_single_eligible"
        )

    def test_scope_from_known_subsystem(self):
        output = run_analyze_task(
            {"task": "fix login bug", "known_subsystem": "billing"},
            analyzer=DisabledSemanticAnalyzer(),
        )
        self.assertIn("SCOPE", output["execution"])
        self.assertIn("billing", output["execution"]["SCOPE"])

    def test_verify_uses_test_command_when_provided(self):
        output = run_analyze_task(
            {"task": "fix bug", "test_command": "python3 -m unittest tests.test_auth"},
            analyzer=DisabledSemanticAnalyzer(),
        )
        self.assertEqual(
            output["execution"]["VERIFY"],
            ["python3 -m unittest tests.test_auth"],
        )

    def test_verify_frontend_visual(self):
        output = run_analyze_task(
            {
                "task": "update login page styles",
                "changed_files": ["src/login.tsx"],
            },
            analyzer=DisabledSemanticAnalyzer(),
        )
        self.assertTrue(
            any(
                "visual" in item.lower() or "browser" in item.lower()
                for item in output["execution"]["VERIFY"]
            ),
            output["execution"]["VERIFY"],
        )

    def test_omit_empty_scope_and_verify(self):
        output = run_analyze_task(
            {"task": "fix typo in readme"}, analyzer=DisabledSemanticAnalyzer()
        )
        self.assertNotIn("SCOPE", output["execution"])
        self.assertNotIn("VERIFY", output["execution"])

    def test_run_analyze_task_returns_execution_json(self):
        output = run_analyze_task(
            {"task": "docs tweak", "changed_files": ["README.md"]},
            analyzer=DisabledSemanticAnalyzer(),
        )
        self.assertIn("execution", output)
        self.assertIn("decision", output)
        self.assertIn("explanation", output)
        self.assertIn("AGENT", output["execution"])
        self.assertIn("MODEL", output["execution"])

    def test_skill_documents_analyze_task_before_execution(self):
        skill = (ROOT / "skills" / "model-router" / "SKILL.md").read_text()
        self.assertIn("scripts/analyze-task", skill)
        self.assertIn("before emitting `EXECUTION`", skill)
        self.assertIn("Skip `analyze-task` for `R-PARENT`", skill)
        self.assertIn("Do **not** call `analyze-task` from", skill)


if __name__ == "__main__":
    unittest.main()
