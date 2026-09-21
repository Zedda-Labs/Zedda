from __future__ import annotations


class ZeddaError(Exception):
    """Base class for all exceptions raised by zedda."""

    pass


class ZeddaTypeError(ZeddaError, TypeError):
    """Raised when an argument has an inappropriate type."""

    pass

