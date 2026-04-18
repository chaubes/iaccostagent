"""Output formatters for IaCCostAgent analysis reports."""

from rich.console import Console
from rich.table import Table

from iaccostagent.models.schemas import CostAnalysisReport, OptimizationRisk

console = Console()

RISK_COLORS = {
    OptimizationRisk.LOW: "green",
    OptimizationRisk.MEDIUM: "yellow",
    OptimizationRisk.HIGH: "red",
}


# ── Terminal (Rich) ────────────────────────────────────────────────


def format_terminal(report: CostAnalysisReport) -> None:
    """Render the report to the terminal using Rich."""
    console.print()
    title = f"IaCCostAgent Report — {report.provider.value.upper() if report.provider else 'Multi-cloud'}"
    console.rule(f"[bold]{title}")
    console.print()

    console.print(f"[bold]Project:[/bold] {report.project_path}")
    console.print(f"[bold]Backend:[/bold] {report.backend_used}")
    if report.region:
        console.print(f"[bold]Region:[/bold] {report.region}")
    console.print()

    console.print(
        f"[bold]Total monthly cost:[/bold] ${report.total_monthly_cost:,.2f}  |  "
        f"[bold]Resources:[/bold] {report.resource_count}  |  "
        f"[bold]Potential savings:[/bold] ${report.total_potential_savings:,.2f} "
        f"({report.savings_percentage:.1f}%)"
    )
    console.print()

    if report.executive_summary:
        console.print(f"[bold]Summary:[/bold] {report.executive_summary}")
        console.print()

    if report.top_cost_drivers:
        drivers = Table(title="Top Cost Drivers")
        drivers.add_column("Resource", style="bold")
        drivers.add_column("Type")
        drivers.add_column("Monthly", justify="right")
        drivers.add_column("% of total", justify="right")
        for rc in report.top_cost_drivers:
            drivers.add_row(
                rc.resource.address,
                rc.resource.resource_type,
                f"${rc.monthly_cost:,.2f}",
                f"{rc.percentage_of_total:.1f}%",
            )
        console.print(drivers)
        console.print()

    if report.optimizations:
        opt = Table(title="Optimization Suggestions")
        opt.add_column("Title", style="bold")
        opt.add_column("Resource")
        opt.add_column("Savings", justify="right")
        opt.add_column("Risk")
        opt.add_column("Suggested change")
        for o in report.optimizations:
            color = RISK_COLORS.get(o.risk, "")
            opt.add_row(
                o.title,
                o.resource_address,
                f"${o.estimated_monthly_savings:,.2f}",
                f"[{color}]{o.risk.value.upper()}[/{color}]",
                o.suggested_config,
            )
        console.print(opt)
        console.print()

    if report.patterns_detected and not report.optimizations:
        # Fall back to showing patterns if the LLM produced no optimizations.
        console.print("[bold]Detected patterns:[/bold]")
        for p in report.patterns_detected:
            console.print(f"  - {p.description}")
        console.print()

    if report.errors:
        console.print("[yellow]Warnings/errors:[/yellow]")
        for err in report.errors:
            console.print(f"  - {err}")
        console.print()


# ── Markdown ───────────────────────────────────────────────────────


def format_markdown(report: CostAnalysisReport) -> str:
    provider = report.provider.value.upper() if report.provider else "multi-cloud"
    lines = [
        f"# IaCCostAgent Report — {provider}",
        "",
        f"**Project:** `{report.project_path}`  ",
        f"**Backend:** {report.backend_used}  ",
        f"**Analyzed:** {report.analyzed_at.strftime('%Y-%m-%d %H:%M UTC')}  ",
    ]
    if report.region:
        lines.append(f"**Region:** {report.region}  ")
    lines += [
        "",
        "## Summary",
        "",
        report.executive_summary or "(no summary generated)",
        "",
        f"- **Total monthly cost:** ${report.total_monthly_cost:,.2f}",
        f"- **Resources:** {report.resource_count}",
        f"- **Potential savings:** ${report.total_potential_savings:,.2f} ({report.savings_percentage:.1f}% reduction)",
        "",
    ]

    if report.top_cost_drivers:
        lines += [
            "## Top Cost Drivers",
            "",
            "| Resource | Type | Monthly | % of total |",
            "|----------|------|--------:|-----------:|",
        ]
        for rc in report.top_cost_drivers:
            lines.append(
                f"| `{rc.resource.address}` | {rc.resource.resource_type} | "
                f"${rc.monthly_cost:,.2f} | {rc.percentage_of_total:.1f}% |"
            )
        lines.append("")

    if report.optimizations:
        lines += [
            "## Optimization Suggestions",
            "",
            "| Title | Resource | Savings | Risk | Suggested change |",
            "|-------|----------|--------:|------|------------------|",
        ]
        for o in report.optimizations:
            lines.append(
                f"| {o.title} | `{o.resource_address}` | "
                f"${o.estimated_monthly_savings:,.2f} | {o.risk.value.upper()} | "
                f"{o.suggested_config} |"
            )
        lines.append("")

    if report.patterns_detected:
        lines += ["## Detected Patterns", ""]
        for p in report.patterns_detected:
            savings = f" — ~${p.estimated_savings_monthly:,.2f}/month" if p.estimated_savings_monthly else ""
            lines.append(f"- **{p.pattern_type.value}**: {p.description}{savings}")
        lines.append("")

    if report.errors:
        lines += ["## Warnings", ""]
        for err in report.errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)


# ── JSON ──────────────────────────────────────────────────────────


def format_json(report: CostAnalysisReport) -> str:
    return report.model_dump_json(indent=2)


# ── GitHub PR Comment ─────────────────────────────────────────────


def format_github_comment(report: CostAnalysisReport) -> str:
    provider = report.provider.value.upper() if report.provider else "multi-cloud"
    lines = [
        f"## IaCCostAgent Cost Review — {provider}",
        "",
        f"**Estimated monthly cost:** `${report.total_monthly_cost:,.2f}`  ",
        f"**Potential savings:** `${report.total_potential_savings:,.2f}` "
        f"({report.savings_percentage:.1f}% reduction)  ",
        f"**Resources analyzed:** {report.resource_count}",
        "",
    ]

    if report.executive_summary:
        lines += [report.executive_summary, ""]

    high_impact = [o for o in report.optimizations if o.estimated_monthly_savings >= 50]
    other = [o for o in report.optimizations if o.estimated_monthly_savings < 50]

    if high_impact:
        lines += ["### High-impact optimizations", ""]
        for o in high_impact:
            lines.append(
                f"- **{o.title}** (`{o.resource_address}`) — save "
                f"${o.estimated_monthly_savings:,.2f}/month. "
                f"Risk: {o.risk.value}. {o.suggested_config}"
            )
        lines.append("")

    if other:
        lines += [f"<details><summary>Other suggestions ({len(other)})</summary>", ""]
        lines += ["| Title | Resource | Savings | Risk |", "|-------|----------|--------:|------|"]
        for o in other:
            lines.append(
                f"| {o.title} | `{o.resource_address}` | ${o.estimated_monthly_savings:,.2f} | {o.risk.value} |"
            )
        lines += ["", "</details>", ""]

    if report.errors:
        lines += [f"<details><summary>Warnings ({len(report.errors)})</summary>", ""]
        for err in report.errors:
            lines.append(f"- {err}")
        lines += ["", "</details>", ""]

    return "\n".join(lines)


# ── Dispatcher ────────────────────────────────────────────────────

FORMATTERS = {
    "terminal": None,  # terminal handled separately (prints directly)
    "markdown": format_markdown,
    "json": format_json,
    "github-comment": format_github_comment,
}


def output_report(report: CostAnalysisReport, fmt: str = "terminal", output_file: str | None = None) -> None:
    """Output the report in the requested format, to stdout or a file."""
    if fmt == "terminal" and output_file is None:
        format_terminal(report)
        return

    formatter = FORMATTERS.get(fmt)
    if formatter is None:
        formatter = format_json

    content = formatter(report)

    if output_file:
        with open(output_file, "w") as f:
            f.write(content)
        console.print(f"Report written to {output_file}")
    else:
        print(content)
