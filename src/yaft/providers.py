"""Providers: where feature data comes from, and how a key is answered (SPEC section 5)."""

import json
import os
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Protocol, Self, runtime_checkable

from .evaluate import Clock, evaluate, system_clock
from .mapping import normalise_booleans, normalise_feature, normalise_group
from .model import Feature


@runtime_checkable
class FeatureProvider(Protocol):
    """Anything that answers whether a feature is on.

    A feature-shape provider holds :class:`Feature` records and delegates to
    :func:`yaft.evaluate` (R20); a boolean-shape provider holds plain booleans
    and has no time logic (R21). Any object with ``is_enabled`` will do, for
    example one backed by environment variables.
    """

    def is_enabled(self, key: str) -> bool: ...


class LocalFeatureProvider:
    """A feature-shape provider over data held in memory.

    Time bounds are evaluated against ``clock`` on every call. Replacing the
    data swaps a reference, so readers on other threads see either the old or
    the new data, never a mix.
    """

    def __init__(self, data: Mapping[str, Feature] | None = None, clock: Clock = system_clock):
        self._clock = clock
        self._data: Mapping[str, Feature] = MappingProxyType(dict(data or {}))

    @classmethod
    def from_response(cls, response: object, clock: Clock = system_clock) -> Self:
        """Builds a provider from a parsed backend response (R22).

        Raises ``ValueError`` if ``response`` is not a toggle group (R30).
        """
        provider = cls(clock=clock)
        provider.load(response)
        return provider

    @classmethod
    def from_file(cls, path: str | os.PathLike[str], clock: Clock = system_clock) -> Self:
        """Reads a JSON file: a backend response, or features keyed by name.

        The keyed form is what yaft-ts reads from local files::

            {"myToggle": {"value": "true", "activeAt": "", "disabledAt": ""}}

        A missing or unreadable file raises, rather than starting with every
        feature off.
        """
        with open(path, encoding="utf-8") as file:
            content = json.load(file)
        group = normalise_group(content)
        if group is None:
            group = _keyed_features(content)
        return cls(group, clock)

    @property
    def data(self) -> Mapping[str, Feature]:
        """The current features by key, read-only."""
        return self._data

    def replace(self, data: Mapping[str, Feature]) -> None:
        """Swaps the data, for example after reloading it. The mapping is copied."""
        self._data = MappingProxyType(dict(data))

    def load(self, response: object) -> None:
        """Replaces the data with the group in a parsed backend response.

        The refresh succeeds or fails as a whole (R30). A group -- even an
        empty one -- replaces the data completely, so a toggle missing from it
        is off. Anything else raises ``ValueError`` and leaves the data as it
        was: storing a proxy's error page as "no toggles" would switch every
        feature off without an error.
        """
        group = normalise_group(response)
        if group is None:
            raise ValueError(f"not a toggle group: {_preview(response)}")
        self.replace(group)

    def is_enabled(self, key: str) -> bool:
        """Evaluates the feature stored under ``key``; a missing key is off."""
        return evaluate(self._data.get(key), self._clock())


class LocalBooleanProvider:
    """A boolean-shape provider: ``{"myToggle": true}``, no time logic (R21).

    Only the boolean ``True`` is on. Anything that is not a boolean is dropped
    when the data is set, so its key reads as missing and therefore off (R29).
    """

    def __init__(self, data: Mapping[str, Any] | None = None):
        self._data: Mapping[str, bool] = MappingProxyType(normalise_booleans(data or {}))

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> Self:
        """Reads a JSON object of booleans. A missing or unreadable file raises."""
        with open(path, encoding="utf-8") as file:
            content = json.load(file)
        if not isinstance(content, Mapping):
            raise ValueError(f"{os.fspath(path)}: expected a JSON object, got {_preview(content)}")
        return cls(content)

    @property
    def data(self) -> Mapping[str, bool]:
        """The current booleans by key, read-only."""
        return self._data

    def replace(self, data: Mapping[str, Any]) -> None:
        """Swaps the data; entries that are not booleans are dropped (R29)."""
        self._data = MappingProxyType(normalise_booleans(data))

    def is_enabled(self, key: str) -> bool:
        return self._data.get(key) is True


def _keyed_features(content: object) -> dict[str, Feature]:
    """Reads ``{"name": {feature}}``; each feature is stored under its name."""
    if not isinstance(content, Mapping):
        raise ValueError(f"not a toggle group or features keyed by name: {_preview(content)}")
    return {
        name: normalise_feature({**raw, "key": name})
        for name, raw in content.items()
        if isinstance(name, str) and name != "" and isinstance(raw, Mapping)
    }


def _preview(value: object) -> str:
    text = repr(value)
    return text if len(text) <= 80 else text[:77] + "..."
