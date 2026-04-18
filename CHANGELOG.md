# Changelog

All notable changes to IaCCostAgent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-17

### Added

- Initial release
- Terraform HCL and plan JSON parsing
- Infracost and OpenInfraQuote cost estimation backends
- LangGraph agent pipeline with six nodes (parse, estimate, analyze, detect, suggest, report)
- Rule-based cost pattern detection (oversized instances, old-generation, gp2 vs gp3, NAT gateway sprawl)
- LLM-powered optimization suggestions and executive summaries (Ollama + OpenAI)
- CLI commands: analyze, estimate, diff, check-backend, serve, version
- Output formats: terminal (Rich), markdown, JSON, GitHub comment
- FastAPI server mode
- GitHub Actions CI template for PR cost reviews
- `--max-cost` and `--fail-on-exceed` flags for CI/CD policy enforcement
