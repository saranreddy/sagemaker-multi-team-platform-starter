output "execution_role_arn" {
  description = "ARN of the team's SageMaker execution role"
  value       = aws_iam_role.team_execution.arn
}

output "s3_bucket_name" {
  description = "Name of the team's S3 bucket"
  value       = aws_s3_bucket.team_data.id
}

output "ecr_repository_url" {
  description = "URL of the team's ECR repository"
  value       = aws_ecr_repository.team_models.repository_url
}

output "model_package_group_name" {
  description = "Name of the team's model package group"
  value       = aws_sagemaker_model_package_group.team_registry.model_package_group_name
}

output "sns_topic_arn" {
  description = "ARN of the team's SNS alert topic"
  value       = aws_sns_topic.team_alerts.arn
}

output "budget_name" {
  description = "Name of the team's AWS Budget"
  value       = aws_budgets_budget.team_monthly.name
}

output "user_profile_names" {
  description = "List of SageMaker Studio user profile names for this team"
  value       = [for profile in aws_sagemaker_user_profile.team_member : profile.user_profile_name]
}
