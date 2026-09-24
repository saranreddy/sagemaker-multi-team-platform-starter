data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_region" "current" {}

# Package Lambda function
data "archive_file" "endpoint_alarm_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/src"
  output_path = "${path.module}/lambda_package.zip"
}

# IAM role for Lambda
resource "aws_iam_role" "endpoint_alarm_lambda" {
  name = "${var.project_name}-endpoint-alarm-lambda-role"

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
    Name = "${var.project_name}-endpoint-alarm-lambda-role"
  }
}

resource "aws_iam_role_policy_attachment" "endpoint_alarm_lambda_basic" {
  role       = aws_iam_role.endpoint_alarm_lambda.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "endpoint_alarm_lambda_permissions" {
  name = "endpoint-alarm-permissions"
  role = aws_iam_role.endpoint_alarm_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SageMakerReadAccess"
        Effect = "Allow"
        Action = [
          "sagemaker:DescribeEndpoint",
          "sagemaker:ListTags"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchAlarms"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DescribeAlarms",
          "cloudwatch:DeleteAlarms"
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
resource "aws_lambda_function" "endpoint_alarm" {
  filename         = data.archive_file.endpoint_alarm_lambda.output_path
  function_name    = "${var.project_name}-endpoint-alarm-attacher"
  role             = aws_iam_role.endpoint_alarm_lambda.arn
  handler          = "endpoint_alarm.lambda_handler"
  source_code_hash = data.archive_file.endpoint_alarm_lambda.output_base64sha256
  runtime          = "python3.11"
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      TEAM_SNS_TOPICS        = jsonencode(var.team_sns_topics)
      PLATFORM_SNS_TOPIC_ARN = var.platform_sns_topic_arn
    }
  }

  tags = {
    Name = "${var.project_name}-endpoint-alarm"
  }
}

# EventBridge rule for SageMaker endpoint events
resource "aws_cloudwatch_event_rule" "endpoint_state_change" {
  name        = "${var.project_name}-endpoint-state-change"
  description = "Trigger on SageMaker endpoint creation/update"

  event_pattern = jsonencode({
    source      = ["aws.sagemaker"]
    detail-type = ["SageMaker Endpoint State Change"]
    detail = {
      EndpointStatus = ["InService"]
    }
  })

  tags = {
    Name = "${var.project_name}-endpoint-events"
  }
}

resource "aws_cloudwatch_event_target" "endpoint_alarm_lambda" {
  rule      = aws_cloudwatch_event_rule.endpoint_state_change.name
  target_id = "EndpointAlarmLambda"
  arn       = aws_lambda_function.endpoint_alarm.arn
}

resource "aws_lambda_permission" "allow_eventbridge_endpoint" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.endpoint_alarm.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.endpoint_state_change.arn
}
