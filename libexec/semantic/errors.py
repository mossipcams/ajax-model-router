"""Typed errors for semantic analysis — sensor failures never block routing."""

from __future__ import annotations


class SemanticError(Exception):
    """Base semantic-layer error."""


class SemanticDisabledError(SemanticError):
    """Semantic analysis is disabled in configuration."""


class SemanticUnavailableError(SemanticError):
    """Sensor unavailable (missing venv, missing model, bridge failure)."""


class SemanticTimeoutError(SemanticError):
    """Sensor request timed out."""


class SemanticValidationError(SemanticError):
    """Sensor output failed schema validation."""


class SemanticLowConfidenceError(SemanticError):
    """Sensor confidence below configured threshold."""
