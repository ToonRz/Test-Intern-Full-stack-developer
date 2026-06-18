terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.0"
    }
  }

  backend "s3" {
    bucket = "log-management-terraform-state"
    key    = "prod/terraform.tfstate"
    region = "ap-southeast-1"
    dynamodb_table = "terraform-state-lock"
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

# ── VPC ────────────────────────────────────────────────────────────────────
module "vpc" {
  source = "./modules/vpc"

  environment = var.environment
  vpc_cidr    = var.vpc_cidr

  tags = {
    Project     = "log-management"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ── RDS PostgreSQL ─────────────────────────────────────────────────────────
module "rds" {
  source = "./modules/rds"

  environment           = var.environment
  vpc_id                = module.vpc.vpc_id
  private_subnet_ids    = module.vpc.private_subnet_ids
  db_instance_class     = var.db_instance_class
  db_allocated_storage  = var.db_allocated_storage
  db_name               = "logs"
  db_username           = var.db_username
  db_password            = var.db_password

  tags = {
    Project     = "log-management"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ── EKS Cluster ────────────────────────────────────────────────────────────
module "eks" {
  source = "./modules/eks"

  environment         = var.environment
  vpc_id              = module.vpc.vpc_id
  private_subnet_ids  = module.vpc.private_subnet_ids
  eks_cluster_version = var.eks_cluster_version
  eks_instance_types  = var.eks_instance_types

  tags = {
    Project     = "log-management"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ── Helm Deployment ────────────────────────────────────────────────────────
resource "helm_release" "log_management" {
  name       = "log-management"
  repository = "file://../../helm/log-management"
  chart      = "../../helm/log-management"
  namespace  = "log-management"

  set {
    name  = "backend.image.repository"
    value = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/log-management-backend"
  }
  set {
    name  = "frontend.image.repository"
    value = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/log-management-frontend"
  }
  set {
    name  = "backend.env.DATABASE_URL"
    value = "postgresql+asyncpg://${var.db_username}:${var.db_password}@${module.rds.db_endpoint}/logs"
  }
  set {
    name  = "redis.enabled"
    value = "true"
  }

  depends_on = [module.eks, module.rds]
}
