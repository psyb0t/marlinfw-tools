"""Typed errors exposed by the Marlin serial boundary."""


class MarlinToolError(Exception):
    """Base error for a rejected or failed Marlin tool operation."""


class ConfigurationError(MarlinToolError):
    """Raised when a local tool configuration value is invalid or unusable."""


class CommandValidationError(MarlinToolError):
    """Raised when a command is unsafe or malformed."""


class PrinterCommandError(MarlinToolError):
    """Raised when printer firmware rejects a command."""


class PrinterTimeoutError(MarlinToolError):
    """Raised when firmware does not acknowledge a command before timeout."""
