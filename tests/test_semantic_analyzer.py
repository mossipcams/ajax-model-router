#!/usr/bin/env python3
"""Semantic analyzer behavior — sensor with typed failures, never blocks routing."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.analyzer import (  # noqa: E402
    DisabledSemanticAnalyzer,
    GlinerAnalyzer,
    TaskAnalysisInput,
    analyze_with_fallback,
    create_analyzer,
)
from semantic.config import SemanticConfig  # noqa: E402
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

CFG = SemanticConfig(
    enabled=True,
    model="fastino/GLiNER2.5-Decide",
    python=".venv/bin/python",
    timeout_ms=5000,
    confidence_threshold=0.60,
)
CFG_GLINER = SemanticConfig(
    enabled=True,
    model="fastino/GLiNER2.5-Decide",
    python=".venv/bin/python",
    timeout_ms=20000,
    confidence_threshold=0.45,
)
ELIGIBLE = ("MINIMAX", "QWEN", "CURSOR", "GLM", "CODEX", "OPUS")


def _task_input(**overrides) -> TaskAnalysisInput:
    base = dict(
        user_request="fix login bug",
        facts=RoutingFacts(user_request="fix login bug"),
        eligible_routes=ELIGIBLE,
    )
    base.update(overrides)
    return TaskAnalysisInput(**base)


class AnalyzerTests(unittest.TestCase):
    def test_create_analyzer_disabled(self):
        analyzer = create_analyzer(SemanticConfig(
            enabled=False, model="m", python="p",
            timeout_ms=100, confidence_threshold=0.6,
        ))
        self.assertIsInstance(analyzer, DisabledSemanticAnalyzer)

    def test_create_analyzer_gliner(self):
        analyzer = create_analyzer(CFG_GLINER)
        self.assertIsInstance(analyzer, GlinerAnalyzer)

    def test_create_analyzer_defaults_to_gliner(self):
        analyzer = create_analyzer()
        self.assertIsInstance(analyzer, GlinerAnalyzer)

    def test_disabled_analyzer_raises(self):
        with self.assertRaises(SemanticDisabledError):
            DisabledSemanticAnalyzer().analyze_task(_task_input())


class GlinerAnalyzerTests(unittest.TestCase):
    def test_missing_venv_raises_unavailable(self):
        cfg = SemanticConfig(
            enabled=True, model="m",
            python="/does/not/exist/python",
            timeout_ms=1000, confidence_threshold=0.45,
        )
        with self.assertRaises(SemanticUnavailableError):
            GlinerAnalyzer(cfg).analyze_task(_task_input())

    def test_no_eligible_routes_raises(self):
        with self.assertRaises(SemanticValidationError):
            GlinerAnalyzer(CFG_GLINER).analyze_task(
                _task_input(eligible_routes=())
            )

    def test_bridge_low_confidence_raises(self):
        cfg = SemanticConfig(
            enabled=True, model="m",
            python=str(ROOT / ".venv" / "bin" / "python"),
            timeout_ms=1000, confidence_threshold=0.99,
        )
        proc = mock.Mock()
        proc.returncode = 0
        proc.stdout = json.dumps({
            "route": "GLM",
            "probabilities": {"GLM": 0.5, "CURSOR": 0.5},
            "complexity": 3,
            "ambiguity": 2,
        })
        proc.stderr = ""
        with mock.patch("semantic.gliner.subprocess.run", return_value=proc):
            with self.assertRaises(SemanticLowConfidenceError):
                GlinerAnalyzer(cfg).analyze_task(_task_input())

    def test_bridge_success_returns_decision(self):
        proc = mock.Mock()
        proc.returncode = 0
        proc.stdout = json.dumps({
            "route": "GLM",
            "probabilities": {"GLM": 0.85, "CURSOR": 0.15},
            "complexity": 3,
            "ambiguity": 2,
        })
        proc.stderr = ""
        with mock.patch("semantic.gliner.subprocess.run", return_value=proc):
            decision = GlinerAnalyzer(CFG_GLINER).analyze_task(_task_input())
        self.assertEqual(decision.route, "GLM")
        self.assertEqual(decision.confidence, 0.85)

    def test_bridge_failure_raises_unavailable(self):
        proc = mock.Mock()
        proc.returncode = 3
        proc.stdout = ""
        proc.stderr = "bridge: model not in local cache — run scripts/setup-gliner"
        with mock.patch("semantic.gliner.subprocess.run", return_value=proc):
            with self.assertRaises(SemanticUnavailableError):
                GlinerAnalyzer(CFG_GLINER).analyze_task(_task_input())

    def test_analyze_failure_unavailable(self):
        with self.assertRaises(SemanticUnavailableError):
            GlinerAnalyzer(CFG_GLINER).analyze_failure(
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
        self.assertEqual(source, "sensor")

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
        self.assertEqual(source, "sensor_rejected")
        self.assertEqual(reason, "low")

    def test_unavailable_returns_failed(self):
        analyzer = mock.MagicMock()
        analyzer.analyze_task.side_effect = SemanticUnavailableError("no endpoint")
        decision, reason, source = analyze_with_fallback(analyzer, _task_input())
        self.assertIsNone(decision)
        self.assertEqual(source, "sensor_failed")
        self.assertEqual(reason, "no endpoint")

    def test_never_raises(self):
        analyzer = mock.MagicMock()
        analyzer.analyze_task.side_effect = SemanticTimeoutError("timed out")
        decision, reason, source = analyze_with_fallback(analyzer, _task_input())
        self.assertIsNone(decision)
        self.assertEqual(source, "sensor_failed")


if __name__ == "__main__":
    unittest.main()
