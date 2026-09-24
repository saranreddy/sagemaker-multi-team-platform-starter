data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  team_tag = "team:${var.team_name}"

  assume_role_principals = var.enable_smoke_test_assume ? [
    {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    },
    {
      type        = "AWS"
      identifiers = [var.deploying_principal_arn]
    }
    ] : [
    {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  ]
}

# SNS topic for team alerts
resource "aws_sns_topic" "team_alerts" {
  name = "${var.project_name}-${var.team_name}-alerts"

  tags = {
    Name = "${var.project_name}-${var.team_name}-alerts"
    Team = var.team_name
  }
}

resource "aws_sns_topic_subscription" "team_email_alerts" {
  count = length(var.email_alerts)

  topic_arn = aws_sns_topic.team_alerts.arn
  protocol  = "email"
  endpoint  = var.email_alerts[count.index]
}

# S3 bucket for team data with enforced team prefix
resource "aws_s3_bucket" "team_data" {
  bucket = "${var.project_name}-${var.team_name}-data-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "${var.project_name}-${var.team_name}-data"
    Team = var.team_name
  }
}

resource "aws_s3_bucket_versioning" "team_data" {
  bucket = aws_s3_bucket.team_data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "team_data" {
  bucket = aws_s3_bucket.team_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "team_data" {
  bucket = aws_s3_bucket.team_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ECR repository for team's container images
resource "aws_ecr_repository" "team_models" {
  name = "${var.project_name}/${var.team_name}/models"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "${var.project_name}-${var.team_name}-models"
    Team = var.team_name
  }
}

resource "aws_ecr_lifecycle_policy" "team_models" {
  repository = aws_ecr_repository.team_models.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# SageMaker Model Package Group for team's model registry
resource "aws_sagemaker_model_package_group" "team_registry" {
  model_package_group_name        = "${var.project_name}-${var.team_name}-registry"
  model_package_group_description = "Model registry for ${var.team_name} team"

  tags = {
    Name = "${var.project_name}-${var.team_name}-registry"
    Team = var.team_name
  }
}

# IAM role for team's SageMaker execution with ABAC
resource "aws_iam_role" "team_execution" {
  name = "${var.project_name}-${var.team_name}-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      for principal in local.assume_role_principals : {
        Effect = "Allow"
        Principal = {
          (principal.type) = principal.identifiers
        }
        Action = "sts:AssumeRole"
        Condition = principal.type == "Service" ? {
          StringEquals = {
            "aws:RequestedRegion" = var.aws_region
          }
        } : null
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-${var.team_name}-execution-role"
    Team = var.team_name
  }
}

# Attach principal tags to the role for ABAC
resource "aws_iam_role_policy" "team_execution_core" {
  name = "team-execution-core"
  role = aws_iam_role.team_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # S3 access to team's own bucket only
      {
        Sid    = "TeamS3Access"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = aws_s3_bucket.team_data.arn
      },
      {
        Sid    = "TeamS3ObjectAccess"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = "${aws_s3_bucket.team_data.arn}/*"
      },
      # ECR access to team's repository
      {
        Sid    = "TeamECRAccess"
        Effect = "Allow"
        Action = [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:DescribeRepositories",
          "ecr:GetRepositoryPolicy",
          "ecr:ListImages",
          "ecr:DescribeImages"
        ]
        Resource = aws_ecr_repository.team_models.arn
      },
      {
        Sid    = "ECRAuthToken"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken"
        ]
        Resource = "*"
      },
      # SageMaker access with instance type restrictions and team tagging
      {
        Sid    = "SageMakerTrainingAndProcessing"
        Effect = "Allow"
        Action = [
          "sagemaker:CreateTrainingJob",
          "sagemaker:CreateProcessingJob",
          "sagemaker:CreateTransformJob",
          "sagemaker:CreateEndpoint",
          "sagemaker:CreateEndpointConfig",
          "sagemaker:CreateModel"
        ]
        Resource = "*"
        Condition = {
          "ForAllValues:StringEquals" = {
            "sagemaker:InstanceTypes" = var.allowed_instance_types
          }
          StringEquals = {
            "aws:RequestTag/Team" = var.team_name
          }
        }
      },
      {
        Sid    = "SageMakerDescribeAndList"
        Effect = "Allow"
        Action = [
          "sagemaker:Describe*",
          "sagemaker:List*"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/Team" = var.team_name
          }
        }
      },
      {
        Sid    = "SageMakerUpdateDelete"
        Effect = "Allow"
        Action = [
          "sagemaker:UpdateEndpoint",
          "sagemaker:UpdateEndpointWeightsAndCapacities",
          "sagemaker:DeleteEndpoint",
          "sagemaker:DeleteEndpointConfig",
          "sagemaker:DeleteModel",
          "sagemaker:StopTrainingJob",
          "sagemaker:StopProcessingJob",
          "sagemaker:StopTransformJob",
          "sagemaker:InvokeEndpoint"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/Team" = var.team_name
          }
        }
      },
      # Model Package Group access
      {
        Sid    = "ModelPackageGroupAccess"
        Effect = "Allow"
        Action = [
          "sagemaker:CreateModelPackage",
          "sagemaker:UpdateModelPackage",
          "sagemaker:DescribeModelPackage",
          "sagemaker:ListModelPackages",
          "sagemaker:DeleteModelPackage"
        ]
        Resource = aws_sagemaker_model_package_group.team_registry.arn
      },
      # CloudWatch Logs
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/sagemaker/*"
      },
      # CloudWatch Metrics
      {
        Sid    = "CloudWatchMetrics"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "AWS/SageMaker"
          }
        }
      }
    ]
  })
}

# SageMaker Studio user profiles for team members
resource "aws_sagemaker_user_profile" "team_member" {
  for_each = toset(var.members)

  domain_id         = var.studio_domain_id
  user_profile_name = "${var.team_name}-${each.value}"

  user_settings {
    execution_role = aws_iam_role.team_execution.arn
  }

  tags = {
    Name   = "${var.project_name}-${var.team_name}-${each.value}"
    Team   = var.team_name
    Member = each.value
  }
}

# AWS Budget for team with cost allocation tag filter
resource "aws_budgets_budget" "team_monthly" {
  name         = "${var.project_name}-${var.team_name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name = "TagKeyValue"
    values = [
      "Team$${var.team_name}"
    ]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.team_alerts.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.team_alerts.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 90
    threshold_type            = "PERCENTAGE"
    notification_type         = "FORECASTED"
    subscriber_sns_topic_arns = [aws_sns_topic.team_alerts.arn]
  }

  tags = {
    Name = "${var.project_name}-${var.team_name}-budget"
    Team = var.team_name
  }
}
