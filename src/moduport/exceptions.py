"""Public exceptions raised before entering the frozen numerical core."""


class ModuPortError(Exception):
    """Base exception for the public wrapper."""


class ConfigurationError(ModuPortError, ValueError):
    """The supplied configuration is incomplete or malformed."""


class UnsupportedConfigurationError(ConfigurationError):
    """The supplied configuration is outside the validated public domain."""
