"""
Generate docs/demo-no-llm.svg and docs/demo-with-llm.svg by running the real
analyze pipeline against the overprovisioned fixture and capturing Rich's
console output as SVGs.

Run from the repo root (this script assumes CWD == the project root so that
all paths that appear in the output are relative):

    cd iaccostagent
    uv run python scripts/generate_demo_svg.py

Requires:
- A configured Infracost backend (INFRACOST_API_KEY + `infracost` CLI on PATH)
- For the with-llm variant: a working LLM provider (OPENAI_API_KEY for
  openai/gpt-4o-mini by default, or a reachable Ollama)

The script also sanitizes any accidental absolute paths (e.g. /Users/<name>/...)
from the generated SVGs before writing them to disk, so demos never leak
developer-machine paths.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from rich.console import Console

import iaccostagent.utils.output as _output_module
from iaccostagent.agent.graph import run_analysis
from iaccostagent.utils.output import format_terminal

FIXTURE = "tests/fixtures/terraform/overprovisioned"
BACKEND = "infracost"
REGION = "us-east-1"
LLM_PROVIDER = os.environ.get("IACCOSTAGENT_DEMO_LLM", "openai/gpt-4o-mini")
DOCS_DIR = Path("docs")


def _sanitize_paths(svg_text: str) -> str:
    """Replace any leaked absolute paths with generic placeholders."""
    svg_text = re.sub(r"/Users/[^/\s<]+", "~", svg_text)
    svg_text = re.sub(r"/home/[^/\s<]+", "~", svg_text)
    svg_text = svg_text.replace(str(Path.cwd()) + "/", "")
    return svg_text


async def _render(skip_llm: bool, out_name: str, title: str) -> None:
    recorded = Console(record=True, width=110)
    _output_module.console = recorded

    report = await run_analysis(
        project_path=FIXTURE,
        backend=BACKEND,
        region=REGION,
        llm_provider=LLM_PROVIDER,
        skip_llm=skip_llm,
    )
    if report is None:
        sys.exit(f"analysis produced no report for {title}")

    format_terminal(report)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out = DOCS_DIR / out_name
    svg_text = recorded.export_svg(title=title)
    out.write_text(_sanitize_paths(svg_text))
    print(f"  wrote {out}")


async def main() -> None:
    if not Path(FIXTURE).exists():
        sys.exit(f"Fixture not found at {FIXTURE}. Run this script from the repo root.")

    print(f"Generating demo SVGs from fixture: {FIXTURE}")
    print(f"Backend:      {BACKEND} ({REGION})")
    print(f"LLM provider: {LLM_PROVIDER}")
    print()

    print("[1/2] rendering --no-llm variant")
    await _render(
        skip_llm=True,
        out_name="demo-no-llm.svg",
        title="iaccostagent analyze --no-llm",
    )

    print("[2/2] rendering with-LLM variant (makes real API calls)")
    await _render(
        skip_llm=False,
        out_name="demo-with-llm.svg",
        title=f"iaccostagent analyze --llm {LLM_PROVIDER}",
    )


if __name__ == "__main__":
    asyncio.run(main())
