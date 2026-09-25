#!/usr/bin/env python3
"""Model capability registry."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.capabilities import CapabilityRegistry  # noqa: E402
from semantic.config import load_capabilities  # noqa: E402


class ModelCapabilitiesTests(unittest.TestCase):
    def test_registry_loads_all_keys(self):
        caps = load_capabilities()
        for key in ("CODEX", "CURSOR", "MINIMAX", "QWEN", "GLM", "OPUS"):
            self.assertIn(key, caps)
        self.assertEqual(caps["QWEN"].context_window, 65536)
        self.assertEqual(caps["QWEN"].max_output_tokens, 4096)

    def test_cheapest_eligible_static_strength(self):
        registry = CapabilityRegistry()
        result = registry.cheapest_eligible(
            min_strength_field="localized_implementation_strength",
            min_strength=4,
        )
        self.assertTrue(result.data_sufficient)
        self.assertIn("CURSOR", result.models)
        self.assertLess(
            registry.get("MINIMAX").cost_tier,
            registry.get("CURSOR").cost_tier,
        )

    def test_threshold_query_insufficient_data(self):
        registry = CapabilityRegistry()
        result = registry.cheapest_eligible(
            min_strength_field="architecture_strength",
            min_strength=3,
            expected_success_threshold=0.9,
        )
        self.assertFalse(result.data_sufficient)
        self.assertIn("unavailable", result.note)


if __name__ == "__main__":
    unittest.main()
