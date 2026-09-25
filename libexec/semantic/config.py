"""Load semantic analysis and model capability TOML configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEMANTIC_CONFIG = ROOT / "config" / "semantic_analysis.toml"
DEFAULT_CAPABILITIES_CONFIG = ROOT / "config" / "model_capabilities.toml"


@dataclass(frozen=True)
class LayaConfig:
    """Laya semantic routing settings.

    Laya is a local, persistent System-1 routing sensor. It is a sensor only:
    Ajax deterministic policy retains final authority over routing.
    """

    enabled: bool
    endpoint: str
    timeout_ms: int
    confidence_threshold: float


def load_laya_config(path: str | Path | None = None) -> LayaConfig:
    """Load Laya settings from TOML; defaults keep analysis enabled."""
    toml_path = Path(path) if path is not None else DEFAULT_SEMANTIC_CONFIG
    if toml_path.is_file():
        raw = tomllib.loads(toml_path.read_text())
    else:
        raw = {}
    section = raw.get("semantic", {})
    return LayaConfig(
        enabled=bool(section.get("enabled", True)),
        endpoint=str(
            section.get("endpoint", "http://127.0.0.1:8000/v1/systemone")
        ),
        timeout_ms=int(section.get("timeout_ms", 5000)),
        confidence_threshold=float(section.get("confidence_threshold", 0.60)),
    )


@dataclass(frozen=True)
class ModelCapability:
    key: str
    context_window: int
    max_output_tokens: int
    cost_tier: int
    architecture_strength: int
    localized_implementation_strength: int
    frontend_strength: int
    rust_strength: int
    debugging_strength: int
    test_writing_strength: int
    large_context_strength: int
    review_strength: int


def load_capabilities(path: Path | None = None) -> dict[str, ModelCapability]:
    config_path = path or DEFAULT_CAPABILITIES_CONFIG
    data = tomllib.loads(config_path.read_text())
    result: dict[str, ModelCapability] = {}
    for key, values in data.items():
        if not isinstance(values, dict):
            continue
        result[key] = ModelCapability(
            key=key,
            context_window=int(values.get("context_window", 0)),
            max_output_tokens=int(values.get("max_output_tokens", 0)),
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
