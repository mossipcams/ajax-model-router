#!/usr/bin/env python3
"""Provider-owned model registry. Exact IDs only — no aliases in transport."""

from __future__ import annotations

# Callers may invoke Ajax without being a supported DELEGATE target.
CALLERS = ("cursor", "codex", "claude", "pi", "other")

# Only these have Ajax-owned transport adapters / model IDs.
TRANSPORTS = ("cursor", "codex", "pi")

TRANSPORT_MODELS = {
    "cursor": frozenset({"composer-2.5", "cursor-grok-4.6-high"}),
    "codex": frozenset({"gpt-5.6-sol"}),
    "pi": frozenset({"opencode-go/minimax-m3", "opencode-go/glm-5.2"}),
}

TRANSPORT_COMMANDS = {
    "cursor": "cursor-agent",
    "codex": "codex",
    "pi": "pi",
}

# Back-compat aliases used by older call sites / docs snippets.
HARNESSES = TRANSPORTS
HARNESS_MODELS = TRANSPORT_MODELS


def models_for(transport: str) -> frozenset[str]:
    return TRANSPORT_MODELS.get(transport, frozenset())


def model_belongs(transport: str, model: str) -> bool:
    return model in models_for(transport)


def transport_command(transport: str) -> str | None:
    return TRANSPORT_COMMANDS.get(transport)
