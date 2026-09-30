"""Runs the shared mapping cases against this port.

These pin down how a backend response becomes provider data: which envelopes
exist, how the two field spellings are reconciled, that a present but empty
value is kept, and that a refresh replaces the data as a whole or not at all.
"""

from collections.abc import Mapping

import pytest

from yaft import (
    APIFeatureProvider,
    Feature,
    LocalBooleanProvider,
    RefreshError,
    normalise_collection,
)

from ..backend import GROUP, Backend, running
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
            with running() as backend:
                refresh(case, backend)
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


def refresh(case: Case, backend: Backend) -> None:
    """A refresh case (R30, R32) through the API provider, over HTTP.

    ``held`` is loaded first, then the backend answers with a new hash and
    ``response``. The refresh must raise exactly when the case says the
    response is rejected (R32), and leave the data the case expects. ``retry``
    comes with the same hash as the rejected response: a provider that
    recorded the hash of a body it rejected never fetches again (R30).
    """
    rejected = case["rejected"]
    if not isinstance(rejected, bool):
        unsupported("rejected", rejected, case)

    backend.serve("held", {"toggles": list(case["held"].values())})
    provider = APIFeatureProvider(backend.url, GROUP)
    assert provider.refresh()
    assert records(provider.data) == case["held"]

    backend.serve("response", case["response"])
    if rejected:
        with pytest.raises(RefreshError):
            provider.refresh()
    else:
        provider.refresh()
    assert records(provider.data) == case["expected"]

    retry = case.get("retry")
    if retry is not None:
        if not isinstance(retry, dict):
            unsupported("retry", retry, case)
        backend.serve("response", retry["response"])
        provider.refresh()
        assert records(provider.data) == retry["expected"]
