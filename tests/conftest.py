from collections.abc import Iterator

import pytest

from .backend import Backend, running


@pytest.fixture
def backend() -> Iterator[Backend]:
    with running() as backend:
        yield backend
