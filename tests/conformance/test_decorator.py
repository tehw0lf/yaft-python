"""Runs the shared decorator cases against this port.

These are scenarios rather than input/output pairs -- "the fallback receives
the same receiver" cannot be written as JSON. Each case names a scenario and an
outcome in port-neutral terms, and this module maps them onto Python
decorators. An unknown value fails instead of being skipped.
"""

import asyncio
import inspect
from collections.abc import Iterator
from typing import Any

import pytest

from yaft import ProviderNotSetError, feature_toggle, get_provider, set_provider

from .cases import Case, load, title, unsupported

CASES = load("decorator")
KEY = "conformanceToggle"
ORIGINAL = "original"
FALLBACK = "fallback"


class SwitchableProvider:
    """A provider whose answer can change between decoration and call."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def is_enabled(self, key: str) -> bool:
        return self.enabled


@pytest.fixture(autouse=True)
def restore_provider() -> Iterator[None]:
    saved = get_provider()
    yield
    set_provider(saved)


def set_up(case: Case) -> SwitchableProvider:
    """Installs a provider in the state ``toggle`` starts in.

    ``on-then-off`` is on while decorating and off by the time the class or
    method is used, which is what separates "evaluated once" (R14) from
    "evaluated per call" (R15).
    """
    match case["toggle"]:
        case "on" | "on-then-off":
            provider = SwitchableProvider(True)
        case "off" | "off-then-on":
            provider = SwitchableProvider(False)
        case other:
            unsupported("toggle", other, case)
    set_provider(provider)
    return provider


def flip_if_two_phase(case: Case, provider: SwitchableProvider) -> None:
    if case["toggle"] == "on-then-off":
        provider.enabled = False
    elif case["toggle"] == "off-then-on":
        provider.enabled = True


def test_loads_the_suite() -> None:
    assert CASES


@pytest.mark.parametrize("case", CASES, ids=title)
def test_decorator(case: Case) -> None:
    if case["toggle"] == "no-provider":
        expect_decoration_error(case)
        return
    match case["target"]:
        case "method":
            method_case(case)
        case "async-method":
            async_method_case(case)
        case "class":
            class_case(case)
        case other:
            unsupported("target", other, case)


def method_case(case: Case) -> None:
    provider = set_up(case)
    seen: dict[str, Any] = {"ran": ""}

    def fallback_method(this: object, *args: object) -> str:
        seen.update(ran=FALLBACK, args=args, receiver=this)
        return FALLBACK

    match case["fallback"]:
        case "none":
            fallback = None
        case "method":
            fallback = fallback_method
        case other:
            unsupported("fallback", f"{other} on a method target", case)

    class Subject:
        @feature_toggle(KEY, fallback)
        def run(self, *args: object) -> str:
            seen["ran"] = ORIGINAL
            return ORIGINAL

    flip_if_two_phase(case, provider)
    instance = Subject()
    result: object = instance.run("a", 1)

    match case["expected"]:
        case "original":
            assert (seen["ran"], result) == (ORIGINAL, ORIGINAL)
        case "fallback":
            assert (seen["ran"], result) == (FALLBACK, FALLBACK)
        case "nothing":
            assert (seen["ran"], result) == ("", None)
        case other:
            unsupported("expected", other, case)

    for assertion in case.get("assertions", []):
        match assertion:
            case "same-arguments":
                assert seen["args"] == ("a", 1)
            case "same-receiver":
                assert seen["receiver"] is instance
            case other:
                unsupported("assertion", other, case)


def async_method_case(case: Case) -> None:
    provider = set_up(case)
    if case["fallback"] != "none":
        unsupported("fallback", f"{case['fallback']} on an async method", case)
    seen = {"ran": ""}

    class Subject:
        @feature_toggle(KEY)
        async def run(self) -> str:
            seen["ran"] = ORIGINAL
            return ORIGINAL

    flip_if_two_phase(case, provider)
    result = Subject().run()
    # An await at the call site must not break: the result is awaitable even
    # when the method is off (R18).
    assert inspect.iscoroutine(result)
    value = asyncio.run(result)

    match case["expected"]:
        case "original":
            assert (seen["ran"], value) == (ORIGINAL, ORIGINAL)
        case "resolved-nothing":
            assert (seen["ran"], value) == ("", None)
        case other:
            unsupported("expected", other, case)


def class_case(case: Case) -> None:
    provider = set_up(case)

    class FallbackClass:
        def which(self) -> str:
            return FALLBACK

    match case["fallback"]:
        case "none":
            fallback: type | None = None
        case "class":
            fallback = FallbackClass
        case other:
            unsupported("fallback", f"{other} on a class target", case)

    @feature_toggle(KEY, fallback)
    class Subject:
        def which(self) -> str:
            return ORIGINAL

    # A class is decided when it is decorated, so this flip must have no
    # effect -- exactly what the two-phase cases check (R14).
    flip_if_two_phase(case, provider)
    which = Subject().which()

    match case["expected"]:
        case "original":
            assert which == ORIGINAL
        case "fallback":
            assert which == FALLBACK
        case "empty-shell":
            # The shell still answers every method of the original, each with
            # nothing, so calling into a disabled class does not raise.
            assert which is None
        case other:
            unsupported("expected", other, case)


def expect_decoration_error(case: Case) -> None:
    """With no provider, decorating itself must fail, not the first call (R16)."""
    if case["expected"] != "decoration-error":
        unsupported("expected", case["expected"], case)
    set_provider(None)
    with pytest.raises(ProviderNotSetError, match="FeatureToggleProvider not set"):
        feature_toggle(KEY)
