"""Turns a backend response or a local file into provider data (SPEC section 6).

This is the single definition of the mapping rules, the way
:func:`yaft.evaluate` is the single definition of the evaluation rules.
"""

from collections.abc import Mapping
from typing import Any

from .model import Feature


def _field(raw: Mapping[str, Any], lower: str, upper: str) -> Any:
    """Reads a field by presence, not by truthiness (R23).

    ``raw.get("value") or raw.get("Value")`` is wrong: a present but empty
    value falls through to the other spelling, so a feature stored as ``""``
    reads as whatever the capitalised field holds, and an off feature reports
    on. The same trap applies to ``tags: []``.
    """
    if lower in raw:
        return raw[lower]
    if upper in raw:
        return raw[upper]
    return None


def _text(value: Any) -> str:
    """A string field, or ``""`` for anything that is not a string.

    ``value`` is a string by definition (R1); a JSON boolean belongs in the
    boolean shape, not here. So ``"value": true`` is not coerced to ``"true"``
    -- it is not set, and the feature is off. A key that is not a string is
    likewise no key, and the entry is skipped (R25). The backend sends ``null``
    for an unset bound and fixtures ``""``; both are no bound (R24).
    """
    return value if isinstance(value, str) else ""


def normalise_feature(raw: Mapping[str, Any]) -> Feature:
    """Normalises one entry into a :class:`Feature`, in either field spelling (R22a)."""
    tags = _field(raw, "tags", "Tags")
    return Feature(
        key=_text(_field(raw, "key", "Key")),
        value=_text(_field(raw, "value", "Value")),
        active_at=_text(_field(raw, "activeAt", "ActiveAt")),
        disabled_at=_text(_field(raw, "disabledAt", "DisabledAt")),
        # Filtered rather than trusted: a mixed array would otherwise hand
        # callers a non-string through a field typed as strings.
        tags=tuple(tag for tag in tags if isinstance(tag, str)) if isinstance(tags, list) else (),
    )


def _collection(body: Mapping[str, Any]) -> list[Any] | None:
    for name in ("toggles", "value"):
        entries = body.get(name)
        if isinstance(entries, list):
            return entries
    return None


def normalise_collection(response: object) -> dict[str, Feature]:
    """Normalises a whole response into features keyed by their key.

    Three envelopes are accepted, because the backend uses all three (R22):
    ``{"toggles": [...]}`` for a UUID group, ``{"value": [...]}`` for the same
    thing under another name, and a flat object for a single toggle. An entry
    without a usable key is skipped rather than stored under ``""`` (R25).
    """
    if not isinstance(response, Mapping):
        return {}

    collection = _collection(response)
    entries = collection if collection is not None else [response]

    data: dict[str, Feature] = {}
    for entry in entries:
        if isinstance(entry, Mapping):
            feature = normalise_feature(entry)
            if feature.key != "":
                data[feature.key] = feature
    return data


def normalise_group(response: object) -> dict[str, Feature] | None:
    """Normalises a response, but only if it is recognisably a toggle group (R30).

    A group is a collection envelope -- an empty one is a valid empty group --
    or a single toggle. Returns ``None`` for anything else: ``None``, a list,
    a proxy's error object, or a collection none of whose entries is usable.
    :func:`normalise_collection` turns all of those into ``{}``, and a provider
    storing that would switch every feature off without an error.
    """
    if not isinstance(response, Mapping):
        return None
    data = normalise_collection(response)
    if data:
        return data
    collection = _collection(response)
    return data if collection is not None and len(collection) == 0 else None


def normalise_booleans(response: object) -> dict[str, bool]:
    """Normalises a boolean-shape payload, ``{"myToggle": true}``.

    Only real booleans are kept (R29). Anything else is dropped, so its key
    reads as missing and therefore off. Keeping it and testing its truthiness
    would turn ``"false"`` on, since a non-empty string is truthy.
    """
    if not isinstance(response, Mapping):
        return {}
    return {
        key: value
        for key, value in response.items()
        if isinstance(key, str) and isinstance(value, bool)
    }
