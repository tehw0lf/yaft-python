"""The evaluation rules, in one place (SPEC sections 2 and 3).

Providers call :func:`evaluate` instead of implementing the rules themselves
(R20), so every provider -- and every port that mirrors this module -- gives
the same answer for the same feature at the same instant.
"""

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime

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

_DAYS_IN_MONTH = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _days_in_month(year: int, month: int) -> int:
    leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
    return 29 if month == 2 and leap else _DAYS_IN_MONTH[month]


def _days_from_civil(year: int, month: int, day: int) -> int:
    """Days since 1970-01-01 in the proleptic Gregorian calendar.

    Computed rather than taken from ``datetime``, which stops at year 1 and
    cannot represent every instant JavaScript's ``Date.parse`` can.
    """
    year -= month <= 2
    era = (year if year >= 0 else year - 399) // 400
    year_of_era = year - era * 400
    day_of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146097 + day_of_era - 719468


def parse_timestamp(value: object) -> int | None:
    """Parses an RFC 3339 timestamp with an offset into epoch milliseconds.

    Returns ``None`` for anything unset, malformed or in another format;
    callers treat that as no bound, never as an error (R8). An invalid value
    is logged as a warning but never raises, so a bad timestamp in the backend
    cannot take an application down.

    Fractional seconds are truncated to milliseconds (R27), the calendar is
    range-checked before anything is computed (R11), a leap second is ignored
    (R12) and the offset is applied, up to ``±23:59`` (R13, R28).
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

    # Checked before anything is computed: the arithmetic below would roll an
    # impossible date over instead of rejecting it, turning 2027-02-30 into
    # 2027-03-02 (R11).
    if not 1 <= month <= 12 or not 1 <= day <= _days_in_month(year, month):
        log.warning('YaFT: ignoring "%s", not a valid date', value)
        return None
    if hour > 23 or minute > 59 or second > 60:
        log.warning('YaFT: ignoring "%s", not a valid time', value)
        return None
    if second == 60:
        # RFC 3339 permits a leap second, but not every language can represent
        # one, so every port ignores it (R12).
        log.warning('YaFT: ignoring "%s", a leap second is not supported', value)
        return None

    offset = 0
    if not zulu:
        if int(offset_hours) > 23 or int(offset_minutes) > 59:
            log.warning('YaFT: ignoring "%s", not a valid offset', value)
            return None
        offset = (int(offset_hours) * 60 + int(offset_minutes)) * 60_000
        if sign == "-":
            offset = -offset

    # Truncated, not rounded: .9999 is .999, never the next second (R27).
    millis = int((fraction or "")[:3].ljust(3, "0"))
    seconds = ((_days_from_civil(year, month, day) * 24 + hour) * 60 + minute) * 60 + second
    return seconds * 1000 + millis - offset


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _epoch_millis(now: datetime) -> int:
    if now.utcoffset() is None:
        # A naive datetime has no instant; guessing a timezone would make the
        # same feature flip at a different time on every machine.
        raise ValueError("now must be timezone-aware, e.g. datetime.now(UTC)")
    delta = now - _EPOCH
    # Integer arithmetic, truncated towards the past, like a millisecond clock.
    return (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000


def evaluate(feature: Feature | None, now: datetime) -> bool:
    """Decides whether ``feature`` is on at the instant ``now``.

    - A missing feature is off (R3).
    - Only the exact string ``"true"`` is on (R4).
    - The window is ``[active_at, disabled_at)``: on at exactly ``active_at``,
      off at exactly ``disabled_at`` (R5, R6).
    - ``active_at`` after ``disabled_at`` is not special-cased; the window is
      simply never open (R7).
    - An unset or unparseable bound is ignored (R8).

    ``now`` must be timezone-aware; a naive ``datetime`` raises ``ValueError``.
    """
    if feature is None or feature.value != "true":
        return False

    instant = _epoch_millis(now)

    active_at = parse_timestamp(feature.active_at)
    if active_at is not None and instant < active_at:
        return False

    disabled_at = parse_timestamp(feature.disabled_at)
    return not (disabled_at is not None and instant >= disabled_at)
