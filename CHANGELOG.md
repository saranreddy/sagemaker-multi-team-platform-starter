# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-24

### Added
- Initial release of SageMaker Multi-Team Platform starter
- Reusable team module for self-service onboarding
- Per-team SageMaker Studio user profiles in shared domain
- Isolated team resources:
  - Dedicated S3 buckets with versioning and encryption
  - ECR repositories for container images
  - SageMaker Model Package Groups for model registry
  - SNS topics for team-specific alerts
- Team isolation via ABAC (Attribute-Based Access Control) with team tags
- Instance type restrictions per team via SageMaker condition keys
- Cost guardrails:
  - AWS Budgets per team with cost allocation tag filtering
  - Studio idle auto-shutdown via lifecycle configuration
  - Scheduled reaper Lambda (Python 3.11) for idle resource cleanup
  - Report-only and deletion modes for reaper
- Default monitoring:
  - EventBridge rule for endpoint state changes
  - Automatic CloudWatch alarm attachment for new endpoints
  - Team-routed alerts (5XX errors, latency p90, invocation drop)
  - Platform alerts for untagged resources
- Comprehensive testing:
  - pytest unit tests for reaper Lambda
  - pytest unit tests for endpoint alarm Lambda
  - Smoke test script validating isolation
- Infrastructure tooling:
  - Makefile with doctor, init, plan, apply, smoke, destroy targets
  - Doctor script checking Terraform, AWS CLI, Python prerequisites
  - Pre-destroy script for Studio cleanup ordering
  - CI workflow with fmt, validate, tflint, pytest, and plan jobs
- Documentation:
  - Comprehensive README with architecture, onboarding flow, cost table
  - Example tfvars with two demo teams
  - Known limitations and when-not-to-use guidance

### Fixed (Live Test)
- Fixed Terraform version parsing in `doctor.sh` for TF 1.5.7 (uses `jq -r .terraform_version` with fallback)
- Fixed IAM trust policy rendering to omit `Condition` key when null (avoided `MalformedPolicyDocument` error)
- Added root account caller support for smoke tests (automatically creates temporary IAM user for assume-role tests)
- Fixed smoke test error handling for assume-role failures (explicit capture and error messages)
- Fixed EventBridge pattern to support both `InService` and `IN_SERVICE` endpoint statuses
- Fixed Lambda status normalization to handle both formats case-insensitively
- Removed duplicate `ml.t3.medium` in `SageMakerCreateApp` instance types list using `distinct()`
- Added managed CloudWatch log groups for Lambda functions with 14-day retention
- Added alarm cleanup to `pre-destroy.sh` script (deletes alarms created by endpoint alarm Lambda)
- Fixed `make clean` to preserve `terraform.tfstate*` files (prevents orphaned live infrastructure)

### Technical Details
- Terraform >= 1.5.7, AWS provider ~> 5.0
- Default VPC detection with override support
- EFS retention set to Delete for clean teardown
- Committed .terraform.lock.hcl for reproducibility
- Python 3.11 Lambdas with proper IAM scoping
- EventBridge and CloudWatch scheduling
