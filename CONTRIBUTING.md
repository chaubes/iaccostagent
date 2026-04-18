# Contributing to IaCCostAgent

Thanks for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/chaubes/iaccostagent.git
cd iaccostagent
uv sync --all-extras
```

## Local Prerequisites

For full testing you need at least one cost backend installed locally:

```bash
# Infracost (recommended — covers AWS, Azure, GCP)
brew install infracost
infracost auth login

# OR OpenInfraQuote (fully local, AWS only)
brew install openinfraquote/tap/oiq
```

Optional for agent tests:

```bash
# Ollama for local LLM
brew install ollama
ollama pull qwen3:8b
```

## Running Tests

```bash
make test-unit           # Fast, no network, no subprocess
make test-integration    # Needs infracost / oiq on PATH
make test-agent          # Graph compilation always; full pipeline needs Ollama
make test                # Everything
make test-coverage       # With coverage report
```

## Code Style

```bash
make lint        # ruff check
make format      # ruff format
make typecheck   # mypy strict
```

All three must pass before opening a PR. CI enforces the same.

## Adding a New Cost Backend

1. Subclass `CostBackend` in `src/iaccostagent/backends/`.
2. Implement `async estimate(terraform_path: str) -> CostEstimate`.
3. Register it in `cli/app.py` and `agent/nodes/estimate_costs.py`.
4. Add unit tests with a recorded fixture JSON under `tests/fixtures/cost_output/`.

See `docs/adding-backends.md` for the full guide.

## Adding a New Cost Pattern

Add a rule to `patterns/rules.py` and a test case to `tests/unit/test_patterns.py`. See `docs/writing-patterns.md`.

## Pull Requests

- Keep PRs focused and small where possible.
- Include tests for new behavior.
- Update `CHANGELOG.md` under an "Unreleased" section.
- Ensure `make lint`, `make format --check`, `make typecheck`, and `make test-unit` all pass locally.
