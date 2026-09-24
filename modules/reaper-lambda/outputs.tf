output "function_name" {
  description = "Name of the reaper Lambda function"
  value       = aws_lambda_function.reaper.function_name
}

output "function_arn" {
  description = "ARN of the reaper Lambda function"
  value       = aws_lambda_function.reaper.arn
}
