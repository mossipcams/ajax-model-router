#!/usr/bin/env python3
"""Laya analyzer behavior — sensor with typed failures, never blocks routing."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.analyzer import (  # noqa: E402
    DisabledSemanticAnalyzer,
    LayaAnalyzer,
    TaskAnalysisInput,
    analyze_with_fallback,
    create_analyzer,
)
from semantic.config import LayaConfig  # noqa: E402
from semantic.errors import (  # noqa: E402
    SemanticDisabledError,
    SemanticLowConfidenceError,
    SemanticTimeoutError,
    SemanticUnavailableError,
    SemanticValidationError,
)
from semantic.facts import RoutingFacts  # noqa: E402
from semantic.failure import FailureAnalysisInput  # noqa: E402
from semantic.schema import RouteDecision  # noqa: E402

CFG = LayaConfig(
    enabled=True,
    endpoint="http://127.0.0.1:8000/v1/systemone",
    timeout_ms=5000,
    confidence_threshold=0.60,
)
ELIGIBLE = ("MINIMAX", "CURSOR", "GLM", "CODEX")


def _task_input(**overrides) -> TaskAnalysisInput:
    base = dict(
        user_request="fix login bug",
        facts=RoutingFacts(user_request="fix login bug"),
        eligible_routes=ELIGIBLE,
    )
    base.update(overrides)
    return TaskAnalysisInput(**base)


def _decision_body(route: str, confidence: float) -> dict:
    return {
        "route": route,
        "probabilities": {route: confidence, "CURSOR": max(0.0, 1 - confidence)},
        "complexity": 3,
        "ambiguity": 2,
    }


class AnalyzerTests(unittest.TestCase):
    def test_create_analyzer_disabled(self):
        analyzer = create_analyzer(LayaConfig(
            enabled=False, endpoint="http://x", timeout_ms=100,
            confidence_threshold=0.6,
        ))
        self.assertIsInstance(analyzer, DisabledSemanticAnalyzer)

    def test_create_analyzer_enabled(self):
        analyzer = create_analyzer(CFG)
        self.assertIsInstance(analyzer, LayaAnalyzer)

    def test_disabled_analyzer_raises(self):
        with self.assertRaises(SemanticDisabledError):
            DisabledSemanticAnalyzer().analyze_task(_task_input())

    def test_analyze_task_returns_route_decision(self):
        with mock.patch(
            "semantic.analyzer.laya_request",
            return_value=_decision_body("GLM", 0.85),
        ) as request:
            decision = LayaAnalyzer(CFG).analyze_task(_task_input())
        self.assertEqual(decision.route, "GLM")
        self.assertIsInstance(decision, RouteDecision)
        self.assertEqual(decision.confidence, 0.85)
        body = request.call_args[0][1]
        self.assertEqual(body["kind"], "route")
        self.assertEqual(body["eligible_routes"], list(ELIGIBLE))
        self.assertIn("response_schema", body)
        self.assertIn("GLM", body["route_definitions"])

    def test_analyze_task_low_confidence_raises(self):
        with mock.patch(
            "semantic.analyzer.laya_request",
            return_value=_decision_body("GLM", 0.4),
        ):
            with self.assertRaises(SemanticLowConfidenceError):
                LayaAnalyzer(CFG).analyze_task(_task_input())

    def test_analyze_task_no_eligible_routes_raises(self):
        with self.assertRaises(SemanticValidationError):
            LayaAnalyzer(CFG).analyze_task(_task_input(eligible_routes=()))

    def test_analyze_task_invalid_route_rejected(self):
        with mock.patch(
            "semantic.analyzer.laya_request",
            return_value=_decision_body("NOT_A_ROUTE", 0.9),
        ):
            with self.assertRaises(SemanticValidationError):
                LayaAnalyzer(CFG).analyze_task(_task_input())

    def test_analyze_failure_parses_features(self):
        body = {
            "failure_class": "test_regression",
            "domain": "testing",
            "component": "tests/test_auth.py",
            "likely_task_related": True,
            "retry_same_model": True,
            "confidence": 0.9,
        }
        with mock.patch("semantic.analyzer.laya_request", return_value=body):
            features = LayaAnalyzer(CFG).analyze_failure(
                FailureAnalysisInput(log_excerpt="3 tests failed")
            )
        self.assertEqual(features.failure_class.value, "test_regression")
        self.assertTrue(features.retry_same_model)

    def test_analyze_failure_low_confidence_raises(self):
        body = {
            "failure_class": "unknown",
            "domain": "unknown",
            "component": "",
            "likely_task_related": False,
            "retry_same_model": False,
            "confidence": 0.2,
        }
        with mock.patch("semantic.analyzer.laya_request", return_value=body):
            with self.assertRaises(SemanticLowConfidenceError):
                LayaAnalyzer(CFG).analyze_failure(
                    FailureAnalysisInput(log_excerpt="???")
                )

    def test_analyze_failure_invalid_schema_rejected(self):
        with mock.patch(
            "semantic.analyzer.laya_request",
            return_value={"failure_class": "mystery", "domain": "unknown"},
        ):
            with self.assertRaises(SemanticValidationError):
                LayaAnalyzer(CFG).analyze_failure(
                    FailureAnalysisInput(log_excerpt="???")
                )


class AnalyzeWithFallbackTests(unittest.TestCase):
    def test_success_returns_decision(self):
        analyzer = mock.MagicMock()
        analyzer.analyze_task.return_value = RouteDecision(
            route="GLM",
            probabilities={"GLM": 0.85, "CURSOR": 0.15},
            complexity=3,
            ambiguity=2,
            confidence=0.85,
        )
        decision, reason, source = analyze_with_fallback(analyzer, _task_input())
        self.assertEqual(decision.route, "GLM")
        self.assertIsNone(reason)
        self.assertEqual(source, "laya")

    def test_disabled_returns_reason(self):
        decision, reason, source = analyze_with_fallback(
            DisabledSemanticAnalyzer(), _task_input()
        )
        self.assertIsNone(decision)
        self.assertEqual(source, "disabled")
        self.assertIn("disabled", reason)

    def test_low_confidence_returns_rejected(self):
        analyzer = mock.MagicMock()
        analyzer.analyze_task.side_effect = SemanticLowConfidenceError("low")
        decision, reason, source = analyze_with_fallback(analyzer, _task_input())
        self.assertIsNone(decision)
        self.assertEqual(source, "laya_rejected")
        self.assertEqual(reason, "low")

    def test_unavailable_returns_failed(self):
        analyzer = mock.MagicMock()
        analyzer.analyze_task.side_effect = SemanticUnavailableError("no endpoint")
        decision, reason, source = analyze_with_fallback(analyzer, _task_input())
        self.assertIsNone(decision)
        self.assertEqual(source, "laya_failed")
        self.assertEqual(reason, "no endpoint")

    def test_never_raises(self):
        analyzer = mock.MagicMock()
        analyzer.analyze_task.side_effect = SemanticTimeoutError("timed out")
        decision, reason, source = analyze_with_fallback(analyzer, _task_input())
        self.assertIsNone(decision)
        self.assertEqual(source, "laya_failed")


if __name__ == "__main__":
    unittest.main()
