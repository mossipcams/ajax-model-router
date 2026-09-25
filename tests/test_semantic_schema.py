#!/usr/bin/env python3
"""RouteDecision / FailureFeatures schema validation."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.schema import (  # noqa: E402
    ContextBudget,
    ContextRequirements,
    RouteDecision,
    failure_features_json_schema,
    parse_failure_features_json,
    parse_route_decision_json,
    route_decision_json_schema,
)

ALLOWED = ("MINIMAX", "QWEN", "CURSOR", "GLM", "CODEX", "OPUS")

VALID_ROUTE = """{
  "route": "GLM",
  "probabilities": {"MINIMAX": 0.1, "CURSOR": 0.2, "GLM": 0.6, "CODEX": 0.1},
  "complexity": 3,
  "ambiguity": 4
}"""


class RouteDecisionSchemaTests(unittest.TestCase):
    def test_valid_route_decision_parses(self):
        decision = parse_route_decision_json(VALID_ROUTE, ALLOWED)
        self.assertEqual(decision.route, "GLM")
        self.assertEqual(decision.confidence, 0.6)
        self.assertEqual(decision.complexity, 3)
        self.assertEqual(decision.ambiguity, 4)
        self.assertEqual(decision.probabilities["CODEX"], 0.1)

    def test_confidence_matches_selected_probability(self):
        decision = parse_route_decision_json(VALID_ROUTE, ALLOWED)
        self.assertEqual(decision.confidence, decision.probabilities[decision.route])

    def test_explicit_confidence_must_match(self):
        text = VALID_ROUTE.replace(
            '"complexity": 3', '"confidence": 0.99, "complexity": 3'
        )
        with self.assertRaises(ValueError) as ctx:
            parse_route_decision_json(text, ALLOWED)
        self.assertIn("confidence", str(ctx.exception))

    def test_route_must_be_eligible(self):
        text = VALID_ROUTE.replace('"route": "GLM"', '"route": "NOT_A_ROUTE"')
        with self.assertRaises(ValueError) as ctx:
            parse_route_decision_json(text, ALLOWED)
        self.assertIn("route", str(ctx.exception))

    def test_route_must_appear_in_probabilities(self):
        text = VALID_ROUTE.replace('"GLM": 0.6, ', "")
        with self.assertRaises(ValueError) as ctx:
            parse_route_decision_json(text, ALLOWED)
        self.assertIn("probabilities", str(ctx.exception))

    def test_unknown_route_in_probabilities_rejected(self):
        text = VALID_ROUTE.replace(
            '{"MINIMAX": 0.1,', '{"MINIMAX": 0.1, "MYSTERY": 0.2,'
        )
        with self.assertRaises(ValueError) as ctx:
            parse_route_decision_json(text, ALLOWED)
        self.assertIn("MYSTERY", str(ctx.exception))

    def test_probability_out_of_range_rejected(self):
        text = VALID_ROUTE.replace('"GLM": 0.6', '"GLM": 1.5')
        with self.assertRaises(ValueError):
            parse_route_decision_json(text, ALLOWED)

    def test_complexity_out_of_range_rejected(self):
        text = VALID_ROUTE.replace('"complexity": 3', '"complexity": 9')
        with self.assertRaises(ValueError) as ctx:
            parse_route_decision_json(text, ALLOWED)
        self.assertIn("complexity", str(ctx.exception))

    def test_unexpected_field_rejected(self):
        text = VALID_ROUTE[: VALID_ROUTE.rfind("}")] + ', "chain_of_thought": "x"}'
        with self.assertRaises(ValueError) as ctx:
            parse_route_decision_json(text, ALLOWED)
        self.assertIn("unexpected fields", str(ctx.exception))

    def test_malformed_json_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            parse_route_decision_json("not json", ALLOWED)
        self.assertIn("malformed JSON", str(ctx.exception))

    def test_no_eligible_routes_rejected(self):
        with self.assertRaises(ValueError):
            parse_route_decision_json(VALID_ROUTE, ())

    def test_route_decision_json_schema_lists_eligible(self):
        schema = route_decision_json_schema(("GLM", "CODEX"))
        self.assertEqual(schema["allowed_routes"], ["GLM", "CODEX"])
        self.assertEqual(set(schema["probabilities"]), {"GLM", "CODEX"})


class FailureFeaturesSchemaTests(unittest.TestCase):
    def test_valid_failure_features_parse(self):
        text = json.dumps(
            {
                "failure_class": "test_regression",
                "domain": "testing",
                "component": "tests/test_auth.py",
                "likely_task_related": True,
                "retry_same_model": True,
                "confidence": 0.9,
            }
        )
        features = parse_failure_features_json(text)
        self.assertEqual(features.failure_class.value, "test_regression")
        self.assertEqual(features.domain.value, "testing")
        self.assertTrue(features.retry_same_model)

    def test_unexpected_field_rejected(self):
        text = json.dumps(
            {
                "failure_class": "timeout",
                "domain": "unknown",
                "component": "",
                "likely_task_related": False,
                "retry_same_model": False,
                "confidence": 0.5,
                "extra": 1,
            }
        )
        with self.assertRaises(ValueError) as ctx:
            parse_failure_features_json(text)
        self.assertIn("unexpected", str(ctx.exception))

    def test_missing_required_field_rejected(self):
        text = json.dumps(
            {
                "failure_class": "timeout",
                "domain": "unknown",
                "component": "",
                "likely_task_related": False,
                "confidence": 0.5,
            }
        )
        with self.assertRaises(ValueError) as ctx:
            parse_failure_features_json(text)
        self.assertIn("retry_same_model", str(ctx.exception))

    def test_unknown_failure_class_rejected(self):
        text = json.dumps(
            {
                "failure_class": "mystery",
                "domain": "unknown",
                "component": "",
                "likely_task_related": False,
                "retry_same_model": False,
                "confidence": 0.5,
            }
        )
        with self.assertRaises(ValueError):
            parse_failure_features_json(text)

    def test_schema_echo_domain_rejected(self):
        text = json.dumps(
            {
                "failure_class": "unknown",
                "domain": "|".join(
                    d
                    for d in (
                        "frontend",
                        "rust_backend",
                        "mobile_web",
                        "git",
                        "github",
                        "testing",
                        "ci",
                        "architecture",
                        "tooling",
                        "unknown",
                    )
                ),
                "component": "",
                "likely_task_related": False,
                "retry_same_model": False,
                "confidence": 0.5,
            }
        )
        with self.assertRaises(ValueError) as ctx:
            parse_failure_features_json(text)
        self.assertIn("schema echo", str(ctx.exception))

    def test_failure_features_json_schema_shape(self):
        schema = failure_features_json_schema()
        self.assertEqual(schema["additionalProperties"], False)
        self.assertIn("failure_class", schema["required"])
        self.assertEqual(
            schema["properties"]["failure_class"]["enum"][0], "test_regression"
        )


class ContextRequirementsTests(unittest.TestCase):
    def test_defaults_and_to_dict(self):
        context = ContextRequirements()
        self.assertEqual(context.context_budget, ContextBudget.UNKNOWN)
        data = context.to_dict()
        self.assertEqual(data["likely_subsystems"], [])
        self.assertEqual(data["context_budget"], "unknown")


if __name__ == "__main__":
    unittest.main()
