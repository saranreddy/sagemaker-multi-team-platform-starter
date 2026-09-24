output "function_name" {
  description = "Name of the endpoint alarm Lambda function"
  value       = aws_lambda_function.endpoint_alarm.function_name
}

output "function_arn" {
  description = "ARN of the endpoint alarm Lambda function"
  value       = aws_lambda_function.endpoint_alarm.arn
}
