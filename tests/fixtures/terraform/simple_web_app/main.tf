resource "aws_instance" "web" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.large"
  tags = {
    Name        = "web-server"
    Environment = "production"
  }
}

resource "aws_db_instance" "database" {
  allocated_storage    = 100
  engine               = "postgres"
  engine_version       = "15.4"
  instance_class       = "db.r5.2xlarge"
  username             = "app"
  password             = "changeme"
  skip_final_snapshot  = true
  tags = {
    Name        = "app-database"
    Environment = "production"
  }
}

resource "aws_s3_bucket" "assets" {
  bucket = "my-app-assets"
}

resource "aws_lb" "app" {
  name               = "app-lb"
  load_balancer_type = "application"
}
