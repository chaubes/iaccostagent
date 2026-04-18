resource "google_compute_instance" "api" {
  name         = "api"
  machine_type = "e2-standard-2"
  zone         = "us-central1-a"

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
    }
  }

  network_interface {
    network = "default"
    access_config {}
  }
}

resource "google_compute_disk" "data" {
  name = "data-disk"
  type = "pd-balanced"
  zone = "us-central1-a"
  size = 100
}

resource "google_sql_database_instance" "database" {
  name             = "app-db"
  database_version = "POSTGRES_15"
  region           = "us-central1"

  settings {
    tier = "db-custom-2-7680"
  }
}
