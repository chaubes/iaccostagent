resource "aws_instance" "legacy" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "m4.large"
  tags = {
    Name        = "legacy-app"
    Environment = "production"
  }
}

resource "aws_ebs_volume" "old_storage" {
  availability_zone = "us-east-1a"
  type              = "gp2"
  size              = 200
}

resource "aws_eip" "idle" {
  domain = "vpc"
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

resource "aws_s3_bucket" "logs" {
  bucket = "noisy-logs-bucket"
}
