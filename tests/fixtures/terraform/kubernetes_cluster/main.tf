resource "aws_eks_cluster" "main" {
  name     = "prod-cluster"
  role_arn = "arn:aws:iam::123456789012:role/eks-cluster-role"

  vpc_config {
    subnet_ids = ["subnet-aaa", "subnet-bbb"]
  }
}

resource "aws_eks_node_group" "workers" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "workers"
  node_role_arn   = "arn:aws:iam::123456789012:role/eks-node-role"
  subnet_ids      = ["subnet-aaa", "subnet-bbb"]
  instance_types  = ["m5.xlarge"]

  scaling_config {
    desired_size = 3
    min_size     = 2
    max_size     = 10
  }
}

resource "aws_lb" "ingress" {
  name               = "eks-ingress"
  load_balancer_type = "network"
}
