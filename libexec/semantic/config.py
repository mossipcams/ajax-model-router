"""Load semantic analysis and model capability TOML configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEMANTIC_CONFIG = ROOT / "config" / "semantic_analysis.toml"
DEFAULT_CAPABILITIES_CONFIG = ROOT / "config" / "model_capabilities.toml"


DEFAULT_MODEL = "fastino/GLiNER2.5-Decide"
DEFAULT_PYTHON = ".venv/bin/python"


@dataclass(frozen=True)
class SemanticConfig:
    """Semantic routing sensor settings.

    The sensor is a local GLiNER classifier (GLiNER2.5-Decide by default).
    It is a sensor only: Ajax deterministic policy retains final authority
    over routing.
    """

    enabled: bool
    model: str  # GLiNER model id (HF repo or local path)
    python: str  # venv interpreter that has gliner2 installed
    timeout_ms: int
    confidence_threshold: float


def load_semantic_config(path: str | Path | None = None) -> SemanticConfig:
    """Load semantic sensor settings from TOML; defaults keep analysis enabled."""
    toml_path = Path(path) if path is not None else DEFAULT_SEMANTIC_CONFIG
    if toml_path.is_file():
        raw = tomllib.loads(toml_path.read_text())
    else:
        raw = {}
    section = raw.get("semantic", {})
    return SemanticConfig(
        enabled=bool(section.get("enabled", True)),
        model=str(section.get("model", DEFAULT_MODEL)),
        python=str(section.get("python", DEFAULT_PYTHON)),
        timeout_ms=int(section.get("timeout_ms", 20000)),
        confidence_threshold=float(section.get("confidence_threshold", 0.45)),
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
