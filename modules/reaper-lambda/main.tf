data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_region" "current" {}

# Package Lambda function
data "archive_file" "reaper_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/src"
  output_path = "${path.module}/lambda_package.zip"
}

# IAM role for Lambda
resource "aws_iam_role" "reaper_lambda" {
  name = "${var.project_name}-reaper-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-reaper-lambda-role"
  }
}

resource "aws_iam_role_policy_attachment" "reaper_lambda_basic" {
  role       = aws_iam_role.reaper_lambda.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "reaper_lambda_permissions" {
  name = "reaper-permissions"
  role = aws_iam_role.reaper_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SageMakerReadAccess"
        Effect = "Allow"
        Action = [
          "sagemaker:ListEndpoints",
          "sagemaker:DescribeEndpoint",
          "sagemaker:DescribeEndpointConfig",
          "sagemaker:ListApps",
          "sagemaker:DescribeApp",
          "sagemaker:ListUserProfiles",
          "sagemaker:DescribeUserProfile",
          "sagemaker:ListTags"
        ]
        Resource = "*"
      },
      {
        Sid    = "SageMakerDeleteAccess"
        Effect = "Allow"
        Action = [
          "sagemaker:DeleteEndpoint",
          "sagemaker:DeleteEndpointConfig",
          "sagemaker:DeleteApp"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchMetrics"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics"
        ]
        Resource = "*"
      },
      {
        Sid    = "SNSPublish"
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = concat(
          values(var.team_sns_topics),
          [var.platform_sns_topic_arn]
        )
      }
    ]
  })
}

# Lambda function
resource "aws_lambda_function" "reaper" {
  filename         = data.archive_file.reaper_lambda.output_path
  function_name    = "${var.project_name}-idle-resource-reaper"
  role             = aws_iam_role.reaper_lambda.arn
  handler          = "reaper.lambda_handler"
  source_code_hash = data.archive_file.reaper_lambda.output_base64sha256
  runtime          = "python3.11"
  timeout          = 300
  memory_size      = 256

  environment {
    variables = {
      REAPER_ENABLED         = var.reaper_enabled ? "true" : "false"
      ENDPOINT_IDLE_DAYS     = tostring(var.endpoint_idle_days)
      STUDIO_APP_IDLE_HOURS  = tostring(var.studio_app_idle_hours)
      TEAM_SNS_TOPICS        = jsonencode(var.team_sns_topics)
      PLATFORM_SNS_TOPIC_ARN = var.platform_sns_topic_arn
    }
  }

  tags = {
    Name = "${var.project_name}-reaper"
  }
}

# CloudWatch Event Rule to trigger Lambda daily
resource "aws_cloudwatch_event_rule" "reaper_schedule" {
  name                = "${var.project_name}-reaper-schedule"
  description         = "Trigger idle resource reaper daily"
  schedule_expression = "cron(0 2 * * ? *)" # 2 AM UTC daily

  tags = {
    Name = "${var.project_name}-reaper-schedule"
  }
}

resource "aws_cloudwatch_event_target" "reaper_lambda" {
  rule      = aws_cloudwatch_event_rule.reaper_schedule.name
  target_id = "ReaperLambda"
  arn       = aws_lambda_function.reaper.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.reaper.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.reaper_schedule.arn
}
