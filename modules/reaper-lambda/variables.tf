variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "reaper_enabled" {
  description = "If true, delete idle resources. If false, only report."
  type        = bool
}

variable "endpoint_idle_days" {
  description = "Days with zero invocations before endpoint is idle"
  type        = number
}

variable "studio_app_idle_hours" {
  description = "Hours idle before Studio app is flagged"
  type        = number
}

variable "team_sns_topics" {
  description = "Map of team names to SNS topic ARNs"
  type        = map(string)
}

variable "platform_sns_topic_arn" {
  description = "SNS topic ARN for platform alerts"
  type        = string
}
