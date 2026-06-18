variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "eks_cluster_version" { type = string }
variable "eks_instance_types" { type = list(string) }
variable "tags" { type = map(string) }

data "aws_iam_role" "eks_nodes" {
  name = "AmazonEKSNodeRole"
}

# EKS Cluster
resource "aws_eks_cluster" "main" {
  name     = "${var.environment}-eks-logmgmt"
  role_arn = data.aws_iam_role.eks_nodes.arn
  version  = var.eks_cluster_version

  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = ["0.0.0.0/0"]
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_policy,
    aws_iam_role_policy_attachment.eks_service_policy,
  ]

  tags = merge(var.tags, { Name = "${var.environment}-eks-cluster" })
}

# EKS Node Group
resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${var.environment}-nodes"
  node_role_arn   = data.aws_iam_role.eks_nodes.arn
  subnet_ids      = var.private_subnet_ids
  instance_types  = var.eks_instance_types
  scaling_config {
    min_size     = 2
    max_size     = 6
    desired_size = 3
  }

  labels = {
    role = "log-management"
  }

  tags = merge(var.tags, { Name = "${var.environment}-eks-nodes" })
}

# IAM Role Policies (minimum for EKS)
data "aws_iam_policy_document" "eks_assume_role" {
  statement {
    effect = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eks_cluster_role" {
  name = "${var.environment}-eks-cluster-role"
  assume_role_policy = data.aws_iam_policy_document.eks_assume_role.json
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.eks_cluster_role.name
}

resource "aws_iam_role_policy_attachment" "eks_service_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSServicePolicy"
  role       = aws_iam_role.eks_cluster_role.name
}

output "eks_cluster_name" {
  value = aws_eks_cluster.main.name
}

output "eks_cluster_endpoint" {
  value = aws_eks_cluster.main.endpoint
}

output "eks_cluster_ca" {
  value = aws_eks_cluster.main.certificate_authority[0].data
}
