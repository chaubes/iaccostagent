resource "aws_instance" "app" {
  count         = 5
  instance_type = "m5.4xlarge"
  ami           = "ami-0c55b159cbfafe1f0"
  tags = {
    Name        = "app-server"
    Environment = "production"
  }
}

resource "aws_db_instance" "db" {
  instance_class       = "db.r5.4xlarge"
  allocated_storage    = 1000
  engine               = "postgres"
  engine_version       = "15.4"
  username             = "app"
  password             = "changeme"
  skip_final_snapshot  = true
}

resource "aws_nat_gateway" "nat_a" {
  allocation_id = "eipalloc-aaa"
  subnet_id     = "subnet-aaa"
}

resource "aws_nat_gateway" "nat_b" {
  allocation_id = "eipalloc-bbb"
  subnet_id     = "subnet-bbb"
}

resource "aws_nat_gateway" "nat_c" {
  allocation_id = "eipalloc-ccc"
  subnet_id     = "subnet-ccc"
}

resource "aws_ebs_volume" "data" {
  count             = 10
  availability_zone = "us-east-1a"
  type              = "gp2"
  size              = 500
}
