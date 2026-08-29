#!/usr/bin/env python3
"""Deterministic routing policy selection."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.facts import RoutingFacts  # noqa: E402
from semantic.policy import select_route  # noqa: E402
from semantic.schema import (  # noqa: E402
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


def _features(**overrides):
    base = dict(
        task_type=TaskType.BUG_FIX,
        domains=(TaskDomain.RUST_BACKEND,),
        complexity=Complexity.MEDIUM,
        scope=ChangeScope.LOCALIZED,
        reasoning_depth=ReasoningDepth.MEDIUM,
        uncertainty=Uncertainty.LOW,
        requires_repo_discovery=False,
        requires_visual_validation=False,
        requires_large_context=False,
        likely_context_size=ContextSize.SMALL,
        risk=TaskRisk.MEDIUM,
        confidence=0.9,
    )
    base.update(overrides)
    return TaskFeatures(**base)


class RoutingPolicyTests(unittest.TestCase):
    def test_default_cursor_when_no_signals(self):
        decision = select_route(None, RoutingFacts())
        self.assertEqual(decision.model_key, "CURSOR")
        self.assertEqual(decision.rule_id, "R-CURSOR")

    def test_explicit_user_model_override(self):
        facts = RoutingFacts(explicit_model="gpt-5.6-sol")
        decision = select_route(None, facts)
        self.assertEqual(decision.model_key, "CODEX")
        self.assertEqual(decision.rule_id, "R-EXPLICIT-MODEL")

    def test_user_asked_codex(self):
        facts = RoutingFacts(user_asked_codex=True)
        decision = select_route(None, facts)
        self.assertEqual(decision.model_key, "CODEX")

    def test_recorded_spec_uncertainty_glm(self):
        facts = RoutingFacts(recorded_spec_uncertainty=True)
        decision = select_route(None, facts)
        self.assertEqual(decision.model_key, "GLM")

    def test_architecture_high_complexity_codex(self):
        features = _features(
            task_type=TaskType.ARCHITECTURE,
            complexity=Complexity.HIGH,
            scope=ChangeScope.REPO_WIDE,
        )
        decision = select_route(features, RoutingFacts())
        self.assertEqual(decision.model_key, "CODEX")
        self.assertEqual(decision.rule_id, "R-ARCH-HIGH")

    def test_localized_low_complexity_cursor(self):
        features = _features(
            complexity=Complexity.LOW,
            scope=ChangeScope.LOCALIZED,
            task_type=TaskType.FEATURE,
        )
        decision = select_route(features, RoutingFacts())
        self.assertEqual(decision.model_key, "CURSOR")
        self.assertEqual(decision.rule_id, "R-LOCALIZED-IMPL")

    def test_retry_escalates_from_minimax(self):
        facts = RoutingFacts(is_retry=True, previous_model_key="MINIMAX")
        decision = select_route(None, facts)
        self.assertEqual(decision.model_key, "GLM")

    def test_retry_escalates_from_cursor(self):
        facts = RoutingFacts(is_retry=True, previous_model_key="CURSOR")
        decision = select_route(None, facts)
        self.assertEqual(decision.model_key, "CODEX")

    def test_slm_cannot_override_explicit_model(self):
        features = _features(task_type=TaskType.ARCHITECTURE, complexity=Complexity.HIGH)
        facts = RoutingFacts(explicit_model="composer-2.5")
        decision = select_route(features, facts, slm_used=True)
        self.assertEqual(decision.model_key, "CURSOR")

    def test_trivial_minimax_within_limits(self):
        features = _features(
            complexity=Complexity.TRIVIAL,
            task_type=TaskType.DOCUMENTATION,
            reasoning_depth=ReasoningDepth.SHALLOW,
        )
        facts = RoutingFacts(changed_file_count=1, diff_line_count=10)
        decision = select_route(features, facts)
        self.assertEqual(decision.model_key, "MINIMAX")


if __name__ == "__main__":
    unittest.main()
