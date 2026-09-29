"""The ``feature_toggle`` decorator (SPEC section 4).

When a toggle is evaluated is observable, so it is fixed:

- a **class** is decided once, when it is decorated (R14);
- a **function or method** is decided on every call (R15).
"""

import functools
import inspect
from collections.abc import AsyncIterator, Callable, Generator, Iterator
from typing import Any, TypeVar

from .providers import FeatureProvider

_T = TypeVar("_T")

_provider: FeatureProvider | None = None


class ProviderNotSetError(RuntimeError):
    """Raised when a toggle is used before :func:`set_provider` (R16)."""

    def __init__(self) -> None:
        super().__init__("FeatureToggleProvider not set")


def set_provider(provider: FeatureProvider | None) -> None:
    """Installs the provider every toggle asks; ``None`` removes it.

    A decorated method asks whichever provider is installed when it is called,
    so replacing the provider takes effect on the next call.
    """
    global _provider
    _provider = provider


def get_provider() -> FeatureProvider | None:
    """The installed provider, or ``None``."""
    return _provider


def _is_enabled(key: str) -> bool:
    provider = _provider
    if provider is None:
        raise ProviderNotSetError
    return provider.is_enabled(key)


def feature_toggle(key: str, fallback: Any = None) -> Callable[[_T], _T]:
    """Switches a function, method or class on and off by the toggle ``key``.

    Off, a function or method runs ``fallback`` with the same arguments and the
    same ``self`` (R19), or returns *nothing* without one: ``None``, a
    coroutine resolving to ``None`` for an ``async def`` (R18), an empty
    iterator for a generator. Off, a class is replaced by ``fallback``, or by
    an empty shell whose methods all return *nothing* (R17).

    Raises :class:`ProviderNotSetError` right here, at decoration time, if no
    provider is installed (R16), and ``TypeError`` for a fallback of the wrong
    kind -- a startup misconfiguration should not wait for the first call.
    """
    if _provider is None:
        raise ProviderNotSetError

    def decorate(target: _T) -> _T:
        if isinstance(target, type):
            result: Any = _toggle_class(target, key, fallback)
        elif isinstance(target, staticmethod | classmethod):
            result = type(target)(_toggle_function(target.__func__, key, fallback))
        elif callable(target):
            result = _toggle_function(target, key, fallback)
        else:
            raise TypeError(f"feature_toggle({key!r}) cannot decorate {target!r}")
        return result  # type: ignore[no-any-return]

    return decorate


def _toggle_class(cls: type, key: str, fallback: Any) -> type:
    if fallback is not None and not isinstance(fallback, type):
        raise TypeError(f"feature_toggle({key!r}): a class's fallback must be a class")
    if _is_enabled(key):
        return cls
    return fallback if fallback is not None else _empty_shell(cls)


def _toggle_function(fn: Callable[..., Any], key: str, fallback: Any) -> Callable[..., Any]:
    if fallback is not None and (isinstance(fallback, type) or not callable(fallback)):
        raise TypeError(f"feature_toggle({key!r}): a function's fallback must be a function")

    if inspect.iscoroutinefunction(fn):
        # An async def wrapper keeps inspect.iscoroutinefunction true, which
        # frameworks such as FastAPI check. The toggle is read when the
        # coroutine starts, which for `await f()` is the call.
        @functools.wraps(fn)
        async def toggled_coroutine(*args: Any, **kwargs: Any) -> Any:
            if _is_enabled(key):
                return await fn(*args, **kwargs)
            if fallback is None:
                return None
            # A synchronous fallback is fine too; awaiting only what is awaitable
            # keeps the promise the signature makes either way.
            result = fallback(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result

        return toggled_coroutine

    if inspect.isgeneratorfunction(fn):

        @functools.wraps(fn)
        def toggled_generator(*args: Any, **kwargs: Any) -> Generator[Any, Any, Any]:
            if _is_enabled(key):
                return (yield from fn(*args, **kwargs))
            result = fallback(*args, **kwargs) if fallback is not None else None
            if result is not None:
                return (yield from result)
            return None

        return toggled_generator

    if inspect.isasyncgenfunction(fn):

        @functools.wraps(fn)
        async def toggled_async_generator(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            source = (
                fn(*args, **kwargs)
                if _is_enabled(key)
                else fallback(*args, **kwargs)
                if fallback is not None
                else None
            )
            if source is not None:
                async for item in source:
                    yield item

        return toggled_async_generator

    @functools.wraps(fn)
    def toggled(*args: Any, **kwargs: Any) -> Any:
        if _is_enabled(key):
            return fn(*args, **kwargs)
        return fallback(*args, **kwargs) if fallback is not None else None

    return toggled


# Dunder methods are left out of the shell: returning None from __len__ or
# __eq__ breaks the caller. These few are safe to answer with nothing, and
# without them a shell could not stand in for a callable or a context manager.
_SHELL_DUNDERS = frozenset({"__call__", "__enter__", "__exit__", "__aenter__", "__aexit__"})


def _empty_shell(cls: type) -> type:
    """A class with the methods of ``cls``, every one returning nothing (R17).

    It takes any constructor arguments, so it can be created wherever ``cls``
    was. Inherited methods are included; data attributes are not.
    """

    def accept_anything(self: object, *args: Any, **kwargs: Any) -> None:
        pass

    namespace: dict[str, Any] = {
        "__module__": cls.__module__,
        "__qualname__": cls.__qualname__,
        "__doc__": cls.__doc__,
        "__init__": accept_anything,
    }
    # Base classes first, so a subclass's definition wins.
    for klass in reversed(cls.__mro__[:-1]):
        for name, attr in vars(klass).items():
            if name.startswith("__") and name.endswith("__") and name not in _SHELL_DUNDERS:
                continue
            stub = _stub(attr)
            if stub is not None:
                namespace[name] = stub
            else:
                namespace.pop(name, None)
    return type(cls.__name__, (), namespace)


def _stub(attr: Any) -> Any:
    if isinstance(attr, staticmethod):
        return staticmethod(_nothing_like(attr.__func__))
    if isinstance(attr, classmethod):
        return classmethod(_nothing_like(attr.__func__))
    if isinstance(attr, property | functools.cached_property):
        # Assigning to it must not fail where the original accepted it.
        writable = isinstance(attr, functools.cached_property) or attr.fset is not None
        return property(_nothing, _ignore if writable else None)
    if inspect.isfunction(attr):
        return _nothing_like(attr)
    return None


def _nothing(*args: Any, **kwargs: Any) -> None:
    return None


def _ignore(*args: Any, **kwargs: Any) -> None:
    pass


def _nothing_like(fn: Callable[..., Any]) -> Callable[..., Any]:
    """A function of the same kind as ``fn`` that returns nothing."""
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def nothing_coroutine(*args: Any, **kwargs: Any) -> None:
            return None

        return nothing_coroutine

    if inspect.isgeneratorfunction(fn):

        @functools.wraps(fn)
        def nothing_generator(*args: Any, **kwargs: Any) -> Iterator[Any]:
            yield from ()

        return nothing_generator

    if inspect.isasyncgenfunction(fn):

        @functools.wraps(fn)
        async def nothing_async_generator(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            return
            yield

        return nothing_async_generator

    # A new function each time: functools.wraps mutates the function it is
    # given, so wrapping the shared _nothing would rename every stub.
    @functools.wraps(fn)
    def nothing(*args: Any, **kwargs: Any) -> None:
        return None

    return nothing
