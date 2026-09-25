"""Load the semantic analysis TOML configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEMANTIC_CONFIG = ROOT / "config" / "semantic_analysis.toml"
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
