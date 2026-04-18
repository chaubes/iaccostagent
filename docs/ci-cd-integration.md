# CI/CD Integration

## GitHub Actions — PR cost review

Posts an IaCCostAgent analysis as a PR comment and fails the check if the estimated monthly cost exceeds a threshold.

```yaml
name: Infrastructure Cost Review
on:
  pull_request:
    paths:
      - 'infrastructure/**'

jobs:
  cost-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - uses: infracost/actions/setup@v3
        with:
          api-key: ${{ secrets.INFRACOST_API_KEY }}
      - uses: astral-sh/setup-uv@v4
      - run: pip install iaccostagent
      - name: Analyze cost impact
        run: |
          iaccostagent analyze ./infrastructure \
            --backend infracost \
            --llm openai/gpt-4o-mini \
            --format github-comment \
            --output cost-comment.md \
            --max-cost 5000 \
            --fail-on-exceed
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      - uses: peter-evans/create-or-update-comment@v4
        with:
          issue-number: ${{ github.event.pull_request.number }}
          body-path: cost-comment.md
```

## Scheduled weekly audit

Runs a Monday-morning analysis on the default branch and opens an issue if anything exceeds policy.

```yaml
name: Weekly Cost Audit
on:
  schedule:
    - cron: '0 9 * * 1'

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: pip install iaccostagent
      - run: |
          iaccostagent analyze ./infrastructure \
            --backend infracost \
            --format markdown \
            --output weekly-report.md
        env:
          INFRACOST_API_KEY: ${{ secrets.INFRACOST_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      - name: Attach report as artifact
        uses: actions/upload-artifact@v4
        with:
          name: weekly-cost-report
          path: weekly-report.md
```

## Local pre-commit hook

Block commits that push the estimated cost past a threshold.

```bash
#!/usr/bin/env bash
# .git/hooks/pre-commit (chmod +x)
set -e

iaccostagent analyze ./infrastructure --max-cost 2000 --fail-on-exceed --format json >/tmp/cost.json
```

## Policy enforcement with OPA

IaCCostAgent's JSON output is consumable by OPA or custom policy tools:

```bash
iaccostagent analyze ./infrastructure --format json > estimate.json
opa eval -d policy.rego -i estimate.json "data.cost.deny"
```

A minimal Rego policy:

```rego
package cost

deny[msg] {
  input.total_monthly_cost > 5000
  msg := sprintf("Monthly cost $%.2f exceeds budget", [input.total_monthly_cost])
}

deny[msg] {
  some i
  opt := input.optimizations[i]
  opt.estimated_monthly_savings >= 500
  opt.risk == "low"
  msg := sprintf("Missed low-risk savings: %s", [opt.title])
}
```
