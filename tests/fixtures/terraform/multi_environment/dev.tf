resource "aws_instance" "dev_api" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.small"
  tags = {
    Name        = "dev-api"
    Environment = "dev"
  }
}

resource "aws_db_instance" "dev_db" {
  allocated_storage    = 20
  engine               = "postgres"
  engine_version       = "15.4"
  instance_class       = "db.t4g.small"
  username             = "app"
  password             = "changeme"
  skip_final_snapshot  = true
}
