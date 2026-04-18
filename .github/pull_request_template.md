<!-- Thanks for contributing! A PR description below makes it much easier to review. -->

## Summary

<!-- What does this PR change, in 1-3 bullets? -->

## Motivation

<!-- Why is this change needed? Link to any relevant issue. -->

Fixes #

## Test plan

- [ ] `make test-unit` passes
- [ ] `make lint` passes (`uv run ruff check src/ tests/`)
- [ ] `make typecheck` passes (`uv run mypy src/iaccostagent`)
- [ ] New behavior covered by a test (unit or agent)
- [ ] For new backends: mock unit test added to `tests/unit/`
- [ ] For new patterns: test case added to `tests/unit/test_patterns*.py`

## Documentation

- [ ] `CHANGELOG.md` updated (under an `Unreleased` section) if user-visible
- [ ] `README.md` updated if CLI flags, backends, or user-facing behavior changed
- [ ] `docs/` updated if architecture, extension points, or CI/CD guidance changed

## Safety checklist

- [ ] No credentials, API keys, or internal URLs committed
- [ ] `.env` and any personal config not included
- [ ] External network calls documented (what / why / when)
