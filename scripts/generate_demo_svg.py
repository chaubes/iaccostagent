"""
Generate docs/demo.svg by running the real analyze pipeline against the
overprovisioned fixture and capturing Rich's console output as an SVG.

Run with:
    uv run python scripts/generate_demo_svg.py

Needs a configured cost backend (infracost or aws-pricing) available.
Uses --no-llm so the demo is deterministic and doesn't need an LLM.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from rich.console import Console

# Swap the output module's console for a recording one BEFORE any
# downstream import reads it.
import iaccostagent.utils.output as _output_module

recorded = Console(record=True, width=110)
_output_module.console = recorded

from iaccostagent.agent.graph import run_analysis  # noqa: E402
from iaccostagent.utils.output import format_terminal  # noqa: E402

FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "terraform" / "overprovisioned"
OUT = Path(__file__).parent.parent / "docs" / "demo.svg"
BACKEND = "aws-pricing"
REGION = "us-east-1"


async def main() -> None:
    report = await run_analysis(
        project_path=str(FIXTURE),
        backend=BACKEND,
        region=REGION,
        skip_llm=True,  # deterministic, no LLM needed
    )
    if report is None:
        sys.exit("analysis produced no report")

    format_terminal(report)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    recorded.save_svg(
        str(OUT),
        title="iaccostagent analyze — overprovisioned fixture",
    )
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
