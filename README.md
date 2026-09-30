# YaFT for Python

<div align="center">
  <img src="./logo.svg" alt="YaFT Logo" width="140">
</div>

---

Feature toggles for functions, methods and classes in Python, following the
same rules as [`@tehw0lf/yaft`](https://github.com/tehw0lf/yaft-ts),
[`de.tehwolf:yaft`](https://github.com/tehw0lf/yaft-java) and
[`yaft-go`](https://github.com/tehw0lf/yaft-go). It passes every case of
[yaft-conformance](https://github.com/tehw0lf/yaft-conformance), is fully
typed, and has no runtime dependencies. Python 3.11 or later.

---

## Installation

```bash
pip install yaft
# or
uv add yaft
```

```python
from yaft import feature_toggle, set_provider
```

## Providers

Set one provider at startup:

```python
from yaft import Feature, LocalFeatureProvider, set_provider

set_provider(LocalFeatureProvider({"newCheckout": Feature(key="newCheckout", value="true")}))
```

| Provider | Data | Time bounds |
|---|---|---|
| `LocalFeatureProvider` | full `Feature` records | yes: `active_at`, `disabled_at` |
| `LocalBooleanProvider` | `{"myToggle": True}` | none, by design |
| `APIFeatureProvider` | one group of a YaFT backend | yes, evaluated locally |

Both read a JSON file with `from_file(path)`. `LocalFeatureProvider` takes a
YaFT backend response (`{"toggles": [...]}`, in either field spelling) or
features keyed by name, the format yaft-ts reads:

```json
{
  "newCheckout": { "value": "true", "activeAt": "2026-10-01T00:00:00Z", "disabledAt": "" }
}
```

A missing or unreadable file raises instead of starting with everything off.
`load(response)` replaces the data with a newer backend response, all or
nothing: a body that is not a toggle group raises `ValueError` and the old
data stays.

### From a YaFT backend

`APIFeatureProvider` loads one toggle group over HTTP, with `urllib` and
nothing else:

```python
import threading
import time

from yaft import APIFeatureProvider, set_provider

provider = APIFeatureProvider("https://yaft.example.com", "896ea308-382f-46b0-bc59-d93a28013633")
provider.refresh()  # raises RefreshError if the backend cannot be reached
set_provider(provider)


def refresh_every_minute() -> None:
    while True:
        time.sleep(60)
        provider.refresh_quietly()  # logs a failure instead of raising it


threading.Thread(target=refresh_every_minute, daemon=True).start()
```

Nothing is fetched until the first `refresh()`; until then every feature is
off. `refresh()` asks `/collectionHash/{uuid}` first and fetches
`/features/{uuid}` only when the group changed. It returns `True` for new data
and `False` for none, and raises `RefreshError` when the backend is down or
answers with something that is not a toggle group. The previous data then
stays: an outage does not switch everything off. An empty group does, because
that is what deleting its last toggle looks like.

A toggle is found by its name (`"newCheckout"`) or its full key
(`"896ea308-…|newCheckout"`). Time bounds are evaluated locally, so a
scheduled toggle flips at its instant, not when the backend's cron job runs.
Keyword arguments: `timeout` (seconds per request, default 5),
`max_body_bytes` (default 1 MiB), `clock`, and `opener` for a custom
`urllib.request.OpenerDirector`, for example one with its own TLS context.
The default opener follows no redirects.

### Your own provider

Any object with an `is_enabled(key: str) -> bool` method is a provider, for
example one that reads environment variables.

### Evaluation rules

A feature is on when all of these hold:

- `value` is exactly `"true"`. `"True"`, `"1"` and `""` are off.
- `active_at` has been reached, if set. At exactly `active_at` it is on.
- `disabled_at` has not been reached, if set. At exactly `disabled_at` it is off.

A missing feature is off. Only RFC 3339 with an offset is a valid bound
(`2026-09-18T15:00:00Z`, `2026-09-18T17:00:00+02:00`); an unset or invalid one
is ignored with a warning on the `yaft` logger, never raised. The clock is a
parameter, so tests can pin the time:

```python
from datetime import UTC, datetime

provider = LocalFeatureProvider(data, clock=lambda: datetime(2026, 9, 18, 12, tzinfo=UTC))
```

The boolean shape has no time logic, and only the boolean `True` is on. A
value that is not a boolean, such as the string `"true"`, is dropped when the
data is loaded.

## Toggling code

### Functions and methods: evaluated on every call

```python
class Checkout:
    def classic_total(self, cart: list[int]) -> int:
        return sum(cart)

    @feature_toggle("newPricing", fallback=classic_total)
    def total(self, cart: list[int]) -> int:
        return sum(cart) - self.discount(cart)
```

Off, the fallback runs with the same arguments and the same `self`. Without a
fallback, an off call returns *nothing*:

| Decorated | Off, without a fallback |
|---|---|
| function or method | `None` |
| `async def` | a coroutine that resolves to `None`, so `await` still works |
| generator | an empty iterator, so a `for` loop still works |
| async generator | an empty async iterator |

A synchronous fallback on an `async def` is fine; its result is returned from
the coroutine. `staticmethod` and `classmethod` can be decorated too, with
`@feature_toggle` on the outside.

### Classes: decided once

```python
@feature_toggle("newCheckout", fallback=ClassicCheckout)
class NewCheckout: ...
```

The toggle is read **once**, when the class is decorated; changing it later
does not swap the class. Without a fallback, an off class becomes an *empty
shell*: it takes any constructor arguments, and every method, inherited ones
included, returns nothing of its own kind (see the table above). Properties
read as `None`. `__call__` and the context manager methods are kept; other
dunder methods and data attributes are not.

### When a toggle is read

| | Evaluated |
|---|---|
| class | **once**, when decorated |
| function or method | on **every call** |
| `async def`, generator | on every call, when the coroutine or generator starts |

### Fail fast

`feature_toggle` raises `ProviderNotSetError` ("FeatureToggleProvider not
set") when it is applied, not on the first call, if no provider is set. A
fallback of the wrong kind, such as a class for a function, raises `TypeError`
at the same point. A misconfiguration shows at startup.

## Conformance

`conformance.lock` pins a release of the suite by version and checksum.
`scripts/fetch-conformance.sh` fetches and verifies it into `tests/suite`, and
`pytest` then runs every case next to this package's own tests.

## Development

```bash
uv sync
uv run ruff check && uv run ruff format --check && uv run mypy
./scripts/fetch-conformance.sh && uv run --python 3.11 pytest && uv run --python 3.14 pytest
uv build
```

## License

MIT
