#!/usr/bin/env python3
"""Local SLM HTTP client — urllib mocked, no live endpoint."""

import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.client import chat_completion  # noqa: E402
from semantic.errors import SemanticTimeoutError, SemanticUnavailableError  # noqa: E402


class LocalSlmClientTests(unittest.TestCase):
    def test_chat_completion_extracts_content(self):
        body = {
            "choices": [{"message": {"content": '{"task_type":"unknown"}'}}]
        }
        response = BytesIO(json.dumps(body).encode())

        def fake_urlopen(request, timeout=0):
            return mock.Mock(read=lambda: response.read(), __enter__=lambda s: s, __exit__=lambda *a: None)

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            content = chat_completion(
                endpoint="http://example/v1/chat/completions",
                model="m",
                system="sys",
                user="task",
                max_tokens=32,
                timeout_ms=1000,
            )
        self.assertIn("task_type", content)

    def test_missing_choices_raises_unavailable(self):
        response = BytesIO(b"{}")

        def fake_urlopen(request, timeout=0):
            return mock.Mock(read=lambda: response.read(), __enter__=lambda s: s, __exit__=lambda *a: None)

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(SemanticUnavailableError):
                chat_completion(
                    endpoint="http://example/v1/chat/completions",
                    model="m",
                    system="sys",
                    user="task",
                    max_tokens=32,
                    timeout_ms=1000,
                )

    def test_timeout_raises(self):
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ):
            with self.assertRaises(SemanticTimeoutError):
                chat_completion(
                    endpoint="http://example/v1/chat/completions",
                    model="m",
                    system="sys",
                    user="task",
                    max_tokens=32,
                    timeout_ms=100,
                )


if __name__ == "__main__":
    unittest.main()
