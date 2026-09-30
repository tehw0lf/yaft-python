# CLAUDE.md

Python port of YaFT (PyPI `yaft`, import `yaft`). The normative rules are
`yaft-conformance/SPEC.md` (fetched to `tests/suite/SPEC.md`); the TypeScript,
Java and Go ports are references for behaviour, not for API shape.

## Layout

- `src/yaft/model.py` — `Feature` (frozen dataclass, snake_case fields)
- `src/yaft/evaluate.py` — `Clock`, `evaluate`, `parse_timestamp` (R3–R13,
  R27, R28). `datetime` does the calendar checks; only the offset minutes are
  checked by hand. The pattern needs `re.ASCII` and `fullmatch`.
- `src/yaft/mapping.py` — response normalisation (R22–R25, R29, R30). A key or
  value that is not a string is not set: no coercion, JSON booleans belong in
  the boolean shape.
- `src/yaft/providers.py` — `FeatureProvider` protocol, local providers;
  `LocalFeatureProvider.load` is the all-or-nothing refresh (R30)
- `src/yaft/api.py` — `APIFeatureProvider` over `urllib` (R26, R30, R32):
  hash first, group only on change, hash recorded only after the group
  loaded; `refresh()` raises `RefreshError`, `refresh_quietly()` logs. No
  redirects; a deadline checked between `read1` calls bounds a trickling body
- `src/yaft/toggle.py` — `feature_toggle`, `set_provider`; functions per call,
  classes once, empty shell for an off class without fallback (R14–R19)
- `tests/backend.py` — a local stand-in backend; the refresh cases of the
  suite run through `APIFeatureProvider` against it
- `tests/conformance/` — the suite adapter; unknown case values and unknown
  case-file format versions must fail, never be skipped
- `tests/test_*.py` — what the suite cannot see (generators, static/class
  methods, the shell, Python's parsing traps)

## Constraints

- No runtime dependencies.
- `requires-python = ">=3.11"`; CI runs the tests on 3.11 and 3.14.
- PyPI: `.github/workflows/publish.yml` uploads the `build` artifact of a
  push to `main` via Trusted Publishing (environment `pypi`). PyPI never
  replaces a file, so a merge without a version bump fails that job.
- Bump the patch version in `pyproject.toml` on every PR and run `uv lock`.
- Mutation-check new rules: `PYTHONDONTWRITEBYTECODE=1`, or a same-length edit
  within the same second keeps running the stale `.pyc`.

## Pre-commit validation

```bash
uv sync && uv run ruff check && uv run ruff format --check && uv run mypy \
  && ./scripts/fetch-conformance.sh && uv run --python 3.11 pytest \
  && uv run --python 3.14 pytest && uv build
```
