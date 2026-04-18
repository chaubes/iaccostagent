# Security Policy

## Supported Versions

During the 0.x release series, only the latest minor version receives security
updates. Once 1.0 ships, the policy will move to supporting the latest two
minor versions.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |

## Reporting a Vulnerability

**Please do not file a public GitHub issue for security vulnerabilities.**
Responsible disclosure helps us fix issues before they can be exploited.

To report a security issue, email **saurabh.chaubey17@gmail.com** with
`SECURITY: iaccostagent` in the subject line. Please include:

- A description of the vulnerability and its impact
- Steps to reproduce (minimal example preferred)
- Affected version / commit hash
- (Optional) A proposed fix or workaround

We aim to:

- Acknowledge receipt within **72 hours**
- Provide an initial assessment within **7 days**
- Release a fix within **14 days** for confirmed issues of moderate severity or higher

You will be credited in the release notes unless you prefer to remain anonymous.

## Scope

This policy covers vulnerabilities in:

- The iaccostagent source code in this repository
- The PyPI artifacts published under the `iaccostagent` package name (once released)
- The example GitHub Actions workflows published under `.github/workflows/`

### Out of scope

- Vulnerabilities in **third-party dependencies** (please report those to the
  respective maintainers: `langgraph`, `langchain-*`, `pydantic`, `httpx`,
  `typer`, `rich`, etc.). We will update our pin to a patched version once
  upstream releases a fix.
- Issues in the **external cost-estimation binaries** this tool wraps
  (Infracost CLI, OpenInfraQuote CLI) — report those to their maintainers.
- Issues in **cloud-provider pricing APIs** or **LLM provider APIs** — those
  belong to AWS / Azure / GCP / Infracost / OpenAI / Anthropic / Ollama etc.
- Vulnerabilities in **user-supplied Terraform code** being analyzed. This
  tool is read-only against user input; it does not execute Terraform.
- Issues that require **physical access** to the user's machine or shared
  access to the `.env` file (that's a local credential-handling issue, not a
  vulnerability in this tool).

## What we consider a vulnerability

In scope:

- Code execution via crafted Terraform or plan JSON input
- Credential leakage (e.g., API keys accidentally written to logs, stdout, or
  cached files)
- Subprocess injection via unsanitised arguments passed to the cost backends
- Path traversal in the git-URL clone handler or `--subdir` flag
- Any issue that causes iaccostagent to send data outside the boundaries
  documented in the [Data Handling & Privacy section](README.md#data-handling--privacy)
  of the README

Not in scope:

- Denial-of-service via extremely large `.tf` inputs (out of band for a
  pre-deployment cost advisor)
- Social-engineering angles that require tricking the user into running a
  custom backend they wrote themselves

Thanks for helping keep iaccostagent safe.
