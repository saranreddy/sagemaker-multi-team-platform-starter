provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      ManagedBy   = "terraform"
      Project     = "sagemaker-multi-team-platform"
      Environment = var.environment
    }
  }
}
