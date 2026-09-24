data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_vpc" "default" {
  count   = var.vpc_id == "" ? 1 : 0
  default = true
}

data "aws_subnets" "default" {
  count = length(var.subnet_ids) == 0 ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [local.vpc_id]
  }
}

locals {
  vpc_id                  = var.vpc_id != "" ? var.vpc_id : data.aws_vpc.default[0].id
  subnet_ids              = length(var.subnet_ids) > 0 ? var.subnet_ids : data.aws_subnets.default[0].ids
  deploying_principal_arn = var.deploying_principal_arn != "" ? var.deploying_principal_arn : data.aws_caller_identity.current.arn
}

# Platform SNS topic for untagged resources and system alerts
resource "aws_sns_topic" "platform_alerts" {
  name = "${var.project_name}-platform-alerts"

  tags = {
    Name = "${var.project_name}-platform-alerts"
  }
}

resource "aws_sns_topic_policy" "platform_alerts_budgets" {
  arn = aws_sns_topic.platform_alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowBudgetsPublish"
        Effect = "Allow"
        Principal = {
          Service = "budgets.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.platform_alerts.arn
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

resource "aws_sns_topic_subscription" "platform_alerts" {
  count = length(var.platform_alert_emails)

  topic_arn = aws_sns_topic.platform_alerts.arn
  protocol  = "email"
  endpoint  = var.platform_alert_emails[count.index]
}

# SageMaker Studio Domain
resource "aws_sagemaker_domain" "main" {
  domain_name = "${var.project_name}-${var.environment}"
  auth_mode   = "IAM"
  vpc_id      = local.vpc_id
  subnet_ids  = local.subnet_ids

  default_user_settings {
    execution_role = aws_iam_role.studio_default.arn

    jupyter_server_app_settings {
      default_resource_spec {
        instance_type = "system"
      }
    }

    kernel_gateway_app_settings {
      default_resource_spec {
        instance_type = "ml.t3.medium"
      }
    }
  }

  default_space_settings {
    execution_role = aws_iam_role.studio_default.arn
  }

  app_network_access_type = var.studio_network_access_type

  retention_policy {
    home_efs_file_system = "Delete"
  }

  tags = {
    Name = "${var.project_name}-domain"
  }
}

# Default Studio execution role (fallback only - minimal permissions)
resource "aws_iam_role" "studio_default" {
  name = "${var.project_name}-studio-default-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "sagemaker.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-studio-default-role"
  }
}

# Minimal policy for default role - users should use team roles
resource "aws_iam_role_policy" "studio_default_minimal" {
  name = "minimal-studio-access"
  role = aws_iam_role.studio_default.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "MinimalStudioAccess"
        Effect = "Allow"
        Action = [
          "sagemaker:DescribeDomain",
          "sagemaker:DescribeUserProfile",
          "sagemaker:ListTags"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogsForStudio"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/sagemaker/*"
      }
    ]
  })
}

# Create team resources
module "team" {
  source   = "./modules/team"
  for_each = var.teams

  team_name                = each.key
  members                  = each.value.members
  email_alerts             = each.value.email_alerts
  monthly_budget_usd       = each.value.monthly_budget_usd
  allowed_instance_types   = each.value.allowed_instance_types
  project_name             = var.project_name
  environment              = var.environment
  aws_region               = var.aws_region
  studio_domain_id         = aws_sagemaker_domain.main.id
  enable_smoke_test_assume = var.enable_smoke_test_assume
  deploying_principal_arn  = local.deploying_principal_arn
}

# Idle resource reaper Lambda
module "reaper_lambda" {
  source = "./modules/reaper-lambda"

  project_name           = var.project_name
  environment            = var.environment
  reaper_enabled         = var.reaper_enabled
  endpoint_idle_days     = var.reaper_endpoint_idle_days
  studio_app_idle_hours  = var.reaper_studio_app_idle_hours
  team_sns_topics        = { for name, team in module.team : name => team.sns_topic_arn }
  platform_sns_topic_arn = aws_sns_topic.platform_alerts.arn
}

# Endpoint alarm attachment Lambda
module "endpoint_alarm_lambda" {
  source = "./modules/endpoint-alarm-lambda"

  project_name           = var.project_name
  environment            = var.environment
  team_sns_topics        = { for name, team in module.team : name => team.sns_topic_arn }
  platform_sns_topic_arn = aws_sns_topic.platform_alerts.arn
}
