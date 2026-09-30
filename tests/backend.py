"""A stand-in YaFT backend on a local port, for the API provider's tests."""

import json
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GROUP = "896ea308-382f-46b0-bc59-d93a28013633"

# Writes the answer to a request; the default ones are built by serve().
Route = Callable[[BaseHTTPRequestHandler], None]


class Backend:
    """Canned answers per path, and a count of the requests per path."""

    def __init__(self, url: str):
        self.url = url
        self.routes: dict[str, Route] = {}
        self.hits: Counter[str] = Counter()
        self.user_agents: set[str] = set()

    def serve(self, hash_: str, features: object) -> None:
        """Answers the group's hash with ``hash_`` and its features with ``features``."""
        self.routes[f"/collectionHash/{GROUP}"] = answer(200, {"collectionHash": hash_})
        self.routes[f"/features/{GROUP}"] = answer(200, features)


def answer(status: int, body: object, headers: dict[str, str] | None = None) -> Route:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()

    def route(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(status)
        for name, value in {"Content-Type": "application/json", **(headers or {})}.items():
            handler.send_header(name, value)
        handler.send_header("Content-Length", str(len(raw)))
        handler.end_headers()
        handler.wfile.write(raw)

    return route


@contextmanager
def running() -> Iterator[Backend]:
    backend: Backend

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            backend.hits[self.path] += 1
            backend.user_agents.add(self.headers.get("User-Agent", ""))
            route = backend.routes.get(self.path, answer(404, {"error": "not found"}))
            route(self)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    backend = Backend(f"http://127.0.0.1:{server.server_port}")
    # The default poll interval of 0.5 s would add that much to every shutdown.
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    try:
        yield backend
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
