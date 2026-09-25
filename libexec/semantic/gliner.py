"""GlinerAnalyzer — local GLiNER2.5-Decide routing sensor via a venv subprocess.

Design: subprocess bridge. The main router process stays stdlib-only; the
gliner2 dependency lives in the repo venv (``.venv``). ``analyze_task`` runs
``gliner_bridge.py`` under the venv's python, passing the payload via stdin
and receiving a RouteDecision JSON object on stdout.

Degradation: missing venv / missing model / import failure / timeout /
invalid output all raise typed SemanticError subclasses, so the caller
degrades to deterministic routing (the sensor never blocks the pipeline).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from semantic.config import ROOT, SemanticConfig, load_semantic_config
from semantic.errors import (
    SemanticDisabledError,
    SemanticLowConfidenceError,
    SemanticTimeoutError,
    SemanticUnavailableError,
    SemanticValidationError,
)
from semantic.schema import RouteDecision, parse_route_decision_json

BRIDGE = ROOT / "libexec" / "semantic" / "gliner_bridge.py"


def _resolve_python(config: SemanticConfig) -> Path:
    """Resolve the venv interpreter path (absolute or relative to the repo)."""
    candidate = Path(config.python)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate


class GlinerAnalyzer:
    """Local GLiNER2.5-Decide sensor.

    Runs the bridge under the repo venv's python. Never retries, never owns
    policy: any failure raises a typed SemanticError so the caller degrades
    to deterministic routing.
    """

    def __init__(self, config: SemanticConfig | None = None):
        self.config = config or load_semantic_config()

    def analyze_task(self, input_data) -> RouteDecision:
        if not self.config.enabled:
            raise SemanticDisabledError("semantic analysis disabled")
        if not input_data.eligible_routes:
            raise SemanticValidationError("no eligible routes for semantic analysis")

        python = _resolve_python(self.config)
        if not BRIDGE.is_file():
            raise SemanticUnavailableError(f"bridge script missing: {BRIDGE}")

        payload = {
            "task": input_data.user_request[:1000],
            "eligible_routes": list(input_data.eligible_routes),
            "model": self.config.model,
        }
        try:
            proc = subprocess.run(
                [str(python), str(BRIDGE)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=self.config.timeout_ms / 1000.0,
                cwd=str(ROOT),
            )
        except subprocess.TimeoutExpired as error:
            raise SemanticTimeoutError(
                f"gliner bridge timed out after {self.config.timeout_ms}ms"
            ) from error
        except FileNotFoundError as error:
            raise SemanticUnavailableError(
                f"gliner venv python not found at {python} — run scripts/setup-gliner"
            ) from error
        except (OSError, subprocess.SubprocessError) as error:
            raise SemanticUnavailableError(
                f"gliner bridge failed to run: {error}"
            ) from error

        if proc.returncode != 0:
            detail = (proc.stderr or "").strip().splitlines()
            message = detail[-1] if detail else f"bridge exit {proc.returncode}"
            raise SemanticUnavailableError(f"gliner bridge: {message}")

        try:
            decision = parse_route_decision_json(
                proc.stdout, input_data.eligible_routes
            )
        except ValueError as error:
            raise SemanticValidationError(str(error)) from error

        if decision.confidence < self.config.confidence_threshold:
            raise SemanticLowConfidenceError(
                f"route confidence {decision.confidence:.2f} below threshold "
                f"{self.config.confidence_threshold:.2f}"
            )
        return decision
