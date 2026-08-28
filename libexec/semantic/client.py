"""OpenAI-compatible local SLM HTTP client — stdlib urllib only."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from semantic.errors import SemanticTimeoutError, SemanticUnavailableError


def chat_completion(
    *,
    endpoint: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    timeout_ms: int,
    keep_alive: str = "30m",
    response_format: dict[str, Any] | None = None,
) -> str:
    """POST /v1/chat/completions and return assistant message content."""
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
        # Disable Qwen 3.5 thinking / agentic loop on Ollama OpenAI-compatible API.
        "reasoning_effort": "none",
        "think": False,
        "keep_alive": keep_alive,
    }
    if response_format is not None:
        body["response_format"] = response_format
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout_sec = max(timeout_ms / 1000.0, 0.001)
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8")
    except TimeoutError as error:
        raise SemanticTimeoutError(str(error)) from error
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise SemanticUnavailableError(f"HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise SemanticUnavailableError(str(error.reason)) from error

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SemanticUnavailableError(f"invalid response JSON: {error}") from error

    return _extract_content(data)


def _extract_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SemanticUnavailableError("missing choices in SLM response")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise SemanticUnavailableError("missing message in SLM response")
    content = message.get("content", "")
    if not isinstance(content, str):
        raise SemanticUnavailableError("message content must be a string")
    return content.strip()
