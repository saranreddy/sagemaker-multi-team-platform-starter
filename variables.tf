variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name used in resource naming"
  type        = string
  default     = "sagemaker-platform"
}

variable "vpc_id" {
  description = "VPC ID for SageMaker Studio domain. If not provided, uses default VPC."
  type        = string
  default     = ""
}

variable "subnet_ids" {
  description = "Subnet IDs for SageMaker Studio domain. If not provided, uses default VPC subnets."
  type        = list(string)
  default     = []
}

variable "teams" {
  description = "Map of data science teams. Each team gets isolated resources and cost tracking."
  type = map(object({
    members            = list(string)
    email_alerts       = optional(list(string), [])
    monthly_budget_usd = optional(number, 1000)
    allowed_instance_types = optional(list(string), [
      "ml.t3.medium",
      "ml.t3.large",
      "ml.m5.xlarge",
      "ml.m5.2xlarge",
      "ml.c5.xlarge",
      "ml.c5.2xlarge"
    ])
  }))

  validation {
    condition     = length(var.teams) > 0
    error_message = "At least one team must be defined."
  }

  validation {
    condition     = alltrue([for name, team in var.teams : length(team.members) > 0])
    error_message = "Each team must have at least one member."
  }
}

variable "reaper_enabled" {
  description = "If true, reaper Lambda will DELETE idle resources. If false, only reports findings to team SNS."
  type        = bool
  default     = false
}

variable "reaper_endpoint_idle_days" {
  description = "Number of days with zero invocations before an endpoint is considered idle"
  type        = number
  default     = 7
}

variable "reaper_studio_app_idle_hours" {
  description = "Number of hours idle before a Studio app is considered for cleanup"
  type        = number
  default     = 24
}

variable "enable_smoke_test_assume" {
  description = "If true, allows the deploying principal to assume team roles for smoke testing. Set to false in production."
  type        = bool
  default     = true
}

variable "deploying_principal_arn" {
  description = "ARN of the IAM principal deploying this infrastructure (for smoke test assume role). Leave empty to auto-detect."
  type        = string
  default     = ""
}

variable "studio_network_access_type" {
  description = "Network access type for Studio: PublicInternetOnly (default, needs no NAT) or VpcOnly (requires NAT gateway)"
  type        = string
  default     = "PublicInternetOnly"

  validation {
    condition     = contains(["PublicInternetOnly", "VpcOnly"], var.studio_network_access_type)
    error_message = "studio_network_access_type must be PublicInternetOnly or VpcOnly"
  }
}

variable "platform_alert_emails" {
  description = "Email addresses for platform-level alerts (untagged resources, system issues)"
  type        = list(string)
  default     = []
}
