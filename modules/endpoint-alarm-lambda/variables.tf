variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "team_sns_topics" {
  description = "Map of team names to SNS topic ARNs"
  type        = map(string)
}

variable "platform_sns_topic_arn" {
  description = "SNS topic ARN for platform alerts"
  type        = string
}
