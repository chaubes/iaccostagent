resource "azurerm_resource_group" "prod" {
  name     = "prod-rg"
  location = "eastus"
}

resource "azurerm_linux_virtual_machine" "batch" {
  count                 = 3
  name                  = "batch-${count.index}"
  resource_group_name   = azurerm_resource_group.prod.name
  location              = azurerm_resource_group.prod.location
  size                  = "Standard_D32s_v5"   # oversized
  admin_username        = "azureuser"
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

resource "azurerm_linux_virtual_machine" "legacy" {
  name                  = "legacy"
  resource_group_name   = azurerm_resource_group.prod.name
  location              = azurerm_resource_group.prod.location
  size                  = "Standard_D2"   # older gen (no _v2/3/4/5 suffix)
  admin_username        = "azureuser"
  network_interface_ids = []

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }
}

resource "azurerm_managed_disk" "data" {
  count                = 5
  name                 = "data-${count.index}"
  location             = azurerm_resource_group.prod.location
  resource_group_name  = azurerm_resource_group.prod.name
  storage_account_type = "Standard_LRS"   # HDD, flag for tier upgrade
  create_option        = "Empty"
  disk_size_gb         = 500
}

resource "azurerm_nat_gateway" "nat_a" {
  name                = "nat-a"
  location            = azurerm_resource_group.prod.location
  resource_group_name = azurerm_resource_group.prod.name
  sku_name            = "Standard"
}

resource "azurerm_nat_gateway" "nat_b" {
  name                = "nat-b"
  location            = azurerm_resource_group.prod.location
  resource_group_name = azurerm_resource_group.prod.name
  sku_name            = "Standard"
}

resource "azurerm_nat_gateway" "nat_c" {
  name                = "nat-c"
  location            = azurerm_resource_group.prod.location
  resource_group_name = azurerm_resource_group.prod.name
  sku_name            = "Standard"
}

resource "azurerm_public_ip" "idle" {
  name                = "idle-pip"
  resource_group_name = azurerm_resource_group.prod.name
  location            = azurerm_resource_group.prod.location
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_postgresql_server" "legacy_db" {
  name                         = "legacy-db"
  location                     = azurerm_resource_group.prod.location
  resource_group_name          = azurerm_resource_group.prod.name
  sku_name                     = "GP_Gen5_2"
  version                      = "11"
  administrator_login          = "app"
  administrator_login_password = "changeme"
  ssl_enforcement_enabled      = true
}
