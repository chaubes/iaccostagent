# Changelog

All notable changes to IaCCostAgent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-18

First public release.

### Added

#### Core pipeline
- Terraform parsing — HCL files (via `python-hcl2`) and Terraform plan JSON; `count` and `for_each` are expanded into individual resource instances at parse time.
- Six-node LangGraph agent pipeline: `parse_terraform` → `estimate_costs` → `analyze_resources` → `detect_patterns` → `suggest_optimizations` → `generate_report`.
- Rule-based cost-pattern engine covering AWS, Azure, and GCP — oversized instances, older-generation VMs, suboptimal disk tiers (gp2→gp3, Standard_LRS→SSD, pd-standard→pd-balanced), unattached public IPs, NAT-gateway sprawl, deprecated database SKUs.
- LLM-powered optimization suggestions + executive summary (OpenAI or local Ollama), with automatic graceful fallback to rule-based output when the LLM is unreachable.

#### Cost backends (pluggable registry)
- `infracost` — recommended for production; full AWS/Azure/GCP coverage via the Infracost CLI.
- `openinfraquote` — fully-local AWS-only alternative for air-gapped use.
- `aws-pricing` — reference backend using AWS's public Price List JSON (covers `aws_instance`, `aws_ebs_volume`, `aws_nat_gateway`, `aws_db_instance`). 24-hour disk cache for the ~200-400 MB price list.
- `azure-retail` — reference backend using Azure's public Retail Prices API (VMs + managed disks with tier-SKU-aware pricing).
- `gcp-catalog` — reference backend using the Cloud Billing Catalog API (requires `GOOGLE_API_KEY`).
- Runtime yellow warning when a reference backend is selected; verified per-resource parity against Infracost within 0–5% for all covered types.

#### Interfaces
- CLI (`iaccostagent`): `analyze`, `estimate`, `diff`, `check-backend` (with `--verify` for end-to-end smoke test), `serve`, `version`.
- `--no-llm` flag for deterministic rule-based output without contacting any LLM.
- `--max-cost N --fail-on-exceed` for CI/CD policy gating.
- Git URL input with `--subdir` / `--before-subdir` / `--after-subdir` for remote Terraform analysis; shallow-clone + auto-cleanup.
- FastAPI server mode (`iaccostagent serve`) with `/api/v1/analyze`, `/estimate`, `/diff`, `/health`.
- Output formats: terminal (Rich), Markdown, JSON, GitHub PR comment.

#### Project scaffolding
- `SECURITY.md` with vulnerability disclosure policy (72h ack / 14d fix target).
- `CODE_OF_CONDUCT.md` referencing Contributor Covenant 2.1.
- GitHub issue templates (`bug_report`, `feature_request`, `new_backend`) and PR template.
- Reference GitHub Actions workflow for PR cost reviews.
- `docs/demo-with-llm.svg` and `docs/demo-no-llm.svg` — real pipeline output captured via Rich, with absolute-path sanitization.
- Full documentation: `README.md`, `docs/architecture.md`, `docs/adding-backends.md`, `docs/writing-patterns.md`, `docs/ci-cd-integration.md`.

### Tested against
- 120 unit + agent tests, 8 integration parity tests.
- Real public GitHub repos: `infracost/example-terraform` (AWS + Azure), `hashicorp/terraform-aws-vpc#examples/complete-vpc`, `futurice/terraform-examples`.

### Security & privacy
- Subprocess helper enforces `shell=False`, validates binaries on PATH, applies timeouts.
- No cloud credentials required; tool reads `.tf` files only, never modifies or applies.
- Documented data-egress matrix per backend. Infracost's FAQ linked with deep anchors for what is/isn't sent to their Cloud Pricing API.
- Self-hosted Infracost CPAPI path documented for fully air-gapped deployments.
