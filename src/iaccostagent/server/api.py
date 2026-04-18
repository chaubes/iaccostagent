"""IaCCostAgent HTTP API server built with FastAPI."""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

from iaccostagent.agent.graph import run_analysis
from iaccostagent.backends.registry import get_backend
from iaccostagent.models.schemas import CostAnalysisReport, CostEstimate, DiffResult
from iaccostagent.utils.diff import diff_estimates


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load .env on server startup."""
    load_dotenv(override=True)
    yield


app = FastAPI(
    title="IaCCostAgent API",
    description="AI-powered Terraform cost preview and optimization advisor",
    version="0.1.0",
    lifespan=lifespan,
)


class AnalyzeRequest(BaseModel):
    project_path: str
    input_format: str = "hcl"
    backend: str = "infracost"
    region: str | None = None
    llm_provider: str = "ollama/qwen3:8b"


class AnalyzeResponse(BaseModel):
    status: str
    report: CostAnalysisReport | None = None
    error: str | None = None


class EstimateRequest(BaseModel):
    project_path: str
    backend: str = "infracost"
    region: str | None = None


class EstimateResponse(BaseModel):
    status: str
    estimate: CostEstimate | None = None
    error: str | None = None


class DiffRequest(BaseModel):
    before_path: str
    after_path: str
    backend: str = "infracost"
    region: str | None = None


class DiffResponse(BaseModel):
    status: str
    diff: DiffResult | None = None
    error: str | None = None


def _build_backend(name: str):
    try:
        return get_backend(name)
    except KeyError as e:
        raise ValueError(str(e)) from e


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Run the full LLM-powered analysis pipeline."""
    try:
        report = await run_analysis(
            project_path=request.project_path,
            input_format=request.input_format,
            backend=request.backend,
            region=request.region,
            llm_provider=request.llm_provider,
        )
        return AnalyzeResponse(status="success", report=report)
    except Exception as e:
        return AnalyzeResponse(status="error", error=str(e))


@app.post("/api/v1/estimate", response_model=EstimateResponse)
async def estimate(request: EstimateRequest) -> EstimateResponse:
    """Run cost estimation only (no LLM)."""
    try:
        backend = _build_backend(request.backend)
        est = await backend.estimate(request.project_path, region=request.region)
        return EstimateResponse(status="success", estimate=est)
    except Exception as e:
        return EstimateResponse(status="error", error=str(e))


@app.post("/api/v1/diff", response_model=DiffResponse)
async def diff(request: DiffRequest) -> DiffResponse:
    """Compare two configurations."""
    try:
        backend = _build_backend(request.backend)
        before = await backend.estimate(request.before_path, region=request.region)
        after = await backend.estimate(request.after_path, region=request.region)
        return DiffResponse(status="success", diff=diff_estimates(before, after))
    except Exception as e:
        return DiffResponse(status="error", error=str(e))


@app.get("/api/v1/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "service": "iaccostagent"}
