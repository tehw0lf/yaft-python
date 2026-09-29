"""Loads the conformance case files.

The cases live in ``tests/suite``, fetched by ``scripts/fetch-conformance.sh``
from the version pinned in ``conformance.lock``. They are not checked in: the
lock file plus its checksum is what makes a suite bump a reviewable one-line
diff, and a committed copy would drift from the tag it claims to be.
"""

import json
from pathlib import Path
from typing import Any, NoReturn

from yaft import Feature

CASES_DIR = Path(__file__).parent.parent / "suite" / "cases"

# The case-file format versions this adapter implements. A file in any other
# format may carry a field this adapter never reads, which would leave a rule
# silently unenforced, so it is rejected instead.
FORMATS = {"evaluation": 1, "decorator": 1, "mapping": 4}

Case = dict[str, Any]


def load(suite: str) -> list[Case]:
    path = CASES_DIR / f"{suite}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Conformance cases missing at {path}.\n"
            "Run scripts/fetch-conformance.sh before the tests; CI does this first."
        )
    file = json.loads(path.read_text(encoding="utf-8"))
    if file["suite"] != suite:
        raise ValueError(f'{path} declares suite "{file["suite"]}", expected "{suite}"')
    if file["version"] != FORMATS[suite]:
        raise ValueError(
            f"{path} is format version {file['version']}, but this adapter implements "
            f"version {FORMATS[suite]}. Extend the adapter to the new format."
        )
    cases: list[Case] = file["cases"]
    return cases


def title(case: Case) -> str:
    """Names a case for the test output, so a failure points at a rule."""
    return f"{case['name']} [{', '.join(case['rules'])}]"


def unsupported(kind: str, value: object, case: Case) -> NoReturn:
    """Rejects a value the adapter does not know how to handle.

    A case whose ``target``, ``toggle`` or ``expected`` this adapter has never
    seen is a rule nothing enforces here. Skipping it would leave the suite
    looking green while a requirement goes unchecked.
    """
    raise AssertionError(
        f'Case "{case["name"]}" uses {kind} "{value}", which this adapter does not '
        "implement. The conformance suite has gained a case this port does not cover "
        "yet -- extend the adapter rather than skipping the case."
    )


def as_record(feature: Feature) -> dict[str, Any]:
    """A feature in the suite's spelling, to compare with ``expected``."""
    return {
        "key": feature.key,
        "value": feature.value,
        "activeAt": feature.active_at,
        "disabledAt": feature.disabled_at,
        "tags": list(feature.tags),
    }
