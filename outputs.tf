output "studio_domain_id" {
  description = "SageMaker Studio domain ID"
  value       = aws_sagemaker_domain.main.id
}

output "studio_domain_url" {
  description = "SageMaker Studio domain URL"
  value       = aws_sagemaker_domain.main.url
}

output "team_details" {
  description = "Details for each team including role ARNs, S3 buckets, and SNS topics"
  value = {
    for team_name, team_module in module.team : team_name => {
      execution_role_arn  = team_module.execution_role_arn
      s3_bucket           = team_module.s3_bucket_name
      ecr_repository_url  = team_module.ecr_repository_url
      model_package_group = team_module.model_package_group_name
      sns_topic_arn       = team_module.sns_topic_arn
      budget_name         = team_module.budget_name
      user_profile_names  = team_module.user_profile_names
    }
  }
}

output "reaper_lambda_function_name" {
  description = "Name of the idle resource reaper Lambda function"
  value       = module.reaper_lambda.function_name
}

output "endpoint_alarm_lambda_function_name" {
  description = "Name of the endpoint alarm attachment Lambda function"
  value       = module.endpoint_alarm_lambda.function_name
}

output "platform_sns_topic_arn" {
  description = "SNS topic for platform-level alerts"
  value       = aws_sns_topic.platform_alerts.arn
}
