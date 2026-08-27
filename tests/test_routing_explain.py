#!/usr/bin/env python3
"""Structured routing explanation output."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.context import derive_context_requirements  # noqa: E402
from semantic.explain import build_explanation  # noqa: E402
from semantic.facts import RoutingFacts  # noqa: E402
from semantic.policy import select_route  # noqa: E402


class RoutingExplainTests(unittest.TestCase):
    def test_explanation_has_required_fields(self):
        facts = RoutingFacts(user_request="fix login bug")
        decision = select_route(None, facts)
        context = derive_context_requirements(None, facts)
        explanation = build_explanation(
            facts=facts,
            features=None,
            decision=decision,
            context=context,
            fallback_reason="semantic analysis disabled",
            analysis_source="disabled",
        )
        for key in (
            "facts",
            "matched_rule",
            "selected_agent",
            "selected_model_key",
            "selected_model_id",
            "context_strategy",
            "fallback_reason",
        ):
            self.assertIn(key, explanation)
        self.assertNotIn("chain_of_thought", explanation)
        self.assertNotIn("reasoning", str(explanation).lower().split("reasoning_depth"))

    def test_explanation_includes_slm_confidence_when_present(self):
        from semantic.schema import (
            ChangeScope,
            Complexity,
            ContextSize,
            ReasoningDepth,
            TaskDomain,
            TaskFeatures,
            TaskRisk,
            TaskType,
            Uncertainty,
        )

        features = TaskFeatures(
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
            confidence=0.92,
        )
        facts = RoutingFacts()
        decision = select_route(features, facts, slm_used=True)
        context = derive_context_requirements(features, facts)
        explanation = build_explanation(
            facts=facts,
            features=features,
            decision=decision,
            context=context,
            slm_confidence=0.92,
            analysis_source="slm",
        )
        self.assertEqual(explanation["slm_confidence"], 0.92)
        self.assertEqual(explanation["task_features"]["task_type"], "bug_fix")


if __name__ == "__main__":
    unittest.main()
