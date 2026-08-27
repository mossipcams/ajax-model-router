#!/usr/bin/env python3
"""Failure log normalization."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.failure import FailureAnalysisInput, normalize_failure  # noqa: E402
from semantic.schema import FailureClass  # noqa: E402


class FailureNormalizationTests(unittest.TestCase):
    def test_git_conflict(self):
        features = normalize_failure(
            FailureAnalysisInput(log_excerpt="merge conflict in file.rs", git_conflict=True)
        )
        self.assertEqual(features.failure_class, FailureClass.GIT_CONFLICT)

    def test_test_regression(self):
        features = normalize_failure(
            FailureAnalysisInput(test_summary="3 tests failed in test_foo")
        )
        self.assertEqual(features.failure_class, FailureClass.TEST_REGRESSION)

    def test_acp_error(self):
        features = normalize_failure(
            FailureAnalysisInput(acp_error="RetriableError: ACP failed")
        )
        self.assertEqual(features.failure_class, FailureClass.ACP_ERROR)
        self.assertTrue(features.retry_same_model)

    def test_timeout(self):
        features = normalize_failure(FailureAnalysisInput(exit_code=124))
        self.assertEqual(features.failure_class, FailureClass.TIMEOUT)


if __name__ == "__main__":
    unittest.main()
