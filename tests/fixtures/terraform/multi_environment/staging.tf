resource "aws_instance" "staging_api" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.medium"
  tags = {
    Name        = "staging-api"
    Environment = "staging"
  }
}

resource "aws_db_instance" "staging_db" {
  allocated_storage    = 50
  engine               = "postgres"
  engine_version       = "15.4"
  instance_class       = "db.t4g.medium"
  username             = "app"
  password             = "changeme"
  skip_final_snapshot  = true
}
