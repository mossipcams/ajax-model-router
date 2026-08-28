#!/usr/bin/env python3
"""Semantic analysis TOML configuration."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.config import load_slm_config  # noqa: E402


class SemanticConfigTests(unittest.TestCase):
    def test_default_enabled(self):
        cfg = load_slm_config()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.timeout_ms, 60000)
        self.assertEqual(cfg.max_tokens, 2048)
        self.assertGreaterEqual(cfg.confidence_threshold, 0.0)

    def test_endpoint_and_model_present(self):
        cfg = load_slm_config()
        self.assertIn("chat/completions", cfg.endpoint)
        self.assertEqual(cfg.model, "qwen3:4b-instruct")
        self.assertNotEqual(cfg.model, "local-model")
        self.assertNotEqual(cfg.model, "qwen3:4b")
        self.assertNotEqual(cfg.model, "qwen2.5:3b")


if __name__ == "__main__":
    unittest.main()
