"""Laya HTTP client — local System-1 routing sensor, stdlib urllib only.

Laya runs as a persistent local service exposing a Jev-compatible
`/v1/systemone` endpoint. The client sends one compact decision payload and
expects one JSON decision back. Transport failures raise typed semantic
errors so the analyzer can degrade gracefully; Laya never blocks routing.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from semantic.errors import SemanticTimeoutError, SemanticUnavailableError


def laya_request(
    endpoint: str,
    payload: dict[str, object],
    timeout_ms: int,
) -> dict[str, object]:
    """POST the decision payload to Laya and return the parsed JSON body.

    Raises:
        SemanticUnavailableError: connection failure, HTTP error, or a
            response body that is not a JSON object.
        SemanticTimeoutError: the request exceeded `timeout_ms`.
    """
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_ms / 1000) as response:
            body = response.read().decode("utf-8", errors="replace")
    except TimeoutError as error:
        raise SemanticTimeoutError(str(error)) from error
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise SemanticUnavailableError(
            f"laya http {error.code}: {detail}"
        ) from error
    except (urllib.error.URLError, OSError) as error:
        raise SemanticUnavailableError(str(error)) from error

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise SemanticUnavailableError(
            f"laya response is not valid json: {body[:200]!r}"
        ) from error
    if not isinstance(parsed, dict):
        raise SemanticUnavailableError(
            f"laya response must be a JSON object, got {type(parsed).__name__}"
        )
    return parsed
