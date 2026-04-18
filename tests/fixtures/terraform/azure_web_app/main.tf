resource "azurerm_resource_group" "web" {
  name     = "web-rg"
  location = "eastus"
}

resource "azurerm_linux_virtual_machine" "api" {
  name                = "api-vm"
  resource_group_name = azurerm_resource_group.web.name
  location            = azurerm_resource_group.web.location
  size                = "Standard_D2s_v5"
  admin_username      = "azureuser"
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

resource "azurerm_managed_disk" "data" {
  name                 = "data-disk"
  location             = azurerm_resource_group.web.location
  resource_group_name  = azurerm_resource_group.web.name
  storage_account_type = "StandardSSD_LRS"
  create_option        = "Empty"
  disk_size_gb         = 100
}

resource "azurerm_postgresql_flexible_server" "database" {
  name                = "app-db"
  resource_group_name = azurerm_resource_group.web.name
  location            = azurerm_resource_group.web.location
  version             = "15"
  administrator_login = "app"
  sku_name            = "GP_Standard_D2s_v3"
  storage_mb          = 32768
}
