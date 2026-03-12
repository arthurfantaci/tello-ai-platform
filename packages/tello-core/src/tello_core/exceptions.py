"""Base exception hierarchy for the tello-ai-platform.

All platform exceptions inherit from TelloError.
Services extend these with domain-specific subclasses.
"""


class TelloError(Exception):
    """Root exception for all tello-ai-platform errors."""


class ConfigurationError(TelloError):
    """Invalid configuration or missing environment variables.

    Raised at startup (fail-fast). Should never be caught in normal flow.
    """


class ConnectionError(TelloError):
    """Neo4j, Redis, or drone connection failure."""


class CommandError(TelloError):
    """Failed to execute a drone command or tool call."""


class ValidationError(TelloError):
    """Invalid input data (distinct from Pydantic's ValidationError)."""
