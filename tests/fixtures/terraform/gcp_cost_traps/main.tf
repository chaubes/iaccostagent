resource "google_compute_instance" "legacy" {
  name         = "legacy"
  machine_type = "n1-standard-4"      # older generation
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

resource "google_compute_instance" "whale" {
  name         = "whale"
  machine_type = "n2-standard-96"     # oversized
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

resource "google_compute_disk" "logs" {
  count = 3
  name  = "logs-${count.index}"
  type  = "pd-standard"               # HDD, flag for tier upgrade
  zone  = "us-central1-a"
  size  = 200
}

resource "google_compute_address" "idle" {
  name         = "idle-static"
  region       = "us-central1"
  address_type = "EXTERNAL"
}

resource "google_compute_router_nat" "nat_a" {
  name                               = "nat-a"
  router                             = "router-a"
  region                             = "us-central1"
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_router_nat" "nat_b" {
  name                               = "nat-b"
  router                             = "router-b"
  region                             = "us-central1"
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_router_nat" "nat_c" {
  name                               = "nat-c"
  router                             = "router-c"
  region                             = "us-central1"
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}
