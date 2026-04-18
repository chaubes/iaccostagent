"""IaCCostAgent CLI application built with Typer."""

import asyncio
import os

import typer
from dotenv import load_dotenv
from rich.console import Console

from iaccostagent.backends.registry import get_backend, list_backends
from iaccostagent.utils.git import GitError, fetch_source, is_git_url

app = typer.Typer(
    name="iaccostagent",
    help="AI-powered Terraform cost preview and optimization advisor",
    no_args_is_help=True,
)
console = Console()
# Warnings go to stderr so they don't pollute JSON output pipes.
warn_console = Console(stderr=True)


# Reference-implementation backends — limited coverage, meant for extension / niche use,
# NOT for production cost analysis. We surface a clear warning whenever they're selected
# so users don't accidentally trust narrow numbers for billing decisions.
REFERENCE_BACKENDS = {"aws-pricing", "azure-retail", "gcp-catalog"}


def _warn_if_reference_backend(name: str) -> None:
    """Emit a one-line stderr warning when a reference/extension backend is selected."""
    if name not in REFERENCE_BACKENDS:
        return
    warn_console.print(
        f"[yellow]⚠  '{name}' is a reference / extension-pattern backend with limited coverage.[/yellow]\n"
        f"[yellow]   Use --backend infracost for production cost analysis. "
        f"Do not rely on these numbers for billing decisions.[/yellow]\n"
        f"[yellow]   See docs/adding-backends.md for the extension pattern.[/yellow]"
    )


@app.callback()
def _load_env() -> None:
    """Load .env before any command runs."""
    load_dotenv(override=True)


def _resolve_llm(llm: str | None) -> str:
    if llm:
        return llm
    provider = os.environ.get("IACCOSTAGENT_LLM_PROVIDER", "ollama")
    model = os.environ.get("IACCOSTAGENT_LLM_MODEL", "qwen3:8b")
    return f"{provider}/{model}"


def _infer_input_format(path: str, explicit: str | None) -> str:
    if explicit in ("hcl", "plan-json"):
        return explicit
    return "plan-json" if path.endswith(".json") else "hcl"


def _resolve_path(path: str, *, subdir: str | None = None, verbose: bool = False):
    """
    Context manager wrapping `fetch_source` with user-facing logging.

    For local paths, this is effectively a no-op that yields the path.
    For git URLs, it shallow-clones, yields the cloned dir (or subdir),
    and removes the clone on exit.
    """
    if verbose and is_git_url(path):
        console.print(f"Cloning {path}...")
    return fetch_source(path, subdir=subdir)


INSTALL_HINTS = {
    "infracost": (
        "Install Infracost:\n"
        "  macOS:  brew install infracost\n"
        "  Linux:  curl -fsSL https://raw.githubusercontent.com/infracost/infracost/master/scripts/install.sh | sh\n"
        "Then authenticate: infracost auth login\n"
        "Or switch backends:  --backend openinfraquote / aws-pricing / azure-retail / gcp-catalog"
    ),
    "openinfraquote": (
        "Install OpenInfraQuote:\n"
        "  macOS:  brew install openinfraquote/tap/oiq\n"
        "  Other:  https://github.com/terrateamio/openinfraquote\n"
        "Remember to set OIQ_PRICESHEET to the pricesheet CSV path."
    ),
    "aws-pricing": (
        "The aws-pricing backend is a reference implementation that uses AWS's public Price List API "
        "(no IAM required). Coverage is limited to aws_instance + aws_ebs_volume. "
        "Use --backend infracost for full coverage."
    ),
    "azure-retail": (
        "The azure-retail backend is a reference implementation that uses Azure's public Retail Prices API "
        "(no key required). Coverage is limited to VMs + managed disks. "
        "Use --backend infracost for full coverage."
    ),
    "gcp-catalog": (
        "The gcp-catalog backend uses the Cloud Billing Catalog API. "
        "Requires GOOGLE_API_KEY with the Cloud Billing API enabled "
        "(https://console.cloud.google.com/apis/credentials). "
        "Coverage is limited to google_compute_instance. Use --backend infracost for full coverage."
    ),
}


def _ensure_backend_ready(backend_name: str) -> None:
    """Fail fast with an actionable error if the selected backend isn't usable.

    Checks performed:
      1. Backend is registered and available (binary on PATH for subprocess-based
         backends; HTTPS egress for native ones).
      2. Provider-specific credentials / config are present.

    Called at the top of `analyze`, `estimate`, and `diff` so users don't
    wait for the pipeline to spin up before hitting a config error.
    """
    backend_obj = _build_backend(backend_name)
    if not backend_obj.is_available():
        console.print(f"[red]{backend_name} is not available.[/red]")
        console.print(INSTALL_HINTS.get(backend_name, ""))
        raise typer.Exit(code=1)

    if backend_name == "infracost" and not os.environ.get("INFRACOST_API_KEY"):
        console.print(
            "[red]INFRACOST_API_KEY is not set.[/red] "
            "Get a free key at https://infracost.io, then either run "
            "`infracost auth login` or add INFRACOST_API_KEY to your .env."
        )
        raise typer.Exit(code=1)

    if backend_name == "openinfraquote" and not os.environ.get("OIQ_PRICESHEET"):
        console.print(
            "[red]OIQ_PRICESHEET is not set.[/red] "
            "Download the pricesheet CSV and point OIQ_PRICESHEET to it, "
            "or switch to --backend infracost."
        )
        raise typer.Exit(code=1)

    if backend_name == "gcp-catalog" and not os.environ.get("GOOGLE_API_KEY"):
        console.print(
            "[red]GOOGLE_API_KEY is not set.[/red] "
            "Create a GCP API key with the Cloud Billing API enabled and export it, "
            "or use --backend infracost."
        )
        raise typer.Exit(code=1)

    _warn_if_reference_backend(backend_name)


@app.command()
def analyze(
    path: str = typer.Argument(..., help="Terraform dir, .tf file, plan JSON, or git URL"),
    backend: str = typer.Option(
        "infracost",
        "--backend",
        "-b",
        help=(
            "Cost backend. Options: infracost (default, full AWS/Azure/GCP), "
            "openinfraquote (AWS, local), aws-pricing (reference, public API), "
            "azure-retail (reference, public API), gcp-catalog (reference, needs GOOGLE_API_KEY)."
        ),
    ),
    region: str | None = typer.Option(None, "--region", "-r", help="Cloud region (e.g., us-east-1)"),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM provider/model (e.g., ollama/qwen3:8b, openai/gpt-4o-mini)",
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Skip the LLM entirely. Produces a rule-based report using only "
        "the cost backend + pattern engine. Useful for air-gapped environments.",
    ),
    fmt: str = typer.Option(
        "terminal",
        "--format",
        "-f",
        help="Output format: terminal, markdown, json, github-comment",
    ),
    output: str | None = typer.Option(None, "--output", "-o", help="Write output to file instead of stdout"),
    input_format: str | None = typer.Option(
        None,
        "--input-format",
        help="Force input format: hcl or plan-json (auto-detected from path)",
    ),
    subdir: str | None = typer.Option(
        None,
        "--subdir",
        help="When path is a git URL, analyze this subdirectory of the cloned repo (e.g., infrastructure/)",
    ),
    max_cost: float | None = typer.Option(
        None,
        "--max-cost",
        help="Cost ceiling for policy gating (used with --fail-on-exceed)",
    ),
    fail_on_exceed: bool = typer.Option(
        False,
        "--fail-on-exceed",
        help="Exit with code 1 if total monthly cost exceeds --max-cost",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress"),
) -> None:
    """Run the full cost analysis pipeline. Accepts local paths and git URLs."""
    from iaccostagent.agent.graph import run_analysis
    from iaccostagent.utils.output import output_report

    _ensure_backend_ready(backend)

    llm_provider = _resolve_llm(llm)

    try:
        with _resolve_path(path, subdir=subdir, verbose=verbose) as (resolved, _cloned):
            in_fmt = _infer_input_format(str(resolved), input_format)

            if verbose:
                mode = "rule-based only" if no_llm else llm_provider
                console.print(f"Analyzing {resolved} via {backend} ({mode})...")

            try:
                report = asyncio.run(
                    run_analysis(
                        project_path=str(resolved),
                        input_format=in_fmt,
                        backend=backend,
                        region=region,
                        llm_provider=llm_provider,
                        skip_llm=no_llm,
                    )
                )
            except Exception as e:
                console.print(f"[red]Analysis failed: {e}[/red]")
                raise typer.Exit(code=1)
    except GitError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    if report is None:
        console.print("[red]Analysis produced no report.[/red]")
        raise typer.Exit(code=1)

    # Replace the temp-dir path with the original git URL in the report for clarity.
    if is_git_url(path):
        report.project_path = path + (f"#{subdir}" if subdir else "")

    output_report(report, fmt=fmt, output_file=output)

    if max_cost is not None and fail_on_exceed and report.total_monthly_cost > max_cost:
        console.print(f"[red]Monthly cost ${report.total_monthly_cost:,.2f} exceeds threshold ${max_cost:,.2f}[/red]")
        raise typer.Exit(code=1)


@app.command()
def estimate(
    path: str = typer.Argument(..., help="Terraform dir, .tf file, plan JSON, or git URL"),
    backend: str = typer.Option(
        "infracost",
        "--backend",
        "-b",
        help="Cost backend: infracost | openinfraquote | aws-pricing | azure-retail | gcp-catalog",
    ),
    region: str | None = typer.Option(None, "--region", "-r", help="Cloud region"),
    fmt: str = typer.Option("terminal", "--format", "-f", help="Output format"),
    output: str | None = typer.Option(None, "--output", "-o", help="Write output to file"),
    subdir: str | None = typer.Option(
        None,
        "--subdir",
        help="When path is a git URL, estimate this subdirectory of the cloned repo",
    ),
) -> None:
    """Fast cost estimate only — no LLM, no pattern analysis."""
    _ensure_backend_ready(backend)

    from iaccostagent.utils.output import console as out_console

    try:
        with _resolve_path(path, subdir=subdir) as (resolved, _cloned):

            async def _run():
                backend_obj = _build_backend(backend)
                return await backend_obj.estimate(str(resolved), region=region)

            try:
                est = asyncio.run(_run())
            except Exception as e:
                console.print(f"[red]Estimate failed: {e}[/red]")
                raise typer.Exit(code=1)
    except GitError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    if fmt == "json":
        payload = est.model_dump_json(indent=2)
        if output:
            with open(output, "w") as f:
                f.write(payload)
            out_console.print(f"Estimate written to {output}")
        else:
            print(payload)
        return

    out_console.print(
        f"[bold]Total monthly cost:[/bold] ${est.total_monthly_cost:,.2f}  "
        f"[bold]Resources:[/bold] {len(est.resource_costs)}  "
        f"[bold]Backend:[/bold] {est.backend}"
    )
    for rc in sorted(est.resource_costs, key=lambda r: r.monthly_cost, reverse=True)[:10]:
        out_console.print(
            f"  {rc.resource.address:<60} ${rc.monthly_cost:>10,.2f}/month ({rc.percentage_of_total:5.1f}%)"
        )


@app.command()
def diff(
    before: str = typer.Argument(..., help="Path A — Terraform dir, plan JSON, or git URL"),
    after: str = typer.Argument(..., help="Path B — Terraform dir, plan JSON, or git URL"),
    backend: str = typer.Option(
        "infracost",
        "--backend",
        "-b",
        help="Cost backend: infracost | openinfraquote | aws-pricing | azure-retail | gcp-catalog",
    ),
    region: str | None = typer.Option(None, "--region", "-r", help="Cloud region"),
    subdir: str | None = typer.Option(
        None,
        "--subdir",
        help="Subdirectory applied to both inputs. Use --before-subdir / --after-subdir for asymmetric layouts.",
    ),
    before_subdir: str | None = typer.Option(
        None,
        "--before-subdir",
        help="Subdirectory inside the 'before' input. Overrides --subdir for this side.",
    ),
    after_subdir: str | None = typer.Option(
        None,
        "--after-subdir",
        help="Subdirectory inside the 'after' input. Overrides --subdir for this side.",
    ),
) -> None:
    """Compare estimated costs between two configurations (local paths or git URLs)."""
    _ensure_backend_ready(backend)

    from iaccostagent.utils.diff import diff_estimates

    # Per-side subdir takes precedence; --subdir is the shared default.
    effective_before_subdir = before_subdir if before_subdir is not None else subdir
    effective_after_subdir = after_subdir if after_subdir is not None else subdir

    try:
        with (
            _resolve_path(before, subdir=effective_before_subdir) as (before_resolved, _),
            _resolve_path(after, subdir=effective_after_subdir) as (after_resolved, _),
        ):

            async def _run():
                backend_obj = _build_backend(backend)
                before_est = await backend_obj.estimate(str(before_resolved), region=region)
                after_est = await backend_obj.estimate(str(after_resolved), region=region)
                return diff_estimates(before_est, after_est)

            try:
                result = asyncio.run(_run())
            except Exception as e:
                console.print(f"[red]Diff failed: {e}[/red]")
                raise typer.Exit(code=1)
    except GitError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    # Label each side with its original input (and subdir, if any) for clarity.
    def _label(input_path: str, sub: str | None) -> str:
        return f"{input_path}{('#' + sub) if sub else ''}"

    before_label = _label(before, effective_before_subdir)
    after_label = _label(after, effective_after_subdir)

    symbol = "+" if result.delta_monthly >= 0 else ""
    console.print(f"[bold]Before:[/bold] {before_label}")
    console.print(f"        ${result.before_monthly_cost:,.2f}/month")
    console.print(f"[bold]After:[/bold]  {after_label}")
    console.print(f"        ${result.after_monthly_cost:,.2f}/month")
    console.print(
        f"[bold]Delta:[/bold]  {symbol}${result.delta_monthly:,.2f}/month ({symbol}{result.delta_percentage:.1f}%)"
    )

    if result.added_resources:
        console.print(f"\n[green]Added ({len(result.added_resources)}):[/green]")
        for rc in result.added_resources:
            console.print(f"  + {rc.resource.address} (${rc.monthly_cost:,.2f}/mo)")
    if result.removed_resources:
        console.print(f"\n[yellow]Removed ({len(result.removed_resources)}):[/yellow]")
        for rc in result.removed_resources:
            console.print(f"  - {rc.resource.address} (${rc.monthly_cost:,.2f}/mo)")
    if result.changed_resources:
        console.print(f"\n[cyan]Changed ({len(result.changed_resources)}):[/cyan]")
        for before_rc, after_rc in result.changed_resources:
            delta = after_rc.monthly_cost - before_rc.monthly_cost
            sym = "+" if delta >= 0 else ""
            console.print(
                f"  ~ {before_rc.resource.address}: "
                f"${before_rc.monthly_cost:,.2f} → ${after_rc.monthly_cost:,.2f} "
                f"({sym}${delta:,.2f})"
            )


@app.command("check-backend")
def check_backend(
    backend: str = typer.Option(
        "infracost",
        "--backend",
        "-b",
        help="Backend to check: infracost | openinfraquote | aws-pricing | azure-retail | gcp-catalog",
    ),
    verify: bool = typer.Option(
        False,
        "--verify",
        help=(
            "Run the backend on a tiny in-memory Terraform snippet to confirm "
            "binary + API key + pricing lookup all work end-to-end."
        ),
    ),
) -> None:
    """Verify the selected cost backend is installed and reachable."""
    _warn_if_reference_backend(backend)

    backend_obj = _build_backend(backend)
    if backend_obj.is_available():
        console.print(f"[green]✓ {backend} is available[/green]")
    else:
        console.print(f"[red]✗ {backend} is NOT available[/red]")
        console.print(INSTALL_HINTS.get(backend, ""))
        raise typer.Exit(code=1)

    if backend == "infracost":
        if os.environ.get("INFRACOST_API_KEY"):
            console.print("[green]✓ INFRACOST_API_KEY is set[/green]")
        else:
            console.print("[yellow]! INFRACOST_API_KEY is not set — estimates will fail.[/yellow]")
            raise typer.Exit(code=1)

    if backend == "openinfraquote":
        if os.environ.get("OIQ_PRICESHEET"):
            console.print("[green]✓ OIQ_PRICESHEET is set[/green]")
        else:
            console.print("[yellow]! OIQ_PRICESHEET is not set — estimates will fail.[/yellow]")
            raise typer.Exit(code=1)

    if backend == "gcp-catalog":
        if os.environ.get("GOOGLE_API_KEY"):
            console.print("[green]✓ GOOGLE_API_KEY is set[/green]")
        else:
            console.print("[yellow]! GOOGLE_API_KEY is not set — estimates will fail.[/yellow]")
            raise typer.Exit(code=1)

    if not verify:
        return

    # End-to-end verification: run the backend on a tiny generated snippet.
    console.print("Running end-to-end verification…")
    try:
        total = asyncio.run(_verify_backend(backend_obj, backend))
    except Exception as e:
        console.print(f"[red]✗ End-to-end verification failed: {e}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]✓ {backend} returned a valid estimate[/green] (sample total: ${total:,.2f}/month)")


# Provider-appropriate snippets used by --verify. Each is small enough to
# cost almost nothing while still exercising a real pricing lookup.
_VERIFY_AWS_HCL = """\
resource "aws_instance" "verify" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.micro"
}
"""

_VERIFY_AZURE_HCL = """\
resource "azurerm_resource_group" "verify" {
  name     = "verify-rg"
  location = "eastus"
}

resource "azurerm_linux_virtual_machine" "verify" {
  name                = "verify"
  resource_group_name = azurerm_resource_group.verify.name
  location            = azurerm_resource_group.verify.location
  size                = "Standard_B1s"
  admin_username      = "verify"
  network_interface_ids = []

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }
}
"""

_VERIFY_GCP_HCL = """\
resource "google_compute_instance" "verify" {
  name         = "verify"
  machine_type = "e2-small"
  zone         = "us-central1-a"

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
    }
  }

  network_interface {
    network = "default"
  }
}
"""

_VERIFY_PLAN_JSON = """\
{
  "format_version": "1.2",
  "terraform_version": "1.7.0",
  "planned_values": {
    "root_module": {
      "resources": [
        {
          "address": "aws_instance.verify",
          "mode": "managed",
          "type": "aws_instance",
          "name": "verify",
          "values": {
            "ami": "ami-0c55b159cbfafe1f0",
            "instance_type": "t3.micro"
          }
        }
      ]
    }
  }
}
"""


def _verify_snippet_for(backend_name: str) -> tuple[str, str]:
    """Pick the right (filename, contents) for --verify based on backend."""
    if backend_name == "azure-retail":
        return "main.tf", _VERIFY_AZURE_HCL
    if backend_name == "gcp-catalog":
        return "main.tf", _VERIFY_GCP_HCL
    if backend_name == "openinfraquote":
        return "plan.json", _VERIFY_PLAN_JSON
    return "main.tf", _VERIFY_AWS_HCL


def _verify_region_for(backend_name: str) -> str:
    if backend_name == "azure-retail":
        return "eastus"
    if backend_name == "gcp-catalog":
        return "us-central1"
    return "us-east-1"


async def _verify_backend(backend_obj, backend_name: str) -> float:
    """Write a tiny fixture to a temp dir and run the backend against it."""
    import tempfile
    from pathlib import Path

    filename, contents = _verify_snippet_for(backend_name)
    region = _verify_region_for(backend_name)

    with tempfile.TemporaryDirectory(prefix="iaccostagent-verify-") as tmp:
        tmp_path = Path(tmp)
        target = tmp_path / filename
        target.write_text(contents)
        # Directory input for HCL backends; file input for plan-JSON ones.
        input_path = str(target) if filename.endswith(".json") else str(tmp_path)
        estimate = await backend_obj.estimate(input_path, region=region)
        return estimate.total_monthly_cost


@app.command()
def version() -> None:
    """Show IaCCostAgent version."""
    from importlib.metadata import version as pkg_version

    try:
        v = pkg_version("iaccostagent")
    except Exception:
        v = "0.1.0"
    console.print(f"iaccostagent {v}")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind"),
    port: int = typer.Option(8888, "--port", "-p", help="Port to listen on"),
) -> None:
    """Start the HTTP API server."""
    try:
        import uvicorn

        from iaccostagent.server.api import app as fastapi_app
    except ImportError:
        console.print("[red]Server dependencies not installed.[/red]")
        # Escape the square brackets: Rich interprets [server] as a markup tag
        # and would otherwise silently drop it, leaving the user with a
        # truncated install hint. Also remind them to quote in a shell since
        # bash/zsh treat `[...]` as a glob.
        console.print(r"Install with: pip install 'iaccostagent\[server]'")
        raise typer.Exit(code=1)

    console.print(f"Starting IaCCostAgent server on {host}:{port}...")
    uvicorn.run(fastapi_app, host=host, port=port)


def _build_backend(name: str):
    try:
        return get_backend(name)
    except KeyError:
        console.print(f"[red]Unknown backend: {name}[/red]")
        console.print(f"Supported: {', '.join(list_backends())}")
        raise typer.Exit(code=1)
