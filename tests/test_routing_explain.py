#!/usr/bin/env python3
"""Structured routing explanation output."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.context import derive_context_requirements  # noqa: E402
from semantic.explain import build_execution_block, build_explanation  # noqa: E402
from semantic.facts import RoutingFacts  # noqa: E402
from semantic.policy import select_route  # noqa: E402
from semantic.schema import RouteDecision  # noqa: E402


def _laya(route: str = "GLM", confidence: float = 0.85) -> RouteDecision:
    other = "CURSOR" if route != "CURSOR" else "MINIMAX"
    return RouteDecision(
        route=route,
        probabilities={route: confidence, other: max(0.0, 1 - confidence)},
        complexity=3,
        ambiguity=2,
        confidence=confidence,
    )


class RoutingExplainTests(unittest.TestCase):
    def test_explanation_has_required_fields(self):
        facts = RoutingFacts(user_request="add csv export")
        decision = select_route(facts)
        context = derive_context_requirements(None, facts)
        explanation = build_explanation(
            facts=facts,
            decision=decision,
            context=context,
            analysis_source="disabled",
        )
        for key in (
            "facts",
            "analysis_source",
            "laya",
            "eligible_routes",
            "selected_route",
            "route_confidence",
            "route_probabilities",
            "complexity",
            "ambiguity",
            "fallback_used",
            "fallback_reason",
            "matched_rule",
            "selected_agent",
            "selected_model_key",
            "selected_model_id",
            "risk",
            "reason",
            "context_strategy",
        ):
            self.assertIn(key, explanation)
        self.assertIsNone(explanation["laya"])
        self.assertEqual(explanation["selected_route"], "QWEN")
        self.assertEqual(explanation["matched_rule"], "R-QWEN")

    def test_explanation_includes_laya_confidence_when_present(self):
        facts = RoutingFacts(user_request="design cache layer", diff_line_count=120)
        laya = _laya("GLM", 0.85)
        decision = select_route(facts, laya=laya)
        context = derive_context_requirements(laya, facts)
        explanation = build_explanation(
            facts=facts,
            decision=decision,
            context=context,
            laya=laya,
            analysis_source="laya",
        )
        self.assertEqual(explanation["analysis_source"], "laya")
        self.assertEqual(explanation["laya"]["route"], "GLM")
        self.assertEqual(explanation["laya"]["confidence"], 0.85)
        self.assertEqual(explanation["route_confidence"], 0.85)
        self.assertEqual(explanation["route_probabilities"]["GLM"], 0.85)
        self.assertEqual(explanation["complexity"], 3)
        self.assertEqual(explanation["ambiguity"], 2)
        self.assertFalse(explanation["fallback_used"])
        self.assertIsNone(explanation["fallback_reason"])

    def test_explanation_records_fallback_reason(self):
        facts = RoutingFacts(user_request="design cache layer", diff_line_count=120)
        laya = _laya("GLM", 0.5)
        decision = select_route(
            facts,
            laya=laya,
            laya_fallback_reason="route confidence 0.50 below threshold 0.60",
        )
        context = derive_context_requirements(None, facts)
        explanation = build_explanation(
            facts=facts,
            decision=decision,
            context=context,
            fallback_reason=decision.fallback_reason,
            analysis_source="laya_rejected",
        )
        self.assertTrue(explanation["fallback_used"])
        self.assertIn("below threshold", explanation["fallback_reason"])
        self.assertEqual(explanation["selected_route"], "QWEN")

    def test_execution_block_required_fields(self):
        facts = RoutingFacts(user_request="fix typo")
        decision = select_route(facts)
        context = derive_context_requirements(None, facts)
        block = build_execution_block(decision=decision, context=context, facts=facts)
        for key in ("AGENT", "MODEL", "RISK", "REASON", "FALLBACK"):
            self.assertIn(key, block)
        self.assertEqual(block["AGENT"], "pi")
        self.assertEqual(block["MODEL"], "qwen3.8-27b")

    def test_execution_block_omits_empty_scope_verify(self):
        facts = RoutingFacts(user_request="fix typo")
        decision = select_route(facts)
        context = derive_context_requirements(None, facts)
        block = build_execution_block(decision=decision, context=context, facts=facts)
        self.assertNotIn("SCOPE", block)
        self.assertNotIn("VERIFY", block)

    def test_execution_block_includes_scope_and_verify(self):
        facts = RoutingFacts(
            user_request="fix billing bug",
            known_subsystem="billing",
            test_command="pytest tests/billing",
        )
        decision = select_route(facts)
        context = derive_context_requirements(None, facts)
        block = build_execution_block(decision=decision, context=context, facts=facts)
        self.assertIn("billing", block["SCOPE"])
        self.assertEqual(block["VERIFY"], ["pytest tests/billing"])


if __name__ == "__main__":
    unittest.main()
