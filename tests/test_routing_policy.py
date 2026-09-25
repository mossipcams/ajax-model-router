#!/usr/bin/env python3
"""Deterministic routing policy selection."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.facts import RoutingFacts  # noqa: E402
from semantic.policy import (  # noqa: E402
    MODEL_KEY_BY_ID,
    eligible_routes,
    has_hard_override,
    select_route,
)
from semantic.schema import RouteDecision  # noqa: E402

ALL_ROUTES = ("MINIMAX", "QWEN", "CURSOR", "GLM", "CODEX")


def _laya(route: str, confidence: float, **overrides) -> RouteDecision:
    other = "CURSOR" if route != "CURSOR" else "MINIMAX"
    base = dict(
        route=route,
        probabilities={route: confidence, other: max(0.0, 1 - confidence)},
        complexity=3,
        ambiguity=2,
        confidence=confidence,
    )
    base.update(overrides)
    return RouteDecision(**base)


class RoutingPolicyTests(unittest.TestCase):
    def test_eligible_routes_all_by_default(self):
        facts = RoutingFacts(user_request="add feature")
        self.assertEqual(eligible_routes(facts), ALL_ROUTES)

    def test_high_risk_removes_minimax(self):
        facts = RoutingFacts(user_request="fix auth token rotation")
        self.assertEqual(eligible_routes(facts), ("QWEN", "CURSOR", "GLM", "CODEX"))

    def test_unavailable_routes_removed(self):
        facts = RoutingFacts(unavailable_routes=["MINIMAX", "GLM"])
        self.assertEqual(eligible_routes(facts), ("QWEN", "CURSOR", "CODEX"))

    def test_explicit_user_model_override(self):
        facts = RoutingFacts(explicit_model="glm-5.2")
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "GLM")
        self.assertEqual(decision.rule_id, "R-EXPLICIT-MODEL")

    def test_explicit_non_registry_model(self):
        facts = RoutingFacts(explicit_model="my-local-model")
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "CUSTOM")
        self.assertEqual(decision.model_id, "my-local-model")

    def test_user_asked_codex(self):
        facts = RoutingFacts(user_request="use codex", user_asked_codex=True)
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "CODEX")
        self.assertEqual(decision.rule_id, "R-CODEX")

    def test_recorded_spec_uncertainty(self):
        facts = RoutingFacts(user_request="design cache", recorded_spec_uncertainty=True)
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "GLM")
        self.assertEqual(decision.rule_id, "R-GLM")

    def test_retry_escalates_from_minimax(self):
        facts = RoutingFacts(is_retry=True, previous_model_key="MINIMAX")
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "GLM")
        self.assertEqual(decision.rule_id, "R-RETRY-ESCALATE")

    def test_retry_escalates_from_cursor(self):
        facts = RoutingFacts(is_retry=True, previous_model_key="CURSOR")
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "CODEX")
        self.assertEqual(decision.rule_id, "R-RETRY-ESCALATE")

    def test_hard_override_wins_over_laya(self):
        facts = RoutingFacts(user_asked_codex=True)
        decision = select_route(facts, laya=_laya("MINIMAX", 0.99))
        self.assertEqual(decision.model_key, "CODEX")
        self.assertFalse(decision.laya_used)
        self.assertIsNone(decision.laya_confidence)

    def test_laya_route_used_when_eligible_and_confident(self):
        facts = RoutingFacts(user_request="refactor parser", diff_line_count=120)
        laya = _laya("GLM", 0.85)
        decision = select_route(facts, laya=laya)
        self.assertEqual(decision.model_key, "GLM")
        self.assertEqual(decision.rule_id, "R-LAYA")
        self.assertTrue(decision.laya_used)
        self.assertEqual(decision.laya_confidence, 0.85)
        self.assertEqual(decision.complexity, 3)
        self.assertEqual(decision.ambiguity, 2)
        self.assertIsNone(decision.fallback_reason)

    def test_laya_low_confidence_falls_back(self):
        facts = RoutingFacts(user_request="refactor parser", diff_line_count=120)
        laya = _laya("GLM", 0.5)
        decision = select_route(facts, laya=laya, laya_fallback_reason="low confidence")
        self.assertEqual(decision.model_key, "QWEN")
        self.assertEqual(decision.rule_id, "R-QWEN")
        self.assertFalse(decision.laya_used)
        self.assertEqual(decision.fallback_reason, "low confidence")

    def test_laya_ineligible_route_falls_back(self):
        facts = RoutingFacts(
            user_request="trivial docs",
            changed_file_count=1,
            diff_line_count=5,
            unavailable_routes=["MINIMAX"],
        )
        laya = RouteDecision(
            route="MINIMAX",
            probabilities={"MINIMAX": 0.9, "CURSOR": 0.1},
            complexity=1,
            ambiguity=1,
            confidence=0.9,
        )
        decision = select_route(facts, laya=laya)
        self.assertEqual(decision.model_key, "QWEN")
        self.assertEqual(decision.fallback_reason, "laya route MINIMAX not eligible")

    def test_deterministic_default_bounded_trivial(self):
        facts = RoutingFacts(
            user_request="fix typo", changed_file_count=1, diff_line_count=5
        )
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "MINIMAX")
        self.assertEqual(decision.rule_id, "R-MINIMAX")

    def test_deterministic_default_large_change(self):
        facts = RoutingFacts(user_request="big refactor", diff_line_count=500)
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "QWEN")
        self.assertEqual(decision.rule_id, "R-QWEN")

    def test_cursor_is_default_when_qwen_unavailable(self):
        facts = RoutingFacts(user_request="big refactor", unavailable_routes=["QWEN"])
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "CURSOR")
        self.assertEqual(decision.rule_id, "R-CURSOR")

    def test_risk_level_from_facts(self):
        low = select_route(RoutingFacts(user_request="docs", diff_line_count=5))
        self.assertEqual(low.risk, "low")
        medium = select_route(RoutingFacts(user_request="refactor", diff_line_count=500))
        self.assertEqual(medium.risk, "medium")
        high = select_route(RoutingFacts(user_request="rotate auth tokens"))
        self.assertEqual(high.risk, "high")

    def test_has_hard_override_detection(self):
        self.assertTrue(has_hard_override(RoutingFacts(explicit_model="glm-5.2")))
        self.assertTrue(has_hard_override(RoutingFacts(user_asked_codex=True)))
        self.assertTrue(has_hard_override(RoutingFacts(recorded_spec_uncertainty=True)))
        self.assertTrue(
            has_hard_override(RoutingFacts(is_retry=True, previous_model_key="MINIMAX"))
        )
        self.assertFalse(has_hard_override(RoutingFacts(user_request="normal task")))

    def test_model_key_by_id_registry(self):
        self.assertEqual(MODEL_KEY_BY_ID["gpt-6-astra"], "CODEX")
        self.assertEqual(MODEL_KEY_BY_ID["composer-2.5"], "CURSOR")
        self.assertEqual(MODEL_KEY_BY_ID["qwen3.8-27b"], "QWEN")
        self.assertEqual(MODEL_KEY_BY_ID["minimax-m3"], "MINIMAX")
        self.assertEqual(MODEL_KEY_BY_ID["glm-5.2"], "GLM")


if __name__ == "__main__":
    unittest.main()
