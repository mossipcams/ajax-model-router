#!/usr/bin/env python3
"""Semantic analysis TOML configuration."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.config import load_laya_config  # noqa: E402


class LayaConfigTests(unittest.TestCase):
    def test_default_config_values(self):
        cfg = load_laya_config()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:8000/v1/systemone")
        self.assertEqual(cfg.timeout_ms, 5000)
        self.assertAlmostEqual(cfg.confidence_threshold, 0.60)
        self.assertNotIn("qwen", cfg.endpoint)

    def test_disabled_override(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as tmp:
            tmp.write("[semantic]\nenabled = false\n")
            path = Path(tmp.name)
        try:
            cfg = load_laya_config(path)
            self.assertFalse(cfg.enabled)
            # Other fields keep defaults.
            self.assertEqual(cfg.endpoint, "http://127.0.0.1:8000/v1/systemone")
        finally:
            path.unlink()

    def test_missing_file_uses_defaults(self):
        cfg = load_laya_config(ROOT / "does-not-exist.toml")
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.timeout_ms, 5000)

    def test_custom_endpoint_and_threshold(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as tmp:
            tmp.write(
                "[semantic]\n"
                "enabled = true\n"
                "endpoint = \"http://laya.internal:9000/v1/systemone\"\n"
                "timeout_ms = 1200\n"
                "confidence_threshold = 0.75\n"
            )
            path = Path(tmp.name)
        try:
            cfg = load_laya_config(path)
            self.assertEqual(cfg.endpoint, "http://laya.internal:9000/v1/systemone")
            self.assertEqual(cfg.timeout_ms, 1200)
            self.assertAlmostEqual(cfg.confidence_threshold, 0.75)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
