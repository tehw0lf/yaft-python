"""The API provider: what the conformance suite cannot see over HTTP."""

import logging
import socket
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler

import pytest

from yaft import APIFeatureProvider, FeatureProvider, RefreshError, __version__

from .backend import GROUP, Backend, Route, answer

FEATURES = f"/features/{GROUP}"
HASH = f"/collectionHash/{GROUP}"


def toggle(name: str, value: str = "true", **fields: str) -> dict[str, str]:
    return {"key": f"{GROUP}|{name}", "value": value, **fields}


def test_is_a_feature_provider() -> None:
    assert isinstance(APIFeatureProvider("http://localhost", GROUP), FeatureProvider)


@pytest.mark.parametrize(
    "base_url",
    ["ftp://host", "localhost:8080", "http://", "http://host/?a=b", "http://host/#top"],
)
def test_rejects_a_base_url_it_cannot_use(base_url: str) -> None:
    with pytest.raises(ValueError, match="base URL"):
        APIFeatureProvider(base_url, GROUP)


@pytest.mark.parametrize(
    "group",
    [
        "",
        "not-a-uuid",
        GROUP.replace("-", ""),
        "{" + GROUP + "}",
        "urn:uuid:" + GROUP,
        GROUP + "/../x",
    ],
)
def test_accepts_only_the_canonical_uuid_form(group: str) -> None:
    # The UUID goes into the request path.
    with pytest.raises(ValueError, match="not a UUID"):
        APIFeatureProvider("http://localhost", group)


def test_rejects_limits_that_are_not_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        APIFeatureProvider("http://localhost", GROUP, timeout=0)
    with pytest.raises(ValueError, match="positive"):
        APIFeatureProvider("http://localhost", GROUP, max_body_bytes=0)


def test_fetches_nothing_before_the_first_refresh(backend: Backend) -> None:
    backend.serve("h1", {"toggles": [toggle("a")]})
    provider = APIFeatureProvider(backend.url, GROUP)
    assert not provider.is_enabled("a")
    assert not backend.hits


def test_fetches_the_group_only_when_its_hash_changed(backend: Backend) -> None:
    backend.serve("h1", {"toggles": [toggle("a")]})
    provider = APIFeatureProvider(backend.url + "/", GROUP.upper())
    assert provider.refresh()
    assert not provider.refresh()
    assert backend.hits == {HASH: 2, FEATURES: 1}

    backend.serve("h2", {"toggles": [toggle("a", "false")]})
    assert provider.refresh()
    assert not provider.is_enabled("a")


def test_names_itself_in_the_user_agent(backend: Backend) -> None:
    # Cloudflare answers urllib's default "Python-urllib/3.x" with 403.
    backend.serve("h1", {"toggles": [toggle("a")]})
    APIFeatureProvider(backend.url, GROUP).refresh()
    assert backend.user_agents == {f"yaft-python/{__version__}"}


def test_answers_by_name_or_by_full_key(backend: Backend) -> None:
    backend.serve("h1", {"toggles": [toggle("a"), {"key": "plain", "value": "true"}]})
    provider = APIFeatureProvider(backend.url, GROUP)
    provider.refresh()
    assert provider.is_enabled("a")
    assert provider.is_enabled(f"{GROUP}|a")
    # A key as given wins, and a full key is not looked up a second time.
    assert provider.is_enabled("plain")
    assert not provider.is_enabled(f"{GROUP}|missing")
    assert not provider.is_enabled("missing")


def test_evaluates_against_its_clock(backend: Backend) -> None:
    now = datetime(2026, 9, 30, 11, 59, tzinfo=UTC)
    backend.serve("h1", {"toggles": [toggle("a", activeAt="2026-09-30T12:00:00Z")]})
    provider = APIFeatureProvider(backend.url, GROUP, clock=lambda: now)
    provider.refresh()
    assert not provider.is_enabled("a")
    now = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    assert provider.is_enabled("a")


@pytest.mark.parametrize(
    ("route", "message"),
    [
        (answer(404, {"error": "not found"}), "answered 404"),
        (answer(500, b"oops"), "answered 500"),
        (answer(204, b""), "answered 204"),
        # Not followed: the target of a redirect is not the backend.
        (answer(302, b"", {"Location": "/elsewhere"}), "answered 302"),
        (answer(200, b"<html>login</html>"), "does not parse"),
        (answer(200, b"\xff\xfe"), "does not parse"),
        (answer(200, b"[" * 100_000), "does not parse"),
        (answer(200, b"x" * 300_000), "more than 200000 bytes"),
    ],
)
def test_a_failed_fetch_raises_and_keeps_the_data(
    backend: Backend, route: Route, message: str
) -> None:
    backend.serve("h1", {"toggles": [toggle("a")]})
    provider = APIFeatureProvider(backend.url, GROUP, max_body_bytes=200_000)
    provider.refresh()

    backend.serve("h2", None)
    backend.routes[FEATURES] = route
    with pytest.raises(RefreshError, match=message):
        provider.refresh()
    assert provider.is_enabled("a")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"collectionHash": ""},
        {"collectionHash": 7},
        # By presence, like every field (R23): an empty collectionHash does not
        # fall through to value.
        {"collectionHash": "", "value": "h1"},
        None,
        [],
    ],
)
def test_a_missing_hash_fails_the_refresh(backend: Backend, body: object) -> None:
    backend.routes[HASH] = answer(200, body)
    provider = APIFeatureProvider(backend.url, GROUP)
    with pytest.raises(RefreshError, match="no collectionHash"):
        provider.refresh()
    assert FEATURES not in backend.hits


def test_reads_the_hash_from_value_when_collection_hash_is_absent(backend: Backend) -> None:
    backend.serve("unused", {"toggles": [toggle("a")]})
    backend.routes[HASH] = answer(200, {"value": "h1"})
    provider = APIFeatureProvider(backend.url, GROUP)
    assert provider.refresh()
    assert not provider.refresh()


def test_an_unreachable_backend_raises() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    provider = APIFeatureProvider(f"http://127.0.0.1:{port}", GROUP)
    with pytest.raises(RefreshError, match=r"GET http://127\.0\.0\.1"):
        provider.refresh()


def test_the_timeout_covers_a_body_that_trickles_in(backend: Backend) -> None:
    def trickle(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Length", "100")
        handler.end_headers()
        for _ in range(100):
            handler.wfile.write(b" ")
            handler.wfile.flush()
            time.sleep(0.05)

    backend.routes[HASH] = trickle
    provider = APIFeatureProvider(backend.url, GROUP, timeout=0.5)
    started = time.monotonic()
    with pytest.raises(RefreshError, match="took longer"):
        provider.refresh()
    assert time.monotonic() - started < 2


def test_refresh_quietly_logs_instead_of_raising(
    backend: Backend, caplog: pytest.LogCaptureFixture
) -> None:
    provider = APIFeatureProvider(backend.url, GROUP)
    with caplog.at_level(logging.WARNING, logger="yaft"):
        assert not provider.refresh_quietly()
    assert "answered 404" in caplog.text

    backend.serve("h1", {"toggles": [toggle("a")]})
    assert provider.refresh_quietly()
    assert provider.is_enabled("a")
