#!/usr/bin/env python3
"""Laya HTTP client — urllib mocked, no live endpoint."""

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.client import laya_request  # noqa: E402
from semantic.errors import (  # noqa: E402
    SemanticTimeoutError,
    SemanticUnavailableError,
)

ENDPOINT = "http://127.0.0.1:8000/v1/systemone"
PAYLOAD = {"kind": "route", "task": "fix login bug"}


def _fake_response(body: bytes, code: int = 200):
    response = mock.MagicMock()
    response.read.return_value = body
    response.status = code
    response.__enter__ = mock.Mock(return_value=response)
    response.__exit__ = mock.Mock(return_value=False)
    return response


class LayaClientTests(unittest.TestCase):
    def test_success_returns_json_object(self):
        body = json.dumps({"route": "GLM", "probabilities": {"GLM": 0.9}}).encode()
        with mock.patch(
            "urllib.request.urlopen", return_value=_fake_response(body)
        ) as urlopen:
            result = laya_request(ENDPOINT, PAYLOAD, 5000)
        self.assertEqual(result["route"], "GLM")
        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_full_url(), ENDPOINT)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            request.get_header("Content-type"), "application/json"
        )
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent, PAYLOAD)
        self.assertEqual(urlopen.call_args[1]["timeout"], 5.0)

    def test_connection_failure_raises_unavailable(self):
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaises(SemanticUnavailableError):
                laya_request(ENDPOINT, PAYLOAD, 5000)

    def test_http_error_raises_unavailable(self):
        http_error = urllib.error.HTTPError(
            ENDPOINT, 500, "internal", {}, io.BytesIO(b"boom")
        )
        with mock.patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(SemanticUnavailableError) as ctx:
                laya_request(ENDPOINT, PAYLOAD, 5000)
        self.assertIn("500", str(ctx.exception))

    def test_timeout_raises_timeout(self):
        with mock.patch(
            "urllib.request.urlopen", side_effect=TimeoutError("timed out")
        ):
            with self.assertRaises(SemanticTimeoutError):
                laya_request(ENDPOINT, PAYLOAD, 5000)

    def test_non_json_response_raises_unavailable(self):
        with mock.patch(
            "urllib.request.urlopen",
            return_value=_fake_response(b"not json"),
        ):
            with self.assertRaises(SemanticUnavailableError):
                laya_request(ENDPOINT, PAYLOAD, 5000)

    def test_json_array_response_raises_unavailable(self):
        with mock.patch(
            "urllib.request.urlopen",
            return_value=_fake_response(b"[1, 2]"),
        ):
            with self.assertRaises(SemanticUnavailableError):
                laya_request(ENDPOINT, PAYLOAD, 5000)


if __name__ == "__main__":
    unittest.main()
