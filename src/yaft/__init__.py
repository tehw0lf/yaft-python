"""YaFT - Yet another Feature Toggle.

Decorators that switch functions, methods and classes on and off, evaluated by
the rules every YaFT port shares (https://github.com/tehw0lf/yaft-conformance)::

    from yaft import LocalFeatureProvider, feature_toggle, set_provider

    set_provider(LocalFeatureProvider.from_file("features.json"))

    class Checkout:
        @feature_toggle("new-pricing", fallback=lambda self, cart: sum(cart))
        def total(self, cart: list[int]) -> int: ...
"""

from importlib.metadata import PackageNotFoundError, version

from .api import APIFeatureProvider, RefreshError
from .evaluate import Clock, evaluate, parse_timestamp, system_clock
from .mapping import normalise_booleans, normalise_collection, normalise_feature, normalise_group
from .model import Feature
from .providers import FeatureProvider, LocalBooleanProvider, LocalFeatureProvider
from .toggle import ProviderNotSetError, feature_toggle, get_provider, set_provider

try:
    __version__ = version("yaft")
except PackageNotFoundError:  # pragma: no cover - only without an installed distribution
    __version__ = "0+unknown"

__all__ = [
    "APIFeatureProvider",
    "Clock",
    "Feature",
    "FeatureProvider",
    "LocalBooleanProvider",
    "LocalFeatureProvider",
    "ProviderNotSetError",
    "RefreshError",
    "__version__",
    "evaluate",
    "feature_toggle",
    "get_provider",
    "normalise_booleans",
    "normalise_collection",
    "normalise_feature",
    "normalise_group",
    "parse_timestamp",
    "set_provider",
    "system_clock",
]
