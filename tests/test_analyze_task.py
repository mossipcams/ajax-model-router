#!/usr/bin/env python3
"""analyze-task CLI output: execution block, SCOPE/VERIFY mapping, SLM fallback."""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic import run_analyze_task  # noqa: E402
from semantic.analyzer import DisabledSemanticAnalyzer  # noqa: E402
from semantic.explain import build_execution_block  # noqa: E402
from semantic.facts import RoutingFacts  # noqa: E402
from semantic.policy import select_route  # noqa: E402
from semantic.schema import (  # noqa: E402
    ChangeScope,
    Complexity,
    ContextRequirements,
    ContextSize,
    ReasoningDepth,
    TaskDomain,
    TaskFeatures,
    TaskRisk,
    TaskType,
    Uncertainty,
)


def _features(**overrides):
    base = dict(
        task_type=TaskType.BUG_FIX,
        domains=(TaskDomain.FRONTEND,),
        complexity=Complexity.LOW,
        scope=ChangeScope.LOCALIZED,
        reasoning_depth=ReasoningDepth.SHALLOW,
        uncertainty=Uncertainty.LOW,
        requires_repo_discovery=False,
        requires_visual_validation=False,
        requires_large_context=False,
        likely_context_size=ContextSize.SMALL,
        risk=TaskRisk.LOW,
        confidence=0.9,
    )
    base.update(overrides)
    return TaskFeatures(**base)


class AnalyzeTaskTests(unittest.TestCase):
    def test_execution_from_policy_not_slm_model(self):
        """Policy registry picks MODEL even when SLM features differ."""
        features = _features(
            task_type=TaskType.ARCHITECTURE,
            complexity=Complexity.HIGH,
            scope=ChangeScope.REPO_WIDE,
        )
        facts = RoutingFacts(
            user_request="design new auth subsystem",
            changed_file_count=1,
            diff_line_count=5,
        )
        decision = select_route(features, facts, slm_used=True)
        self.assertEqual(decision.model_key, "CODEX")
        self.assertEqual(decision.model_id, "gpt-5.6-sol")

        with mock.patch(
            "semantic.analyze_with_fallback",
            return_value=(features, None, "slm"),
        ):
            output = run_analyze_task(
                {"task": facts.user_request},
                analyzer=DisabledSemanticAnalyzer(),
            )
        execution = output["execution"]
        self.assertEqual(execution["AGENT"], "codex")
        self.assertEqual(execution["MODEL"], "gpt-5.6-sol")
        self.assertEqual(execution["RISK"], decision.risk)
        self.assertEqual(execution["REASON"], decision.reason)
        self.assertEqual(execution["FALLBACK"], decision.fallback)

    def test_unreachable_slm_still_emits_execution(self):
        with mock.patch(
            "semantic.analyze_with_fallback",
            return_value=(None, "semantic analysis disabled", "disabled"),
        ):
            output = run_analyze_task(
                {"task": "update readme"},
                analyzer=DisabledSemanticAnalyzer(),
            )
        execution = output["execution"]
        self.assertEqual(execution["AGENT"], "cursor")
        self.assertEqual(execution["MODEL"], "composer-2.5")
        self.assertIn("REASON", execution)
        self.assertIn("FALLBACK", execution)

    def test_scope_from_likely_subsystems(self):
        features = _features(domains=(TaskDomain.RUST_BACKEND, TaskDomain.TESTING))
        facts = RoutingFacts(known_subsystem="auth")
        from semantic.context import derive_context_requirements

        context = derive_context_requirements(features, facts)
        decision = select_route(features, facts)
        block = build_execution_block(
            decision=decision,
            context=context,
            facts=facts,
            features=features,
        )
        self.assertIn("SCOPE", block)
        self.assertIn("rust_backend", block["SCOPE"])
        self.assertIn("testing", block["SCOPE"])
        self.assertIn("auth", block["SCOPE"])

    def test_verify_related_tests_and_visual(self):
        features = _features(
            task_type=TaskType.BUG_FIX,
            requires_visual_validation=True,
        )
        facts = RoutingFacts()
        from semantic.context import derive_context_requirements

        context = derive_context_requirements(features, facts)
        decision = select_route(features, facts)
        block = build_execution_block(
            decision=decision,
            context=context,
            facts=facts,
            features=features,
        )
        self.assertIn("VERIFY", block)
        self.assertTrue(
            any("test" in item.lower() for item in block["VERIFY"]),
            block["VERIFY"],
        )
        self.assertTrue(
            any("visual" in item.lower() or "browser" in item.lower() for item in block["VERIFY"]),
            block["VERIFY"],
        )

    def test_verify_uses_test_command_when_provided(self):
        features = _features()
        facts = RoutingFacts(test_command="python3 -m unittest tests.test_auth")
        from semantic.context import derive_context_requirements

        context = derive_context_requirements(features, facts)
        decision = select_route(features, facts)
        block = build_execution_block(
            decision=decision,
            context=context,
            facts=facts,
            features=features,
        )
        self.assertEqual(block["VERIFY"], ["python3 -m unittest tests.test_auth"])

    def test_omit_empty_scope_and_verify(self):
        decision = select_route(None, RoutingFacts())
        block = build_execution_block(
            decision=decision,
            context=ContextRequirements(
                architecture_docs=False,
                recent_diff=False,
                related_tests=False,
                git_history=False,
                likely_subsystems=(),
                context_budget=ContextSize.UNKNOWN,
            ),
            facts=RoutingFacts(),
            features=None,
        )
        self.assertNotIn("SCOPE", block)
        self.assertNotIn("VERIFY", block)

    def test_run_analyze_task_returns_execution_json(self):
        with mock.patch(
            "semantic.analyze_with_fallback",
            return_value=(None, "semantic analysis disabled", "disabled"),
        ):
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
