resource "aws_instance" "api" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.small"
  tags = {
    Name        = "api"
    Environment = "production"
  }
}

resource "aws_db_instance" "database" {
  allocated_storage    = 50
  engine               = "postgres"
  engine_version       = "15.4"
  instance_class       = "db.t4g.medium"
  username             = "app"
  password             = "changeme"
  skip_final_snapshot  = true
}

resource "aws_ebs_volume" "data" {
  availability_zone = "us-east-1a"
  type              = "gp3"
  size              = 100
}

resource "aws_s3_bucket" "assets" {
  bucket = "well-optimized-assets"
}
