"""The decorator beyond the shared cases: Python's other kinds of callables."""

import asyncio
import inspect
from collections.abc import AsyncIterator, Iterator
from types import TracebackType
from typing import Any

import pytest

from yaft import ProviderNotSetError, feature_toggle, get_provider, set_provider


class Switch:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def is_enabled(self, key: str) -> bool:
        return self.enabled


@pytest.fixture
def switch() -> Iterator[Switch]:
    saved = get_provider()
    provider = Switch()
    set_provider(provider)
    yield provider
    set_provider(saved)


async def collect(source: AsyncIterator[Any]) -> list[Any]:
    return [item async for item in source]


def test_keeps_name_and_coroutine_function_marker(switch: Switch) -> None:
    @feature_toggle("k")
    async def fetch() -> str:
        """Fetches."""
        return "data"

    # Frameworks such as FastAPI decide whether to await by this check.
    assert inspect.iscoroutinefunction(fetch)
    assert (fetch.__name__, fetch.__doc__) == ("fetch", "Fetches.")


def test_async_method_takes_a_sync_or_async_fallback(switch: Switch) -> None:
    async def async_fallback() -> str:
        return "async"

    @feature_toggle("k", fallback=lambda: "sync")
    async def with_sync() -> str:
        return "original"

    @feature_toggle("k", fallback=async_fallback)
    async def with_async() -> str:
        return "original"

    switch.enabled = False
    assert asyncio.run(with_sync()) == "sync"
    assert asyncio.run(with_async()) == "async"


def test_generator_off_is_an_empty_iterator(switch: Switch) -> None:
    @feature_toggle("k")
    def numbers() -> Iterator[int]:
        yield from (1, 2)

    assert list(numbers()) == [1, 2]
    switch.enabled = False
    # None here would break the caller's for loop, the way None breaks await.
    assert list(numbers()) == []


def test_generator_fallback(switch: Switch) -> None:
    @feature_toggle("k", fallback=lambda: iter([9]))
    def numbers() -> Iterator[int]:
        yield 1

    switch.enabled = False
    assert list(numbers()) == [9]


def test_async_generator(switch: Switch) -> None:
    async def fallback() -> AsyncIterator[int]:
        yield 9

    @feature_toggle("k")
    async def plain() -> AsyncIterator[int]:
        yield 1

    @feature_toggle("k", fallback=fallback)
    async def with_fallback() -> AsyncIterator[int]:
        yield 1

    assert asyncio.run(collect(plain())) == [1]
    switch.enabled = False
    assert asyncio.run(collect(plain())) == []
    assert asyncio.run(collect(with_fallback())) == [9]


def test_static_and_class_methods(switch: Switch) -> None:
    class Subject:
        name = "subject"

        @feature_toggle("k")
        @staticmethod
        def static() -> str:
            return "static"

        @feature_toggle("k", fallback=lambda cls: f"fallback {cls.name}")
        @classmethod
        def klass(cls) -> str:
            return f"class {cls.name}"

    assert (Subject.static(), Subject.klass()) == ("static", "class subject")
    switch.enabled = False
    # Typed as the original's str; off, the static method returns nothing.
    results: tuple[object, object] = (Subject.static(), Subject.klass())
    assert results == (None, "fallback subject")


def test_fallback_can_be_a_method_of_the_same_class(switch: Switch) -> None:
    class Pricing:
        rate = 2

        def old(self, amount: int) -> int:
            return amount

        @feature_toggle("k", fallback=old)
        def new(self, amount: int) -> int:
            return amount * self.rate

    switch.enabled = False
    assert Pricing().new(5) == 5


def test_empty_shell_stands_in_for_the_class(switch: Switch) -> None:
    class Base:
        def inherited(self) -> str:
            return "inherited"

    class Service(Base):
        limit = 3

        def __init__(self, url: str):
            self.url = url

        def run(self) -> str:
            return "run"

        async def fetch(self) -> str:
            return "fetch"

        def items(self) -> Iterator[int]:
            yield 1

        @property
        def status(self) -> str:
            return "ok"

        @status.setter
        def status(self, value: str) -> None:
            pass

        @property
        def read_only(self) -> str:
            return "ro"

        @staticmethod
        def helper() -> str:
            return "helper"

        def __call__(self) -> str:
            return "called"

        def __enter__(self) -> "Service":
            return self

        def __exit__(
            self,
            kind: type[BaseException] | None,
            error: BaseException | None,
            trace: TracebackType | None,
        ) -> None:
            pass

    switch.enabled = False
    Shell = feature_toggle("k")(Service)

    assert Shell is not Service
    assert Shell.__name__ == "Service"
    # Created wherever the original was, with the original's arguments.
    shell = Shell("https://example.test")
    assert shell.run() is None
    assert shell.inherited() is None
    assert asyncio.run(shell.fetch()) is None
    assert list(shell.items()) == []
    assert shell.status is None
    shell.status = "ignored"
    with pytest.raises(AttributeError):
        shell.read_only = "x"
    assert Shell.helper() is None
    assert shell() is None
    with shell as entered:
        assert entered is None
    # Only behaviour is stubbed; data attributes are not copied.
    assert not hasattr(shell, "limit")


def test_shell_stubs_keep_their_own_names(switch: Switch) -> None:
    # functools.wraps mutates the function it is handed; wrapping one shared
    # function would give every stub the name of the last one.
    class Service:
        def first(self) -> None: ...

        def second(self) -> None: ...

    switch.enabled = False
    shell = feature_toggle("k")(Service)
    assert (shell.first.__name__, shell.second.__name__) == ("first", "second")


def test_class_fallback_must_be_a_class(switch: Switch) -> None:
    with pytest.raises(TypeError, match="must be a class"):

        @feature_toggle("k", fallback=lambda: None)
        class Subject:
            pass


def test_function_fallback_must_be_a_function(switch: Switch) -> None:
    class NotAFunction:
        pass

    with pytest.raises(TypeError, match="must be a function"):

        @feature_toggle("k", fallback=NotAFunction)
        def run() -> None: ...

    with pytest.raises(TypeError, match="must be a function"):

        @feature_toggle("k", fallback="old")
        def run_by_name() -> None: ...


def test_rejects_what_it_cannot_decorate(switch: Switch) -> None:
    with pytest.raises(TypeError, match="cannot decorate"):
        feature_toggle("k")(42)


def test_provider_removed_after_decoration_fails_at_the_call(switch: Switch) -> None:
    @feature_toggle("k")
    def run() -> str:
        return "run"

    set_provider(None)
    with pytest.raises(ProviderNotSetError):
        run()


def test_the_provider_is_asked_on_every_call(switch: Switch) -> None:
    @feature_toggle("k")
    def run() -> str:
        return "run"

    replacement = Switch(enabled=False)
    set_provider(replacement)
    assert run() is None
