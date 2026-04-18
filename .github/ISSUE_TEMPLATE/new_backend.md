---
name: New backend contribution
about: Propose or discuss adding a new cost backend
title: "[BACKEND] "
labels: enhancement, backend
---

## Backend name

What should `--backend <name>` be called?

## Provider / data source

Which cloud or pricing source does it wrap?
(e.g. a specific cloud provider's native API, a local CSV, another third-party tool)

## Coverage scope

Which Terraform resource types will you cover initially?
(Be explicit — full coverage is never expected for a first PR.)

## Authentication / prerequisites

- API key? Environment variable?
- External binary? CLI tool?
- Fully local (no network)?

## Integration notes

Anything unusual about the data source — rate limits, response shape, pagination, etc.

## Checklist (before opening the PR)

- [ ] Read [docs/adding-backends.md](../../docs/adding-backends.md)
- [ ] Subclass `CostBackend` and register with `@register_backend("<name>")`
- [ ] Add a unit test under `tests/unit/` using respx or subprocess mocks
- [ ] Add an integration test under `tests/integration/` (skip-when-unavailable)
- [ ] Update the "Supported Backends" table in README.md
- [ ] Update `INSTALL_HINTS` in `src/iaccostagent/cli/app.py`
