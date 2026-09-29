"""The feature record every provider of the feature shape holds (SPEC section 1)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Feature:
    """One feature toggle.

    ``value`` is a string, not a boolean: the backend stores it as one, and only
    the exact string ``"true"`` is on (R1, R4). ``active_at`` and
    ``disabled_at`` are RFC 3339 timestamps with an offset, or ``""`` for no
    bound (R2).
    """

    key: str
    value: str
    active_at: str = ""
    disabled_at: str = ""
    tags: tuple[str, ...] = ()
