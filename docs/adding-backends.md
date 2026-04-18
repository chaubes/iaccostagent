# Adding a Cost Backend

All backends live behind the same interface (`backends/base.py:CostBackend`) and register themselves with a decorator. The CLI, the LangGraph agent node, and the FastAPI server all look up backends through the same registry — so wiring a new backend in is exactly one class.

## The contract

```python
# backends/base.py
class CostBackend(ABC):
    name: str

    @abstractmethod
    async def estimate(self, terraform_path: str, region: str | None = None) -> CostEstimate: ...

    @abstractmethod
    def is_available(self) -> bool: ...
```

- `is_available()` returns `False` if the backend can't run right now (binary missing, API key unset, etc.). The CLI pre-flight uses this to fail fast with a clear message.
- `estimate(path, region)` runs the actual pricing lookup and returns a normalized `CostEstimate`.

## Two integration styles

Shipped backends fall into two shapes; pick whichever matches your data source.

### A. Subprocess wrapper (like `infracost`, `openinfraquote`)

Use when you're shelling out to an external CLI.

```python
import asyncio
from datetime import UTC, datetime

from iaccostagent.backends.base import CostBackend
from iaccostagent.backends.registry import register_backend
from iaccostagent.models.schemas import CostEstimate
from iaccostagent.utils.subprocess_runner import BinaryNotFoundError, check_binary, run


@register_backend("my-cli")
class MyCliBackend(CostBackend):
    name = "my-cli"

    def is_available(self) -> bool:
        try:
            check_binary("my-cli")
        except BinaryNotFoundError:
            return False
        return True

    async def estimate(self, terraform_path: str, region: str | None = None) -> CostEstimate:
        result = await asyncio.to_thread(
            run, ["my-cli", "estimate", "--json", terraform_path], timeout=180
        )
        return self._parse(result.stdout, region)

    def _parse(self, stdout: str, region: str | None) -> CostEstimate:
        # Convert tool JSON → CostEstimate / ResourceCost / CostComponent.
        ...
```

**Safety notes:**
- Always use `subprocess_runner.run` (never direct `subprocess.run` / `os.system`).
- Pass arguments as a list — `shell=False` is enforced inside the helper.
- Respect a timeout. Never log credentials that may appear in stdout/stderr.

### B. Native pricing-API backend (like `aws-pricing`, `azure-retail`, `gcp-catalog`)

Use when you're querying a cloud provider's public or authenticated pricing API directly. The three shipped native backends show three different auth shapes — pick the closest match:

| Backend | Auth | Pattern |
|---------|------|---------|
| `azure-retail` | None (fully public) | HTTPS GET → pagination → filter |
| `aws-pricing` | None (public price-list JSON) | Bulk JSON download → local SKU matching |
| `gcp-catalog` | API key (`GOOGLE_API_KEY`) | Authed API → catalog SKU enumeration |

The native backends use a small **handler dispatch table** so adding a new Terraform resource type is a one-function change:

```python
HANDLERS: dict[str, HandlerFn] = {
    "azurerm_linux_virtual_machine": _price_linux_vm,
    "azurerm_windows_virtual_machine": _price_windows_vm,
    "azurerm_managed_disk": _price_managed_disk,
}
```

To extend coverage: write a handler for the new resource type, register it in `HANDLERS`. Unit test it using `respx` to mock the upstream API response (see `tests/unit/test_backends_native.py` for the pattern).

## Parse Terraform once, not twice

Native backends call `HCLParser` / `PlanJSONParser` internally to convert the path into `TerraformResource` objects. That's the same work the agent's `parse_terraform` node does — it's cheap to redo. If you're writing a hot-path backend that'll run in a tight loop, consider accepting a pre-parsed resource list via constructor injection instead.

## Register the backend

`@register_backend("my-cli")` is the only wiring. The registry calls it the moment the module is imported; the CLI's backend-list command picks it up automatically:

```bash
$ iaccostagent check-backend --backend made-up
Unknown backend: made-up
Supported: aws-pricing, azure-retail, gcp-catalog, infracost, my-cli, openinfraquote
```

If your backend ships in the `iaccostagent` package, add an import line to `backends/registry.py:_autodiscover()` so it loads at startup. If it's a third-party plugin, have users import it before invoking the CLI (e.g. via a `[project.entry-points."iaccostagent.backends"]` entry-point in their own `pyproject.toml`).

## Tests

Every shipped backend has both:

- **Unit test** with recorded fixture JSON under `tests/fixtures/cost_output/` (subprocess backends) or a `respx` mock (native backends). Fast, offline.
- **Optional integration test** under `tests/integration/` gated on the real dependency being present. Skipped in CI unless installed.

Follow the shape of `tests/unit/test_backends_infracost.py` (subprocess) or `tests/unit/test_backends_native.py` (HTTP).

## Pre-flight check wiring

If your backend needs a specific env var or configuration, add a branch to `cli/app.py:_ensure_backend_ready()` so the CLI fails fast with a clear hint rather than hitting an obscure error mid-pipeline. Also add an entry to `INSTALL_HINTS` with the install / configuration instructions.
