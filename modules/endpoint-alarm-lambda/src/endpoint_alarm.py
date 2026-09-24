"""
Endpoint Alarm Attachment Lambda Function

Automatically attaches CloudWatch alarms to SageMaker endpoints based on team ownership.
"""

import json
import os
from typing import Dict, Optional

import boto3
from botocore.exceptions import ClientError

# Initialize clients lazily to support mocking in tests
_sagemaker = None
_cloudwatch = None
_sns = None

def get_sagemaker_client():
    global _sagemaker
    if _sagemaker is None:
        _sagemaker = boto3.client('sagemaker')
    return _sagemaker

def get_cloudwatch_client():
    global _cloudwatch
    if _cloudwatch is None:
        _cloudwatch = boto3.client('cloudwatch')
    return _cloudwatch

def get_sns_client():
    global _sns
    if _sns is None:
        _sns = boto3.client('sns')
    return _sns

TEAM_SNS_TOPICS = json.loads(os.environ.get('TEAM_SNS_TOPICS', '{}'))
PLATFORM_SNS_TOPIC_ARN = os.environ.get('PLATFORM_SNS_TOPIC_ARN')


def lambda_handler(event, context):
    """Main Lambda handler for endpoint state change events."""
    print(f"Received event: {json.dumps(event)}")
    
    try:
        # Extract endpoint name from event
        endpoint_name = event['detail']['EndpointName']
        endpoint_status = event['detail']['EndpointStatus']
        
        print(f"Processing endpoint: {endpoint_name} (status={endpoint_status})")
        
        if endpoint_status != 'IN_SERVICE':
            print(f"Endpoint not in service, skipping alarm creation")
            return {'statusCode': 200, 'body': 'Skipped - not in service'}
        
        # Get endpoint details and tags
        team = get_endpoint_team(endpoint_name)
        
        if not team:
            print(f"Endpoint {endpoint_name} has no team tag - alerting platform")
            alert_untagged_endpoint(endpoint_name)
            return {'statusCode': 200, 'body': 'No team tag found'}
        
        # Get appropriate SNS topic
        sns_topic_arn = TEAM_SNS_TOPICS.get(team, PLATFORM_SNS_TOPIC_ARN)
        
        # Create alarms
        create_endpoint_alarms(endpoint_name, team, sns_topic_arn)
        
        print(f"Successfully created alarms for {endpoint_name}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'endpoint': endpoint_name,
                'team': team,
                'alarms_created': True
            })
        }
    
    except Exception as e:
        error_msg = f"Error processing endpoint alarm: {str(e)}"
        print(error_msg)
        send_error_notification(error_msg)
        
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


def get_endpoint_team(endpoint_name: str) -> Optional[str]:
    """Get team tag from endpoint."""
    sagemaker = get_sagemaker_client()
    try:
        endpoint_desc = sagemaker.describe_endpoint(EndpointName=endpoint_name)
        endpoint_arn = endpoint_desc['EndpointArn']
        
        tags_response = sagemaker.list_tags(ResourceArn=endpoint_arn)
        tags = {tag['Key']: tag['Value'] for tag in tags_response['Tags']}
        
        return tags.get('Team')
    
    except Exception as e:
        print(f"Error getting endpoint team: {e}")
        return None


def create_endpoint_alarms(endpoint_name: str, team: str, sns_topic_arn: str):
    """Create standard CloudWatch alarms for the endpoint."""
    cloudwatch = get_cloudwatch_client()
    sagemaker = get_sagemaker_client()
    
    # Get endpoint variants for dimensions
    try:
        endpoint_desc = sagemaker.describe_endpoint(EndpointName=endpoint_name)
        endpoint_config_name = endpoint_desc['EndpointConfigName']
        
        endpoint_config = sagemaker.describe_endpoint_config(EndpointConfigName=endpoint_config_name)
        variants = [variant['VariantName'] for variant in endpoint_config['ProductionVariants']]
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'AccessDeniedException':
            print(f"ERROR: AccessDenied getting endpoint config for {endpoint_name}: {e}")
            raise
        print(f"Error getting endpoint variants: {e}, using AllTraffic as fallback")
        variants = ['AllTraffic']
    except Exception as e:
        print(f"Error getting endpoint variants: {e}, using AllTraffic as fallback")
        variants = ['AllTraffic']
    
    for variant_name in variants:
        # Alarm 1: Model invocation 5XX errors
        try:
            cloudwatch.put_metric_alarm(
                AlarmName=f"{endpoint_name}-{variant_name}-5xx-errors",
                AlarmDescription=f"Alert on 5XX errors for {endpoint_name}/{variant_name} (team={team})",
                ActionsEnabled=True,
                AlarmActions=[sns_topic_arn],
                MetricName='Invocation5XXErrors',
                Namespace='AWS/SageMaker',
                Statistic='Sum',
                Dimensions=[
                    {'Name': 'EndpointName', 'Value': endpoint_name},
                    {'Name': 'VariantName', 'Value': variant_name}
                ],
                Period=300,  # 5 minutes
                EvaluationPeriods=1,
                Threshold=1.0,
                ComparisonOperator='GreaterThanThreshold',
                TreatMissingData='notBreaching',
                Tags=[
                    {'Key': 'Team', 'Value': team},
                    {'Key': 'ManagedBy', 'Value': 'terraform'},
                    {'Key': 'EndpointName', 'Value': endpoint_name},
                    {'Key': 'VariantName', 'Value': variant_name}
                ]
            )
            print(f"Created 5XX error alarm for {endpoint_name}/{variant_name}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'AccessDeniedException':
                print(f"ERROR: AccessDenied creating 5XX alarm for {endpoint_name}: {e}")
                raise
            print(f"Error creating 5XX alarm: {e}")
        except Exception as e:
            print(f"Error creating 5XX alarm: {e}")
        
        # Alarm 2: Model latency (p90) - in microseconds
        try:
            cloudwatch.put_metric_alarm(
                AlarmName=f"{endpoint_name}-{variant_name}-high-latency",
                AlarmDescription=f"Alert on high latency for {endpoint_name}/{variant_name} (team={team})",
                ActionsEnabled=True,
                AlarmActions=[sns_topic_arn],
                MetricName='ModelLatency',
                Namespace='AWS/SageMaker',
                ExtendedStatistic='p90',
                Dimensions=[
                    {'Name': 'EndpointName', 'Value': endpoint_name},
                    {'Name': 'VariantName', 'Value': variant_name}
                ],
                Period=300,  # 5 minutes
                EvaluationPeriods=2,
                Threshold=10000000.0,  # 10 seconds in microseconds
                ComparisonOperator='GreaterThanThreshold',
                TreatMissingData='notBreaching',
                Tags=[
                    {'Key': 'Team', 'Value': team},
                    {'Key': 'ManagedBy', 'Value': 'terraform'},
                    {'Key': 'EndpointName', 'Value': endpoint_name},
                    {'Key': 'VariantName', 'Value': variant_name}
                ]
            )
            print(f"Created latency alarm for {endpoint_name}/{variant_name}")
        except Exception as e:
            print(f"Error creating latency alarm: {e}")
        
        # Alarm 3: Invocation drop (optional - detects if traffic suddenly drops)
        try:
            cloudwatch.put_metric_alarm(
                AlarmName=f"{endpoint_name}-{variant_name}-invocation-drop",
                AlarmDescription=f"Alert on invocation drop for {endpoint_name}/{variant_name} (team={team})",
                ActionsEnabled=True,
                AlarmActions=[sns_topic_arn],
                MetricName='Invocations',
                Namespace='AWS/SageMaker',
                Statistic='Sum',
                Dimensions=[
                    {'Name': 'EndpointName', 'Value': endpoint_name},
                    {'Name': 'VariantName', 'Value': variant_name}
                ],
                Period=3600,  # 1 hour
                EvaluationPeriods=1,
                Threshold=1.0,
                ComparisonOperator='LessThanThreshold',
                TreatMissingData='notBreaching',
                Tags=[
                    {'Key': 'Team', 'Value': team},
                    {'Key': 'ManagedBy', 'Value': 'terraform'},
                    {'Key': 'EndpointName', 'Value': endpoint_name},
                    {'Key': 'VariantName', 'Value': variant_name}
                ]
            )
            print(f"Created invocation drop alarm for {endpoint_name}/{variant_name}")
        except Exception as e:
            print(f"Error creating invocation drop alarm: {e}")


def alert_untagged_endpoint(endpoint_name: str):
    """Alert platform team about untagged endpoint."""
    sns = get_sns_client()
    try:
        message = f"""Untagged SageMaker Endpoint Detected

Endpoint Name: {endpoint_name}

This endpoint was created without a Team tag. Standard monitoring alarms 
cannot be automatically attached. Please tag the endpoint with the appropriate
team or manually configure monitoring.

Recommendation: Add a 'Team' tag with the team name to enable automatic 
alarm attachment.
"""
        
        sns.publish(
            TopicArn=PLATFORM_SNS_TOPIC_ARN,
            Subject=f"[WARNING] Untagged Endpoint: {endpoint_name}",
            Message=message
        )
        print(f"Sent untagged endpoint alert to platform topic")
    
    except Exception as e:
        print(f"Error sending untagged alert: {e}")


def send_error_notification(error_msg: str):
    """Send error notification to platform topic."""
    sns = get_sns_client()
    try:
        sns.publish(
            TopicArn=PLATFORM_SNS_TOPIC_ARN,
            Subject="[ERROR] Endpoint Alarm Attachment Failed",
            Message=f"The endpoint alarm attachment Lambda encountered an error:\n\n{error_msg}"
        )
    except Exception as e:
        print(f"Error sending error notification: {e}")
