"""Runs the shared evaluation cases against this port.

Each case brings its own ``now``, which is why the clock is injectable (R9).
"""

import pytest

from yaft import evaluate, normalise_feature, parse_timestamp

from .cases import Case, load, title

CASES = load("evaluation")


def test_loads_the_suite() -> None:
    assert CASES


@pytest.mark.parametrize("case", CASES, ids=title)
def test_evaluation(case: Case) -> None:
    now = parse_timestamp(case["now"])
    # A case whose own now does not parse would evaluate against nothing and
    # pass or fail for the wrong reason.
    assert now is not None, f"now {case['now']!r} does not parse"

    raw = case["features"].get(case["key"])
    feature = normalise_feature(raw) if raw is not None else None
    assert evaluate(feature, now) is case["expected"]
