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
    fallback_chain,
    has_hard_override,
    select_route,
)
from semantic.schema import RouteDecision  # noqa: E402

ALL_ROUTES = ("DEEPSEEK", "QWEN", "HAIKU", "CURSOR", "CODEX")


def _sensor(route: str, confidence: float, **overrides) -> RouteDecision:
    other = "CURSOR" if route != "CURSOR" else "DEEPSEEK"
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

    def test_high_risk_removes_deepseek(self):
        facts = RoutingFacts(user_request="fix auth token rotation")
        self.assertEqual(eligible_routes(facts), ("QWEN", "HAIKU", "CURSOR", "CODEX"))

    def test_unavailable_routes_removed(self):
        facts = RoutingFacts(unavailable_routes=["DEEPSEEK", "CURSOR"])
        self.assertEqual(eligible_routes(facts), ("QWEN", "HAIKU", "CODEX"))

    def test_explicit_user_model_override(self):
        facts = RoutingFacts(explicit_model="deepseek-v4.1-flash")
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "DEEPSEEK")
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
        self.assertEqual(decision.model_key, "DEEPSEEK")
        self.assertEqual(decision.rule_id, "R-DEEPSEEK-SPEC")

    def test_retry_from_qwen_or_deepseek_goes_to_haiku(self):
        for previous in ("QWEN", "DEEPSEEK"):
            decision = select_route(RoutingFacts(is_retry=True, previous_model_key=previous))
            self.assertEqual((decision.agent, decision.model_key), ("claude", "HAIKU"))
            self.assertEqual(decision.rule_id, "R-RETRY-ESCALATE")

    def test_retry_from_haiku_goes_to_cursor_and_back(self):
        self.assertEqual(
            select_route(RoutingFacts(is_retry=True, previous_model_key="HAIKU")).model_key, "CURSOR"
        )
        self.assertEqual(
            select_route(RoutingFacts(is_retry=True, previous_model_key="CURSOR")).model_key, "HAIKU"
        )

    def test_retry_uses_cursor_when_haiku_down(self):
        facts = RoutingFacts(is_retry=True, previous_model_key="QWEN", unavailable_routes=["HAIKU"])
        self.assertEqual(select_route(facts).model_key, "CURSOR")

    def test_retry_never_reaches_premium_models(self):
        for previous in ("QWEN", "DEEPSEEK", "HAIKU", "CURSOR"):
            facts = RoutingFacts(
                is_retry=True, previous_model_key=previous, unavailable_routes=["HAIKU", "CURSOR"]
            )
            decision = select_route(facts)
            self.assertNotIn(decision.model_key, {"CODEX"})
            self.assertNotIn("opus", decision.model_id)
            self.assertNotIn("astra", decision.model_id)

    def test_hard_override_wins_over_sensor(self):
        facts = RoutingFacts(user_asked_codex=True)
        decision = select_route(facts, sensor=_sensor("DEEPSEEK", 0.99))
        self.assertEqual(decision.model_key, "CODEX")
        self.assertFalse(decision.sensor_used)
        self.assertIsNone(decision.sensor_confidence)

    def test_confident_sensor_never_diverts_from_qwen(self):
        facts = RoutingFacts(user_request="refactor parser", diff_line_count=120)
        decision = select_route(facts, sensor=_sensor("OPUS", 0.99))
        self.assertEqual(decision.model_key, "QWEN")
        self.assertEqual(decision.rule_id, "R-QWEN")
        self.assertFalse(decision.sensor_used)

    def test_sensor_low_confidence_falls_back(self):
        facts = RoutingFacts(user_request="refactor parser", diff_line_count=120)
        sensor = _sensor("OPUS", 0.5)
        decision = select_route(
            facts, sensor=sensor, sensor_fallback_reason="low confidence"
        )
        self.assertEqual(decision.model_key, "QWEN")
        self.assertEqual(decision.rule_id, "R-QWEN")
        self.assertFalse(decision.sensor_used)
        self.assertEqual(decision.fallback_reason, "low confidence")

    def test_trivial_change_still_routes_to_qwen(self):
        facts = RoutingFacts(
            user_request="fix typo", changed_file_count=1, diff_line_count=5
        )
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "QWEN")
        self.assertEqual(decision.rule_id, "R-QWEN")

    def test_qwen_unavailable_falls_to_haiku_then_cursor(self):
        facts = RoutingFacts(user_request="fix typo", unavailable_routes=["QWEN"])
        self.assertEqual(select_route(facts).model_key, "HAIKU")
        facts = RoutingFacts(user_request="fix typo", unavailable_routes=["QWEN", "HAIKU"])
        self.assertEqual(select_route(facts).model_key, "CURSOR")

    def test_deterministic_default_large_change(self):
        facts = RoutingFacts(user_request="big refactor", diff_line_count=500)
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "QWEN")
        self.assertEqual(decision.rule_id, "R-QWEN")

    def test_haiku_is_default_when_qwen_unavailable(self):
        facts = RoutingFacts(user_request="big refactor", unavailable_routes=["QWEN"])
        decision = select_route(facts)
        self.assertEqual(decision.model_key, "HAIKU")
        self.assertEqual(decision.rule_id, "R-HAIKU")

    def test_cursor_is_default_when_qwen_and_haiku_unavailable(self):
        facts = RoutingFacts(
            user_request="big refactor", unavailable_routes=["QWEN", "HAIKU"]
        )
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
        self.assertTrue(has_hard_override(RoutingFacts(explicit_model="deepseek-v4.1-flash")))
        self.assertTrue(has_hard_override(RoutingFacts(user_asked_codex=True)))
        self.assertTrue(has_hard_override(RoutingFacts(recorded_spec_uncertainty=True)))
        self.assertTrue(
            has_hard_override(RoutingFacts(is_retry=True, previous_model_key="DEEPSEEK"))
        )
        self.assertFalse(has_hard_override(RoutingFacts(user_request="normal task")))

    def test_model_key_by_id_registry(self):
        self.assertEqual(MODEL_KEY_BY_ID["gpt-6-astra"], "CODEX")
        self.assertEqual(MODEL_KEY_BY_ID["composer-2.5"], "CURSOR")
        self.assertEqual(MODEL_KEY_BY_ID["current"], "QWEN")
        self.assertEqual(MODEL_KEY_BY_ID["deepseek-v4.1-flash"], "DEEPSEEK")
        self.assertNotIn("glm-5.2", MODEL_KEY_BY_ID)
        self.assertNotIn("minimax-m3", MODEL_KEY_BY_ID)
        self.assertNotIn("claude-opus-5-5", MODEL_KEY_BY_ID)


class FallbackChainTests(unittest.TestCase):
    def test_fallback_is_never_the_selected_route(self):
        for route in ALL_ROUTES:
            chain = fallback_chain(route, ALL_ROUTES)
            self.assertNotIn(route, chain)
            if route != "DEEPSEEK":
                self.assertNotIn("DEEPSEEK", chain)
            self.assertNotIn("CODEX", chain)

    def test_cursor_routes_are_cheap_only(self):
        from semantic.policy import REGISTRY

        cursor_models = [model for agent, model in REGISTRY.values() if agent == "cursor"]
        self.assertEqual(cursor_models, ["composer-2.5"])

    def test_haiku_runs_on_claude_code(self):
        from semantic.policy import REGISTRY

        self.assertEqual(REGISTRY["HAIKU"], ("claude", "claude-haiku-5-5"))

    def test_chain_prefers_stronger_routes_then_wraps(self):
        self.assertEqual(fallback_chain("QWEN", ALL_ROUTES), ("HAIKU", "CURSOR"))
        self.assertEqual(fallback_chain("CURSOR", ALL_ROUTES), ("QWEN", "HAIKU"))
        self.assertEqual(fallback_chain("CODEX", ALL_ROUTES), ("QWEN", "HAIKU", "CURSOR"))

    def test_chain_skips_unavailable_routes(self):
        self.assertEqual(
            fallback_chain("CURSOR", ("QWEN", "CURSOR", "CODEX")), ("QWEN",)
        )

    def test_decision_exposes_chain_and_next_fallback(self):
        decision = select_route(RoutingFacts(user_request="add feature"))
        self.assertTrue(decision.fallback_chain)
        self.assertEqual(decision.fallback, decision.fallback_chain[0])
        self.assertNotEqual(decision.fallback, decision.model_key)


if __name__ == "__main__":
    unittest.main()
