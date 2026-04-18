"""Abstract base class for Terraform input parsers."""

from abc import ABC, abstractmethod

from iaccostagent.models.schemas import CloudProvider, TerraformResource


class BaseTerraformParser(ABC):
    """
    Base contract for parsers that turn some Terraform input into resources.

    Each concrete parser — HCL walker, plan-JSON reader — produces the same
    normalized list of TerraformResource, so downstream nodes don't care
    which format the user supplied.
    """

    @abstractmethod
    def parse(self, path: str) -> list[TerraformResource]:
        """
        Parse the input at `path` and return resource objects.

        Raises:
            FileNotFoundError: If the path does not exist.
            ValueError: If the content is malformed.
        """
        pass

    @abstractmethod
    def can_parse(self, path: str) -> bool:
        """Whether this parser recognizes the input at `path`."""
        pass


PROVIDER_PREFIX_MAP: dict[str, CloudProvider] = {
    "aws_": CloudProvider.AWS,
    "azurerm_": CloudProvider.AZURE,
    "azuread_": CloudProvider.AZURE,
    "google_": CloudProvider.GCP,
}


def infer_provider(resource_type: str) -> CloudProvider | None:
    """Infer cloud provider from a Terraform resource type string."""
    for prefix, provider in PROVIDER_PREFIX_MAP.items():
        if resource_type.startswith(prefix):
            return provider
    return None
