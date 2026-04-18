"""Abstract base class for cost estimation backends."""

from abc import ABC, abstractmethod

from iaccostagent.models.schemas import CostEstimate


class CostBackend(ABC):
    """
    Every cost backend wraps an external CLI (Infracost, OpenInfraQuote, ...).

    Concrete subclasses take a Terraform path (or plan JSON) and return a
    normalized CostEstimate. If the underlying CLI is not installed,
    `estimate()` should raise BinaryNotFoundError.
    """

    name: str

    @abstractmethod
    async def estimate(self, terraform_path: str, region: str | None = None) -> CostEstimate:
        """Run cost estimation against a Terraform path and return the result."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Whether the backing CLI is installed and reachable."""
        pass
