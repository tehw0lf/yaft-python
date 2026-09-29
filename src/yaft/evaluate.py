"""The evaluation rules, in one place (SPEC sections 2 and 3).

Providers call :func:`evaluate` instead of implementing the rules themselves
(R20), so every provider -- and every port that mirrors this module -- gives
the same answer for the same feature at the same instant.
"""

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

from .model import Feature

log = logging.getLogger("yaft")

Clock = Callable[[], datetime]
"""A source of the current time, as a timezone-aware ``datetime``.

Everything that evaluates takes one instead of reading the system time, so
tests -- and the conformance suite, which brings its own ``now`` per case --
can evaluate against a fixed instant (R9).
"""


def system_clock() -> datetime:
    """The default clock: the system time, in UTC."""
    return datetime.now(UTC)


# RFC 3339 with an explicit offset, and nothing else (R10). re.ASCII matters:
# without it \d also matches digits of other scripts, which int() then reads.
_RFC3339 = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(?:([Zz])|([+-])(\d{2}):(\d{2}))",
    re.ASCII,
)


def parse_timestamp(value: object) -> datetime | None:
    """Parses an RFC 3339 timestamp with an offset into an aware ``datetime``.

    Returns ``None`` for anything unset, malformed or in another format;
    callers treat that as no bound, never as an error (R8). An invalid value
    is logged as a warning but never raises, so a bad timestamp in the backend
    cannot take an application down.

    ``datetime`` does the calendar checks: it rejects an impossible date or
    time instead of rolling it over (R11), and a leap second with it (R12).
    Fractional seconds are truncated to milliseconds (R27); offsets up to
    ``±23:59`` are applied (R13, R28).
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        log.warning("YaFT: ignoring %r, expected an RFC 3339 string", value)
        return None

    match = _RFC3339.fullmatch(value)
    if match is None:
        log.warning(
            'YaFT: ignoring "%s", expected RFC 3339 with an offset (e.g. 2026-09-18T15:00:00Z)',
            value,
        )
        return None

    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    fraction, zulu, sign, offset_hours, offset_minutes = match.group(7, 8, 9, 10, 11)

    # timedelta would carry minute 60 into the hour, so it is checked here;
    # timezone() itself rejects 24 hours and more.
    if not zulu and int(offset_minutes) > 59:
        log.warning('YaFT: ignoring "%s", not a valid offset', value)
        return None
    offset = timedelta(hours=int(offset_hours or 0), minutes=int(offset_minutes or 0))

    try:
        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            # Truncated, not rounded: .9999 is .999, never the next second (R27).
            int((fraction or "")[:3].ljust(3, "0")) * 1000,
            tzinfo=UTC if zulu else timezone(-offset if sign == "-" else offset),
        )
    except ValueError:
        log.warning('YaFT: ignoring "%s", not a valid date, time or offset', value)
        return None


def evaluate(feature: Feature | None, now: datetime) -> bool:
    """Decides whether ``feature`` is on at the instant ``now``.

    - A missing feature is off (R3).
    - Only the exact string ``"true"`` is on (R4).
    - The window is ``[active_at, disabled_at)``: on at exactly ``active_at``,
      off at exactly ``disabled_at`` (R5, R6).
    - ``active_at`` after ``disabled_at`` is not special-cased; the window is
      simply never open (R7).
    - An unset or unparseable bound is ignored (R8).

    ``now`` must be timezone-aware; a naive ``datetime`` raises ``ValueError``,
    because guessing a timezone would flip the same feature at a different time
    on every machine. It is truncated to milliseconds, like the bounds.
    """
    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware, e.g. datetime.now(UTC)")
    if feature is None or feature.value != "true":
        return False

    now = now.replace(microsecond=now.microsecond // 1000 * 1000)

    active_at = parse_timestamp(feature.active_at)
    if active_at is not None and now < active_at:
        return False

    disabled_at = parse_timestamp(feature.disabled_at)
    return not (disabled_at is not None and now >= disabled_at)
