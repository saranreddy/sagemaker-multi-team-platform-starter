variable "team_name" {
  description = "Name of the data science team"
  type        = string
}

variable "members" {
  description = "List of team member usernames"
  type        = list(string)
}

variable "email_alerts" {
  description = "Email addresses for team alerts"
  type        = list(string)
  default     = []
}

variable "monthly_budget_usd" {
  description = "Monthly AWS budget for this team in USD"
  type        = number
}

variable "allowed_instance_types" {
  description = "List of allowed SageMaker instance types for this team"
  type        = list(string)
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "studio_domain_id" {
  description = "SageMaker Studio domain ID"
  type        = string
}

variable "enable_smoke_test_assume" {
  description = "Allow deploying principal to assume team role for smoke testing"
  type        = bool
  default     = false
}

variable "deploying_principal_arn" {
  description = "ARN of principal deploying this infrastructure"
  type        = string
}
