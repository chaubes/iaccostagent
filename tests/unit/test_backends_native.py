"""
Tests for the three reference cloud-native backends.

These use respx to intercept the outbound HTTPS calls so we never actually
hit Azure / AWS / GCP during unit tests. Each test verifies:
  - handler dispatch picks up the right resource types
  - JSON parsing produces a CostEstimate with sensible totals
  - unsupported resource types are skipped silently rather than erroring
"""

from pathlib import Path

import pytest
import respx

from iaccostagent.backends.aws_pricing import AWSPricingBackend
from iaccostagent.backends.azure_retail import AzureRetailPricesBackend
from iaccostagent.backends.gcp_catalog import GCPBackendError, GCPCatalogBackend
from iaccostagent.backends.registry import get_backend, list_backends


class TestRegistry:
    def test_all_shipped_backends_registered(self) -> None:
        names = list_backends()
        assert "infracost" in names
        assert "openinfraquote" in names
        assert "aws-pricing" in names
        assert "azure-retail" in names
        assert "gcp-catalog" in names

    def test_get_backend_by_name(self) -> None:
        b = get_backend("azure-retail")
        assert isinstance(b, AzureRetailPricesBackend)

    def test_unknown_backend_raises_keyerror(self) -> None:
        with pytest.raises(KeyError, match="Unknown cost backend"):
            get_backend("made-up")


class TestAzureRetailBackend:
    async def test_prices_a_linux_vm(self, tmp_path: Path) -> None:
        (tmp_path / "main.tf").write_text(
            """
resource "azurerm_resource_group" "verify" {
  name     = "v"
  location = "eastus"
}
resource "azurerm_linux_virtual_machine" "v" {
  name                = "v"
  resource_group_name = azurerm_resource_group.verify.name
  location            = azurerm_resource_group.verify.location
  size                = "Standard_B1s"
  admin_username      = "x"
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
        )

        vm_response = {
            "Items": [
                {
                    "armSkuName": "Standard_B1s",
                    "productName": "Virtual Machines BS Series",
                    "meterName": "B1s",
                    "retailPrice": 0.012,
                    "armRegionName": "eastus",
                }
            ],
            "NextPageLink": None,
        }

        with respx.mock(base_url="https://prices.azure.com") as mock:
            mock.get("/api/retail/prices").respond(200, json=vm_response)
            estimate = await AzureRetailPricesBackend().estimate(str(tmp_path), region="eastus")

        assert estimate.backend == "azure-retail"
        assert estimate.provider.value == "azure"
        # One VM + resource group (ignored) → one ResourceCost.
        assert len(estimate.resource_costs) == 1
        assert estimate.total_monthly_cost == pytest.approx(0.012 * 730, rel=1e-3)

    async def test_managed_disk_uses_tier_sku(self, tmp_path: Path) -> None:
        """100 GB StandardSSD should round up to E10 tier pricing, not per-GB."""
        (tmp_path / "main.tf").write_text(
            """
resource "azurerm_managed_disk" "d" {
  name                 = "d"
  location             = "eastus"
  resource_group_name  = "rg"
  storage_account_type = "StandardSSD_LRS"
  create_option        = "Empty"
  disk_size_gb         = 100
}
"""
        )

        # Retail API response the real endpoint returns for an E10 LRS SKU lookup.
        e10_response = {
            "Items": [
                {
                    "skuName": "E10 LRS",
                    "productName": "Standard SSD Managed Disks",
                    "meterName": "E10 LRS Disks",
                    "unitOfMeasure": "1/Month",
                    "retailPrice": 9.60,
                    "armRegionName": "eastus",
                }
            ],
            "NextPageLink": None,
        }

        with respx.mock(base_url="https://prices.azure.com") as mock:
            mock.get("/api/retail/prices").respond(200, json=e10_response)
            estimate = await AzureRetailPricesBackend().estimate(str(tmp_path), region="eastus")

        assert len(estimate.resource_costs) == 1
        assert estimate.total_monthly_cost == pytest.approx(9.60, rel=1e-3)
        assert "E10" in estimate.resource_costs[0].cost_components[0].name

    async def test_unsupported_types_are_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "main.tf").write_text(
            """
resource "azurerm_storage_account" "s" {
  name                = "s"
  location            = "eastus"
  resource_group_name = "rg"
  account_tier        = "Standard"
  account_replication_type = "LRS"
}
"""
        )
        with respx.mock(base_url="https://prices.azure.com"):
            estimate = await AzureRetailPricesBackend().estimate(str(tmp_path), region="eastus")
        # Storage account not in HANDLERS — should produce zero cost entries, no exception.
        assert estimate.resource_costs == []
        assert estimate.total_monthly_cost == 0.0


class TestAWSPricingBackend:
    async def test_prices_an_ec2_instance(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Isolate the on-disk cache so we don't reuse a prior download.
        monkeypatch.setenv("IACCOSTAGENT_CACHE_DIR", str(tmp_path / "cache"))
        (tmp_path / "main.tf").write_text(
            """
resource "aws_instance" "v" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.micro"
}
"""
        )

        # Minimal shape of the AWS EC2 price-list JSON the backend expects.
        price_json = {
            "products": {
                "SKU-T3MICRO": {
                    "attributes": {
                        "instanceType": "t3.micro",
                        "location": "US East (N. Virginia)",
                        "operatingSystem": "Linux",
                        "tenancy": "Shared",
                        "preInstalledSw": "NA",
                        "capacitystatus": "Used",
                    },
                },
            },
            "terms": {
                "OnDemand": {
                    "SKU-T3MICRO": {
                        "SKU-T3MICRO.offer": {
                            "priceDimensions": {
                                "dim1": {"pricePerUnit": {"USD": "0.0104"}},
                            },
                        },
                    },
                },
            },
        }

        with respx.mock() as mock:
            mock.get(
                "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.json"
            ).respond(200, json=price_json)
            estimate = await AWSPricingBackend().estimate(str(tmp_path), region="us-east-1")

        assert estimate.backend == "aws-pricing"
        assert estimate.provider.value == "aws"
        assert len(estimate.resource_costs) == 1
        assert estimate.total_monthly_cost == pytest.approx(0.0104 * 730, rel=1e-3)


class TestGCPCatalogBackend:
    async def test_missing_api_key_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        (tmp_path / "main.tf").write_text(
            'resource "google_compute_instance" "v" {\n'
            '  name         = "v"\n'
            '  machine_type = "e2-small"\n'
            '  zone         = "us-central1-a"\n'
            '  boot_disk { initialize_params { image = "debian-cloud/debian-12" } }\n'
            '  network_interface { network = "default" }\n'
            "}\n"
        )
        with pytest.raises(GCPBackendError, match="GOOGLE_API_KEY"):
            await GCPCatalogBackend().estimate(str(tmp_path), region="us-central1")

    async def test_is_available_reflects_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = GCPCatalogBackend()
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        assert backend.is_available() is False
        monkeypatch.setenv("GOOGLE_API_KEY", "AIza-test")
        assert backend.is_available() is True

    async def test_prices_an_n2_instance(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "AIza-test")
        (tmp_path / "main.tf").write_text(
            'resource "google_compute_instance" "v" {\n'
            '  name         = "v"\n'
            '  machine_type = "n2-standard-4"\n'
            '  zone         = "us-central1-a"\n'
            '  boot_disk { initialize_params { image = "debian-cloud/debian-12" } }\n'
            '  network_interface { network = "default" }\n'
            "}\n"
        )

        # Two SKUs: one core, one ram — both match n2 + us-central1 on-demand.
        skus_response = {
            "skus": [
                {
                    "description": "N2 Instance Core running in Americas",
                    "category": {"resourceFamily": "Compute", "usageType": "OnDemand"},
                    "serviceRegions": ["us-central1"],
                    "pricingInfo": [{"pricingExpression": {"tieredRates": [{"unitPrice": {"nanos": 100_000_000}}]}}],
                },
                {
                    "description": "N2 Instance Ram running in Americas",
                    "category": {"resourceFamily": "Compute", "usageType": "OnDemand"},
                    "serviceRegions": ["us-central1"],
                    "pricingInfo": [{"pricingExpression": {"tieredRates": [{"unitPrice": {"nanos": 20_000_000}}]}}],
                },
            ]
        }

        with respx.mock(base_url="https://cloudbilling.googleapis.com") as mock:
            mock.get("/v1/services/6F81-5844-456A/skus").respond(200, json=skus_response)
            estimate = await GCPCatalogBackend().estimate(str(tmp_path), region="us-central1")

        assert estimate.backend == "gcp-catalog"
        assert estimate.provider.value == "gcp"
        assert len(estimate.resource_costs) == 1
        # Combined nanos: 100M + 20M = 120M → $0.12/hr × 730 = $87.60/month
        assert estimate.total_monthly_cost == pytest.approx(0.12 * 730, rel=1e-3)
