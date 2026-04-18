"""
Pluggable backend registry.

Every cost backend — shipped or user-written — registers itself here. The
CLI, the agent node, and the FastAPI server all look up backends through
this single registry, so adding a new backend is:

    from iaccostagent.backends.base import CostBackend
    from iaccostagent.backends.registry import register_backend

    @register_backend("my-cloud")
    class MyCloudBackend(CostBackend):
        ...

Users can also call `register_backend` at runtime (e.g. from a plugin or
from their own code before invoking the CLI).
"""

from collections.abc import Callable

from iaccostagent.backends.base import CostBackend

_BACKENDS: dict[str, type[CostBackend]] = {}


def register_backend(name: str) -> Callable[[type[CostBackend]], type[CostBackend]]:
    """Class decorator that registers a CostBackend subclass under `name`."""

    def _decorator(cls: type[CostBackend]) -> type[CostBackend]:
        if name in _BACKENDS:
            raise ValueError(f"Backend '{name}' is already registered")
        _BACKENDS[name] = cls
        return cls

    return _decorator


def get_backend(name: str) -> CostBackend:
    """Instantiate a registered backend by name. Raises KeyError if unknown."""
    cls = _BACKENDS.get(name)
    if cls is None:
        raise KeyError(f"Unknown cost backend: '{name}'. Registered: {', '.join(sorted(_BACKENDS))}")
    return cls()


def list_backends() -> list[str]:
    """Return all registered backend names (sorted)."""
    return sorted(_BACKENDS)


def _autodiscover() -> None:
    """Import the shipped backend modules so their @register_backend runs.

    Kept in its own function so tests can control ordering. Imports here
    are deliberate side-effects — removing them would unregister the
    shipped backends.
    """
    from iaccostagent.backends import (  # noqa: F401  (imports for side effects)
        aws_pricing,
        azure_retail,
        gcp_catalog,
        infracost,
        openinfraquote,
    )


_autodiscover()
