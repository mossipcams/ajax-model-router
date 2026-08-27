"""Load semantic analysis and model capability TOML configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEMANTIC_CONFIG = ROOT / "config" / "semantic_analysis.toml"
DEFAULT_CAPABILITIES_CONFIG = ROOT / "config" / "model_capabilities.toml"


@dataclass(frozen=True)
class SlmConfig:
    enabled: bool
    endpoint: str
    model: str
    timeout_ms: int
    max_retries: int
    confidence_threshold: float
    task_system: str
    failure_system: str
    max_tokens: int


@dataclass(frozen=True)
class ModelCapability:
    key: str
    cost_tier: int
    architecture_strength: int
    localized_implementation_strength: int
    frontend_strength: int
    rust_strength: int
    debugging_strength: int
    test_writing_strength: int
    large_context_strength: int
    review_strength: int


def load_slm_config(path: Path | None = None) -> SlmConfig:
    config_path = path or DEFAULT_SEMANTIC_CONFIG
    data = tomllib.loads(config_path.read_text())
    slm = data.get("slm") or {}
    prompts = data.get("prompts") or {}
    return SlmConfig(
        enabled=bool(slm.get("enabled", False)),
        endpoint=str(slm.get("endpoint", "http://127.0.0.1:11434/v1/chat/completions")),
        model=str(slm.get("model", "local-model")),
        timeout_ms=int(slm.get("timeout_ms", 5000)),
        max_retries=int(slm.get("max_retries", 1)),
        confidence_threshold=float(slm.get("confidence_threshold", 0.6)),
        task_system=str(
            prompts.get(
                "task_system",
                "You classify coding tasks. Reply with JSON only. No explanation.",
            )
        ),
        failure_system=str(
            prompts.get(
                "failure_system",
                "You classify execution failures. Reply with JSON only. No explanation.",
            )
        ),
        max_tokens=int(prompts.get("max_tokens", 256)),
    )


def load_capabilities(path: Path | None = None) -> dict[str, ModelCapability]:
    config_path = path or DEFAULT_CAPABILITIES_CONFIG
    data = tomllib.loads(config_path.read_text())
    result: dict[str, ModelCapability] = {}
    for key, values in data.items():
        if not isinstance(values, dict):
            continue
        result[key] = ModelCapability(
            key=key,
            cost_tier=int(values.get("cost_tier", 0)),
            architecture_strength=int(values.get("architecture_strength", 0)),
            localized_implementation_strength=int(
                values.get("localized_implementation_strength", 0)
            ),
            frontend_strength=int(values.get("frontend_strength", 0)),
            rust_strength=int(values.get("rust_strength", 0)),
            debugging_strength=int(values.get("debugging_strength", 0)),
            test_writing_strength=int(values.get("test_writing_strength", 0)),
            large_context_strength=int(values.get("large_context_strength", 0)),
            review_strength=int(values.get("review_strength", 0)),
        )
    return result
