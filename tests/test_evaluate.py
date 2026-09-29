"""What the conformance suite cannot see: Python's own traps around time."""

import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest

from yaft import Feature, evaluate, parse_timestamp, system_clock

ON = Feature(key="f", value="true")


def test_parses_to_an_aware_datetime() -> None:
    assert parse_timestamp("2026-09-18T14:00:00+02:00") == datetime(2026, 9, 18, 12, tzinfo=UTC)
    assert parse_timestamp("2026-09-18T12:00:00.123456Z") == datetime(
        2026, 9, 18, 12, 0, 0, 123_000, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "value",
    [
        # \d without re.ASCII matches digits of other scripts, and int() reads
        # them: this would parse as 2026-09-18.
        "\u0662\u0660\u0662\u0666-\u0660\u0669-\u0661\u0668T12:00:00Z",  # Arabic-Indic digits
        # re.match with $ allows a trailing newline; fullmatch does not.
        "2026-09-18T12:00:00Z\n",
        " 2026-09-18T12:00:00Z",
    ],
)
def test_rejects_what_a_loose_pattern_lets_through(value: str) -> None:
    assert parse_timestamp(value) is None


@pytest.mark.parametrize("value", [None, "", 1_789_732_800, ["2026-09-18T12:00:00Z"]])
def test_ignores_what_is_not_a_timestamp_string(value: object) -> None:
    assert parse_timestamp(value) is None


def test_warns_about_an_ignored_bound(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="yaft"):
        assert parse_timestamp("2026-09-18") is None
    assert "2026-09-18" in caplog.text


def test_now_must_be_timezone_aware() -> None:
    # A naive datetime names no instant; guessing would flip at different
    # times on different machines.
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate(ON, datetime(2026, 9, 18, 12))


def test_now_in_any_timezone_is_the_same_instant() -> None:
    feature = Feature(key="f", value="true", active_at="2026-09-18T12:00:00Z")
    berlin = timezone(timedelta(hours=2))
    assert evaluate(feature, datetime(2026, 9, 18, 14, tzinfo=berlin))
    assert not evaluate(feature, datetime(2026, 9, 18, 13, 59, 59, 999_999, tzinfo=berlin))


def test_now_is_truncated_to_milliseconds() -> None:
    # Like a millisecond clock: .000999 is still .000, so a bound at .001 has
    # not been reached. Rounding would make it .001 and switch the feature off.
    feature = Feature(key="f", value="true", disabled_at="2026-09-18T12:00:00.001Z")
    assert evaluate(feature, datetime(2026, 9, 18, 12, 0, 0, 999, tzinfo=UTC))


def test_system_clock_is_aware() -> None:
    assert system_clock().utcoffset() == timedelta(0)
