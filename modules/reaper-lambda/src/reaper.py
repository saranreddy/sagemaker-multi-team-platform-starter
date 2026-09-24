"""
Idle Resource Reaper Lambda Function

Scans for idle SageMaker endpoints and Studio apps and either reports or deletes them.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

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

REAPER_ENABLED = os.environ.get('REAPER_ENABLED', 'false').lower() == 'true'
ENDPOINT_IDLE_DAYS = int(os.environ.get('ENDPOINT_IDLE_DAYS', '7'))
STUDIO_APP_IDLE_HOURS = int(os.environ.get('STUDIO_APP_IDLE_HOURS', '24'))
TEAM_SNS_TOPICS = json.loads(os.environ.get('TEAM_SNS_TOPICS', '{}'))
PLATFORM_SNS_TOPIC_ARN = os.environ.get('PLATFORM_SNS_TOPIC_ARN')


def lambda_handler(event, context):
    """Main Lambda handler."""
    print(f"Starting idle resource reaper (enabled={REAPER_ENABLED})")
    
    results = {
        'idle_endpoints': [],
        'idle_apps': [],
        'deleted_endpoints': [],
        'deleted_apps': [],
        'errors': []
    }
    
    try:
        # Check idle endpoints
        idle_endpoints = find_idle_endpoints()
        results['idle_endpoints'] = idle_endpoints
        
        # Check idle Studio apps
        idle_apps = find_idle_studio_apps()
        results['idle_apps'] = idle_apps
        
        # Process idle resources
        if REAPER_ENABLED:
            results['deleted_endpoints'] = delete_idle_endpoints(idle_endpoints)
            results['deleted_apps'] = delete_idle_apps(idle_apps)
        
        # Send notifications
        send_notifications(results)
        
    except Exception as e:
        error_msg = f"Error in reaper: {str(e)}"
        print(error_msg)
        results['errors'].append(error_msg)
        send_error_notification(error_msg)
    
    print(f"Reaper completed: {json.dumps(results, default=str)}")
    return {
        'statusCode': 200,
        'body': json.dumps(results, default=str)
    }


def find_idle_endpoints() -> List[Dict]:
    """Find endpoints with zero invocations over the idle period."""
    idle_endpoints = []
    sagemaker = get_sagemaker_client()
    
    try:
        paginator = sagemaker.get_paginator('list_endpoints')
        
        for page in paginator.paginate(StatusEquals='InService'):
            for endpoint in page['Endpoints']:
                endpoint_name = endpoint['EndpointName']
                creation_time = endpoint['CreationTime']
                
                # Skip endpoints younger than the idle window
                age_days = (datetime.now(creation_time.tzinfo) - creation_time).days
                if age_days < ENDPOINT_IDLE_DAYS:
                    print(f"Skipping {endpoint_name}: only {age_days} days old (threshold {ENDPOINT_IDLE_DAYS})")
                    continue
                
                # Get tags to determine team ownership
                try:
                    tags_response = sagemaker.list_tags(
                        ResourceArn=endpoint['EndpointArn']
                    )
                    tags = {tag['Key']: tag['Value'] for tag in tags_response['Tags']}
                    team = tags.get('Team', 'unknown')
                except ClientError as e:
                    print(f"Error getting tags for {endpoint_name}: {e}")
                    team = 'unknown'
                
                # Get variants for metric query
                variants = get_endpoint_variants(endpoint_name)
                
                # Check invocation metrics across all variants
                total_invocations = 0
                for variant in variants:
                    invocations = get_endpoint_invocations(endpoint_name, variant)
                    if invocations >= 0:  # Only count if we got valid data
                        total_invocations += invocations
                
                if total_invocations == 0:
                    idle_endpoints.append({
                        'name': endpoint_name,
                        'team': team,
                        'created': creation_time,
                        'invocations': total_invocations,
                        'age_days': age_days
                    })
                    print(f"Found idle endpoint: {endpoint_name} (team={team}, age={age_days}d)")
    
    except Exception as e:
        print(f"Error listing endpoints: {e}")
    
    return idle_endpoints


def get_endpoint_variants(endpoint_name: str) -> List[str]:
    """Get variant names for an endpoint."""
    sagemaker = get_sagemaker_client()
    try:
        endpoint_desc = sagemaker.describe_endpoint(EndpointName=endpoint_name)
        endpoint_config_name = endpoint_desc['EndpointConfigName']
        
        endpoint_config = sagemaker.describe_endpoint_config(EndpointConfigName=endpoint_config_name)
        return [variant['VariantName'] for variant in endpoint_config['ProductionVariants']]
    except Exception as e:
        print(f"Error getting variants for {endpoint_name}: {e}")
        return ['AllTraffic']  # Fallback


def get_endpoint_invocations(endpoint_name: str, variant_name: str) -> int:
    """Get total invocations for an endpoint variant over the idle period."""
    cloudwatch = get_cloudwatch_client()
    try:
        end_time = datetime.now(datetime.now().astimezone().tzinfo)
        start_time = end_time - timedelta(days=ENDPOINT_IDLE_DAYS)
        
        response = cloudwatch.get_metric_statistics(
            Namespace='AWS/SageMaker',
            MetricName='Invocations',
            Dimensions=[
                {'Name': 'EndpointName', 'Value': endpoint_name},
                {'Name': 'VariantName', 'Value': variant_name}
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,  # 1 day
            Statistics=['Sum']
        )
        
        total = sum(dp['Sum'] for dp in response['Datapoints'])
        return int(total)
    
    except Exception as e:
        print(f"Error getting metrics for {endpoint_name}/{variant_name}: {e}")
        return -1  # Return -1 to indicate error (don't delete on error)


def find_idle_studio_apps() -> List[Dict]:
    """Find Studio apps that have been idle."""
    idle_apps = []
    sagemaker = get_sagemaker_client()
    
    try:
        # List all apps
        paginator = sagemaker.get_paginator('list_apps')
        
        for page in paginator.paginate():
            for app in page['Apps']:
                if app['Status'] != 'InService':
                    continue
                
                domain_id = app['DomainId']
                user_profile_name = app['UserProfileName']
                app_type = app['AppType']
                app_name = app['AppName']
                
                # Get app details
                try:
                    app_details = sagemaker.describe_app(
                        DomainId=domain_id,
                        UserProfileName=user_profile_name,
                        AppType=app_type,
                        AppName=app_name
                    )
                    
                    # Check if app is idle based on last modified time
                    last_modified = app_details.get('LastUserActivityTimestamp', 
                                                   app_details.get('CreationTime'))
                    
                    if last_modified:
                        age_hours = (datetime.now(last_modified.tzinfo) - last_modified).total_seconds() / 3600
                        
                        if age_hours > STUDIO_APP_IDLE_HOURS:
                            # Extract team from user profile tags
                            team = extract_team_from_profile(domain_id, user_profile_name)
                            
                            idle_apps.append({
                                'domain_id': domain_id,
                                'user_profile_name': user_profile_name,
                                'app_type': app_type,
                                'app_name': app_name,
                                'team': team,
                                'idle_hours': int(age_hours)
                            })
                            print(f"Found idle app: {app_name} (idle={int(age_hours)}h, team={team})")
                
                except Exception as e:
                    print(f"Error describing app {app_name}: {e}")
    
    except Exception as e:
        print(f"Error listing apps: {e}")
    
    return idle_apps


def extract_team_from_profile(domain_id: str, user_profile_name: str) -> str:
    """Extract team name from user profile name or tags."""
    try:
        # User profiles are named {team}-{username}, so extract team prefix
        if '-' in user_profile_name:
            return user_profile_name.split('-')[0]
        return 'unknown'
    except Exception:
        return 'unknown'


def delete_idle_endpoints(idle_endpoints: List[Dict]) -> List[str]:
    """Delete idle endpoints and their configs."""
    deleted = []
    sagemaker = get_sagemaker_client()
    
    for endpoint in idle_endpoints:
        try:
            endpoint_name = endpoint['name']
            
            # Get endpoint config name before deletion
            endpoint_details = sagemaker.describe_endpoint(EndpointName=endpoint_name)
            config_name = endpoint_details['EndpointConfigName']
            
            # Delete endpoint
            sagemaker.delete_endpoint(EndpointName=endpoint_name)
            print(f"Deleted endpoint: {endpoint_name}")
            
            # Delete endpoint config
            try:
                sagemaker.delete_endpoint_config(EndpointConfigName=config_name)
                print(f"Deleted endpoint config: {config_name}")
            except ClientError as e:
                print(f"Error deleting config {config_name}: {e}")
            
            deleted.append(endpoint_name)
        
        except Exception as e:
            print(f"Error deleting endpoint {endpoint['name']}: {e}")
    
    return deleted


def delete_idle_apps(idle_apps: List[Dict]) -> List[str]:
    """Delete idle Studio apps."""
    deleted = []
    sagemaker = get_sagemaker_client()
    
    for app in idle_apps:
        try:
            sagemaker.delete_app(
                DomainId=app['domain_id'],
                UserProfileName=app['user_profile_name'],
                AppType=app['app_type'],
                AppName=app['app_name']
            )
            print(f"Deleted app: {app['app_name']}")
            deleted.append(app['app_name'])
        
        except Exception as e:
            print(f"Error deleting app {app['app_name']}: {e}")
    
    return deleted


def send_notifications(results: Dict):
    """Send notifications to appropriate teams."""
    sns = get_sns_client()
    # Group findings by team
    team_findings = {}
    
    for endpoint in results['idle_endpoints']:
        team = endpoint['team']
        if team not in team_findings:
            team_findings[team] = {'endpoints': [], 'apps': []}
        team_findings[team]['endpoints'].append(endpoint)
    
    for app in results['idle_apps']:
        team = app['team']
        if team not in team_findings:
            team_findings[team] = {'endpoints': [], 'apps': []}
        team_findings[team]['apps'].append(app)
    
    # Send notification to each team
    for team, findings in team_findings.items():
        topic_arn = TEAM_SNS_TOPICS.get(team, PLATFORM_SNS_TOPIC_ARN)
        
        message = format_notification(team, findings, results)
        
        try:
            sns.publish(
                TopicArn=topic_arn,
                Subject=f"{'[ACTION TAKEN]' if REAPER_ENABLED else '[REPORT]'} Idle SageMaker Resources - {team}",
                Message=message
            )
            print(f"Sent notification to {team} at {topic_arn}")
        except Exception as e:
            print(f"Error sending notification to {team}: {e}")


def format_notification(team: str, findings: Dict, results: Dict) -> str:
    """Format notification message."""
    mode = "DELETION MODE" if REAPER_ENABLED else "REPORT-ONLY MODE"
    
    message = f"""SageMaker Idle Resource Reaper - {mode}
Team: {team}

"""
    
    if findings['endpoints']:
        message += f"Idle Endpoints ({len(findings['endpoints'])}):\n"
        for ep in findings['endpoints']:
            status = "DELETED" if ep['name'] in results.get('deleted_endpoints', []) else "FOUND"
            message += f"  - [{status}] {ep['name']} (0 invocations in {ENDPOINT_IDLE_DAYS} days)\n"
        message += "\n"
    
    if findings['apps']:
        message += f"Idle Studio Apps ({len(findings['apps'])}):\n"
        for app in findings['apps']:
            status = "DELETED" if app['app_name'] in results.get('deleted_apps', []) else "FOUND"
            message += f"  - [{status}] {app['app_name']} (idle for {app['idle_hours']} hours)\n"
        message += "\n"
    
    if not REAPER_ENABLED:
        message += "\nNOTE: Reaper is in REPORT-ONLY mode. No resources were deleted.\n"
        message += "To enable deletion, set reaper_enabled=true in Terraform.\n"
    
    return message


def send_error_notification(error_msg: str):
    """Send error notification to platform topic."""
    sns = get_sns_client()
    try:
        sns.publish(
            TopicArn=PLATFORM_SNS_TOPIC_ARN,
            Subject="[ERROR] SageMaker Reaper Failed",
            Message=f"The idle resource reaper encountered an error:\n\n{error_msg}"
        )
    except Exception as e:
        print(f"Error sending error notification: {e}")
