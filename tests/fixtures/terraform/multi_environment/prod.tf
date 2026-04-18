resource "aws_instance" "prod_api" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "m5.large"
  tags = {
    Name        = "prod-api"
    Environment = "prod"
  }
}

resource "aws_db_instance" "prod_db" {
  allocated_storage    = 200
  engine               = "postgres"
  engine_version       = "15.4"
  instance_class       = "db.r5.xlarge"
  username             = "app"
  password             = "changeme"
  skip_final_snapshot  = true
  multi_az             = true
}
