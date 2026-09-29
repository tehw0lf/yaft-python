"""Runs the shared mapping cases against this port.

These pin down how a backend response becomes provider data: which envelopes
exist, how the two field spellings are reconciled, that a present but empty
value is kept, and that a refresh replaces the data as a whole or not at all.
"""

from collections.abc import Mapping

import pytest

from yaft import Feature, LocalBooleanProvider, LocalFeatureProvider, normalise_collection

from .cases import Case, as_record, load, title, unsupported

CASES = load("mapping")


def records(data: Mapping[str, Feature]) -> dict[str, object]:
    return {key: as_record(feature) for key, feature in data.items()}


def test_loads_the_suite() -> None:
    assert CASES


@pytest.mark.parametrize("case", CASES, ids=title)
def test_mapping(case: Case) -> None:
    match case["shape"]:
        case "feature" if "held" in case:
            refresh(case)
        case "feature":
            assert records(normalise_collection(case["response"])) == case["expected"]
        case "boolean":
            provider = LocalBooleanProvider(case["response"])
            assert dict(provider.data) == case["expected"]
            probes = case.get("isEnabled")
            if not probes:
                raise AssertionError(f'Case "{case["name"]}" has no isEnabled probes')
            for key, enabled in probes.items():
                assert (key, provider.is_enabled(key)) == (key, enabled)
        case other:
            unsupported("shape", other, case)


def refresh(case: Case) -> None:
    """A refresh case (R30, R32): ``held`` is loaded, then ``response`` arrives.

    This port has no API provider yet, so the refresh goes through
    ``LocalFeatureProvider.load``, which the API provider will use as well.
    ``load`` must raise exactly when the case says the response is rejected
    (R32), and leave the data the case expects. ``retry`` checks that a
    rejected refresh does not block the next one; without a collection hash
    there is nothing to record, so here it only checks the data it loads.
    """
    rejected = case["rejected"]
    if not isinstance(rejected, bool):
        unsupported("rejected", rejected, case)

    provider = LocalFeatureProvider.from_response({"toggles": list(case["held"].values())})
    assert records(provider.data) == case["held"]

    if rejected:
        with pytest.raises(ValueError, match="not a toggle group"):
            provider.load(case["response"])
    else:
        provider.load(case["response"])
    assert records(provider.data) == case["expected"]

    retry = case.get("retry")
    if retry is not None:
        provider.load(retry["response"])
        assert records(provider.data) == retry["expected"]
