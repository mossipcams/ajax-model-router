#!/usr/bin/env python3
"""RouteDecision schema validation."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.schema import (  # noqa: E402
    ContextBudget,
    ContextRequirements,
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


class ContextRequirementsTests(unittest.TestCase):
    def test_defaults_and_to_dict(self):
        context = ContextRequirements()
        self.assertEqual(context.context_budget, ContextBudget.UNKNOWN)
        data = context.to_dict()
        self.assertEqual(data["likely_subsystems"], [])
        self.assertEqual(data["context_budget"], "unknown")


if __name__ == "__main__":
    unittest.main()
