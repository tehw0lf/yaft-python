"""A provider that loads one toggle group from a YaFT backend (SPEC sections 5-7)."""

import json
import logging
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from urllib.parse import urlsplit

from .evaluate import Clock, evaluate, system_clock
from .model import Feature
from .providers import LocalFeatureProvider

log = logging.getLogger("yaft")

# urllib's own "Python-urllib/3.x" is on the block lists of common bot
# filters: Cloudflare answers it with 403, so a backend behind Cloudflare
# looks like one that refuses every refresh.
try:
    _USER_AGENT = f"yaft-python/{version('yaft')}"
except PackageNotFoundError:  # pragma: no cover - only without an installed distribution
    _USER_AGENT = "yaft-python"


class RefreshError(Exception):
    """A refresh failed; the provider still holds the data it had before."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Turns a redirect into an error instead of following it.

    The backend never redirects, so a redirect comes from something in front of
    it -- a login page, a captive portal -- whose target is not a toggle group.
    """

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class APIFeatureProvider:
    """A feature-shape provider over one toggle group of a YaFT backend.

    :meth:`refresh` asks ``GET /collectionHash/{uuid}`` whether the group
    changed and only then fetches ``GET /features/{uuid}``. Evaluation is local,
    against ``clock`` (R26): a scheduled toggle flips at its exact instant, not
    when the backend's cron job gets to it.

    Nothing is fetched until the first refresh; until then every feature is
    off. A failed refresh raises :class:`RefreshError` and keeps the previous
    data, so a backend outage does not switch everything off (R30). Refreshing
    on a schedule is left to the application, for example::

        def refresh_every_minute() -> None:
            while True:
                time.sleep(60)
                provider.refresh_quietly()

        threading.Thread(target=refresh_every_minute, daemon=True).start()

    Safe for use from several threads.
    """

    def __init__(
        self,
        base_url: str,
        group: str,
        *,
        timeout: float = 5.0,
        max_body_bytes: int = 1 << 20,
        clock: Clock = system_clock,
        opener: urllib.request.OpenerDirector | None = None,
    ):
        """Prepares a provider for ``group`` on the backend at ``base_url``.

        ``base_url`` must be http or https, without query or fragment.
        ``timeout`` bounds each request, from connecting until the last byte of
        the body; a read already waiting may overrun it by at most ``timeout``.
        ``max_body_bytes`` keeps a misbehaving endpoint from exhausting memory.
        ``opener`` replaces the default one, for example to add a TLS context;
        the default follows no redirects and honours the proxy environment
        variables, like everything built on :mod:`urllib.request`.
        """
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"base URL must be http or https: {base_url!r}")
        if parts.query or parts.fragment:
            raise ValueError(f"base URL must not carry a query or fragment: {base_url!r}")
        # The UUID goes into the request path, so only the canonical 8-4-4-4-12
        # form is accepted. uuid.UUID alone would also take braces, a "urn:"
        # prefix or no hyphens.
        try:
            canonical = str(uuid.UUID(group))
        except ValueError:
            canonical = None
        if canonical is None or canonical != group.lower():
            raise ValueError(f"group is not a UUID: {group!r}")
        if timeout <= 0 or max_body_bytes <= 0:
            raise ValueError("timeout and max_body_bytes must be positive")

        root = base_url.rstrip("/")
        self._features_url = f"{root}/features/{canonical}"
        self._hash_url = f"{root}/collectionHash/{canonical}"
        self._key_prefix = f"{canonical}|"
        self._timeout = timeout
        self._max_body_bytes = max_body_bytes
        self._opener = opener or urllib.request.build_opener(_NoRedirect)
        self._clock = clock
        self._local = LocalFeatureProvider(clock=clock)
        self._lock = threading.Lock()
        self._hash = ""

    @property
    def data(self) -> Mapping[str, Feature]:
        """The features of the last successful refresh by key, read-only."""
        return self._local.data

    def refresh(self) -> bool:
        """Fetches the group if it changed since the last successful refresh.

        Returns ``True`` if new data was loaded and ``False`` if the group is
        unchanged. Raises :class:`RefreshError` if the backend cannot be reached
        or answers with something that is not a toggle group (R32); the
        previous data then stays in place.
        """
        with self._lock:
            hash_ = _hash_of(self._get(self._hash_url))
            if hash_ is None:
                raise RefreshError(f"GET {self._hash_url} sent no collectionHash")
            if hash_ == self._hash:
                return False
            try:
                self._local.load(self._get(self._features_url))
            except ValueError as error:
                raise RefreshError(f"GET {self._features_url}: {error}") from error
            # Recorded only after the group loaded, so a failed fetch is
            # retried (R30).
            self._hash = hash_
            return True

    def refresh_quietly(self) -> bool:
        """:meth:`refresh` for a scheduler: logs a failure instead of raising it."""
        try:
            return self.refresh()
        except RefreshError as error:
            log.warning("refresh failed; keeping the previous data: %s", error)
            return False

    def is_enabled(self, key: str) -> bool:
        """Answers for a toggle of this group, by its name or its ``uuid|name`` key.

        The key is looked up as given first, then as a name within the group,
        so a toggle can be named without knowing the group's UUID.
        """
        data = self._local.data
        feature = data.get(key)
        if feature is None and not key.startswith(self._key_prefix):
            feature = data.get(self._key_prefix + key)
        return evaluate(feature, self._clock())

    def _get(self, url: str) -> object:
        request = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT}
        )
        deadline = time.monotonic() + self._timeout
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200:
                    raise RefreshError(f"GET {url} answered {response.status}")
                body = bytearray()
                # read1 returns after one read from the socket, so the deadline
                # is checked while a slow server trickles the body in; read(n)
                # would wait for all n bytes.
                while chunk := response.read1(64 * 1024):
                    body += chunk
                    if len(body) > self._max_body_bytes:
                        raise RefreshError(f"GET {url} sent more than {self._max_body_bytes} bytes")
                    if time.monotonic() > deadline:
                        raise RefreshError(f"GET {url} took longer than {self._timeout} s")
        except urllib.error.HTTPError as error:
            # Raised for 3xx (no redirects) and every 4xx and 5xx.
            error.close()
            raise RefreshError(f"GET {url} answered {error.code}") from error
        except (OSError, ValueError) as error:
            # URLError, timeouts, refused connections and malformed responses
            # are all OSError; http.client raises some ValueErrors of its own.
            raise RefreshError(f"GET {url}: {error}") from error
        try:
            return json.loads(body)
        except (ValueError, RecursionError) as error:
            # RecursionError: a body of nothing but "[" nests deeper than the
            # parser recurses, well within max_body_bytes.
            raise RefreshError(f"GET {url} sent a body that does not parse: {error}") from error


def _hash_of(response: object) -> str | None:
    """Reads the hash by presence, as the other ports do: collectionHash, else value."""
    if not isinstance(response, Mapping):
        return None
    value = response["collectionHash"] if "collectionHash" in response else response.get("value")
    return value if isinstance(value, str) and value != "" else None
