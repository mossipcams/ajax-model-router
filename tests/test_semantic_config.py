#!/usr/bin/env python3
"""Semantic analysis TOML configuration."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.config import load_semantic_config  # noqa: E402


class SemanticConfigTests(unittest.TestCase):
    def test_default_config_values(self):
        cfg = load_semantic_config()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.model, "fastino/GLiNER2.5-Decide")
        self.assertEqual(cfg.python, ".venv/bin/python")
        self.assertEqual(cfg.timeout_ms, 20000)
        self.assertAlmostEqual(cfg.confidence_threshold, 0.45)

    def test_disabled_override(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as tmp:
            tmp.write("[semantic]\nenabled = false\n")
            path = Path(tmp.name)
        try:
            cfg = load_semantic_config(path)
            self.assertFalse(cfg.enabled)
            # Other fields keep defaults.
            self.assertEqual(cfg.model, "fastino/GLiNER2.5-Decide")
        finally:
            path.unlink()

    def test_missing_file_uses_defaults(self):
        cfg = load_semantic_config(ROOT / "does-not-exist.toml")
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.timeout_ms, 20000)

    def test_custom_timeout_and_threshold(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as tmp:
            tmp.write(
                "[semantic]\n"
                "enabled = true\n"
                "timeout_ms = 1200\n"
                "confidence_threshold = 0.75\n"
            )
            path = Path(tmp.name)
        try:
            cfg = load_semantic_config(path)
            self.assertEqual(cfg.timeout_ms, 1200)
            self.assertAlmostEqual(cfg.confidence_threshold, 0.75)
        finally:
            path.unlink()

    def test_custom_gliner_model(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as tmp:
            tmp.write(
                "[semantic]\n"
                "model = \"fastino/GLiNER2.5-Large\"\n"
                "python = \".venv/bin/python3.13\"\n"
            )
            path = Path(tmp.name)
        try:
            cfg = load_semantic_config(path)
            self.assertEqual(cfg.model, "fastino/GLiNER2.5-Large")
            self.assertEqual(cfg.python, ".venv/bin/python3.13")
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
