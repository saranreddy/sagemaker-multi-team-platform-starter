"""
Unit tests for idle resource reaper Lambda function.
"""

import json
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Set AWS region to avoid NoRegionError in tests
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

# Set up environment variables before importing the module
os.environ['REAPER_ENABLED'] = 'false'
os.environ['ENDPOINT_IDLE_DAYS'] = '7'
os.environ['STUDIO_APP_IDLE_HOURS'] = '24'
os.environ['TEAM_SNS_TOPICS'] = json.dumps({'fraud': 'arn:aws:sns:us-east-1:123:fraud', 'recsys': 'arn:aws:sns:us-east-1:123:recsys'})
os.environ['PLATFORM_SNS_TOPIC_ARN'] = 'arn:aws:sns:us-east-1:123:platform'

# Import after setting env vars
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../modules/reaper-lambda/src'))
import reaper


def test_lambda_handler_report_mode():
    """Test lambda handler in report-only mode."""
    mock_sagemaker = MagicMock()
    mock_cloudwatch = MagicMock()
    mock_sns = MagicMock()
    
    old_endpoint_time = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(days=10)
    
    # Mock endpoint listing
    mock_sagemaker.get_paginator.return_value.paginate.return_value = [
        {
            'Endpoints': [
                {
                    'EndpointName': 'fraud-endpoint-1',
                    'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/fraud-endpoint-1',
                    'CreationTime': old_endpoint_time,
                }
            ]
        }
    ]
    
    # Mock tags
    mock_sagemaker.list_tags.return_value = {
        'Tags': [{'Key': 'Team', 'Value': 'fraud'}]
    }
    
    # Mock endpoint config
    mock_sagemaker.describe_endpoint.return_value = {
        'EndpointConfigName': 'test-config'
    }
    mock_sagemaker.describe_endpoint_config.return_value = {
        'ProductionVariants': [{'VariantName': 'AllTraffic'}]
    }
    
    # Mock CloudWatch metrics (zero invocations)
    mock_cloudwatch.get_metric_statistics.return_value = {
        'Datapoints': []
    }
    
    with patch('reaper.get_sagemaker_client', return_value=mock_sagemaker), \
         patch('reaper.get_cloudwatch_client', return_value=mock_cloudwatch), \
         patch('reaper.get_sns_client', return_value=mock_sns):
        
        event = {}
        context = {}
        
        result = reaper.lambda_handler(event, context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert len(body['idle_endpoints']) == 1
        assert body['idle_endpoints'][0]['name'] == 'fraud-endpoint-1'
        assert body['idle_endpoints'][0]['team'] == 'fraud'
        assert len(body['deleted_endpoints']) == 0  # Report-only mode


def test_lambda_handler_delete_mode():
    """Test lambda handler in deletion mode."""
    mock_sagemaker = MagicMock()
    mock_cloudwatch = MagicMock()
    mock_sns = MagicMock()
    
    old_endpoint_time = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(days=10)
    
    # Mock endpoint listing
    mock_sagemaker.get_paginator.return_value.paginate.return_value = [
        {
            'Endpoints': [
                {
                    'EndpointName': 'idle-endpoint',
                    'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/idle-endpoint',
                    'CreationTime': old_endpoint_time,
                }
            ]
        }
    ]
    
    mock_sagemaker.list_tags.return_value = {
        'Tags': [{'Key': 'Team', 'Value': 'fraud'}]
    }
    
    mock_sagemaker.describe_endpoint.return_value = {
        'EndpointConfigName': 'idle-config'
    }
    mock_sagemaker.describe_endpoint_config.return_value = {
        'ProductionVariants': [{'VariantName': 'AllTraffic'}]
    }
    
    mock_cloudwatch.get_metric_statistics.return_value = {
        'Datapoints': []
    }
    
    with patch('reaper.get_sagemaker_client', return_value=mock_sagemaker), \
         patch('reaper.get_cloudwatch_client', return_value=mock_cloudwatch), \
         patch('reaper.get_sns_client', return_value=mock_sns), \
         patch.object(reaper, 'REAPER_ENABLED', True):
        
        result = reaper.lambda_handler({}, {})
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert len(body['idle_endpoints']) == 1
        assert len(body['deleted_endpoints']) == 1
        assert body['deleted_endpoints'][0] == 'idle-endpoint'
        
        # Verify deletion was called
        assert mock_sagemaker.delete_endpoint.called
        assert mock_sagemaker.delete_endpoint_config.called


def test_find_idle_endpoints_with_invocations():
    """Test that endpoints with invocations are not marked as idle."""
    mock_sagemaker = MagicMock()
    mock_cloudwatch = MagicMock()
    
    old_endpoint_time = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(days=10)
    
    mock_sagemaker.get_paginator.return_value.paginate.return_value = [
        {
            'Endpoints': [
                {
                    'EndpointName': 'active-endpoint',
                    'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/active-endpoint',
                    'CreationTime': old_endpoint_time,
                }
            ]
        }
    ]
    
    mock_sagemaker.list_tags.return_value = {
        'Tags': [{'Key': 'Team', 'Value': 'fraud'}]
    }
    
    mock_sagemaker.describe_endpoint.return_value = {
        'EndpointConfigName': 'active-config'
    }
    mock_sagemaker.describe_endpoint_config.return_value = {
        'ProductionVariants': [{'VariantName': 'AllTraffic'}]
    }
    
    # Mock CloudWatch metrics with invocations
    mock_cloudwatch.get_metric_statistics.return_value = {
        'Datapoints': [
            {'Sum': 100.0},
            {'Sum': 200.0}
        ]
    }
    
    with patch('reaper.get_sagemaker_client', return_value=mock_sagemaker), \
         patch('reaper.get_cloudwatch_client', return_value=mock_cloudwatch):
        
        idle_endpoints = reaper.find_idle_endpoints()
        
        assert len(idle_endpoints) == 0


def test_find_idle_endpoints_skips_new_endpoints():
    """Test that new endpoints are skipped even with zero invocations."""
    mock_sagemaker = MagicMock()
    mock_cloudwatch = MagicMock()
    
    # Endpoint created 2 days ago (less than 7 day threshold)
    new_endpoint_time = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(days=2)
    
    mock_sagemaker.get_paginator.return_value.paginate.return_value = [
        {
            'Endpoints': [
                {
                    'EndpointName': 'new-endpoint',
                    'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/new-endpoint',
                    'CreationTime': new_endpoint_time,
                }
            ]
        }
    ]
    
    mock_sagemaker.list_tags.return_value = {
        'Tags': [{'Key': 'Team', 'Value': 'fraud'}]
    }
    
    mock_sagemaker.describe_endpoint.return_value = {
        'EndpointConfigName': 'new-config'
    }
    mock_sagemaker.describe_endpoint_config.return_value = {
        'ProductionVariants': [{'VariantName': 'AllTraffic'}]
    }
    
    mock_cloudwatch.get_metric_statistics.return_value = {
        'Datapoints': []
    }
    
    with patch('reaper.get_sagemaker_client', return_value=mock_sagemaker), \
         patch('reaper.get_cloudwatch_client', return_value=mock_cloudwatch):
        
        idle_endpoints = reaper.find_idle_endpoints()
        
        # Should be skipped because it's too new
        assert len(idle_endpoints) == 0


def test_get_endpoint_invocations():
    """Test getting endpoint invocations from CloudWatch."""
    mock_cloudwatch = MagicMock()
    mock_cloudwatch.get_metric_statistics.return_value = {
        'Datapoints': [
            {'Sum': 50.0},
            {'Sum': 75.0},
            {'Sum': 25.0}
        ]
    }
    
    with patch('reaper.get_cloudwatch_client', return_value=mock_cloudwatch):
        invocations = reaper.get_endpoint_invocations('test-endpoint', 'AllTraffic')
        
        assert invocations == 150
        assert mock_cloudwatch.get_metric_statistics.called
        
        # Check dimensions include both endpoint and variant
        call_args = mock_cloudwatch.get_metric_statistics.call_args[1]
        assert {'Name': 'EndpointName', 'Value': 'test-endpoint'} in call_args['Dimensions']
        assert {'Name': 'VariantName', 'Value': 'AllTraffic'} in call_args['Dimensions']


def test_extract_team_from_profile():
    """Test team extraction from user profile name."""
    assert reaper.extract_team_from_profile('domain-123', 'fraud-alice') == 'fraud'
    assert reaper.extract_team_from_profile('domain-123', 'recsys-bob') == 'recsys'
    assert reaper.extract_team_from_profile('domain-123', 'unknown') == 'unknown'


def test_find_idle_studio_apps_user_profile():
    """Test finding idle Studio apps for user profiles."""
    mock_sagemaker = MagicMock()
    
    old_time = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(hours=30)
    
    mock_sagemaker.get_paginator.return_value.paginate.return_value = [
        {
            'Apps': [
                {
                    'DomainId': 'domain-123',
                    'UserProfileName': 'fraud-alice',
                    'AppType': 'JupyterServer',
                    'AppName': 'default',
                    'Status': 'InService',
                    'SpaceName': None
                }
            ]
        }
    ]
    
    mock_sagemaker.describe_app.return_value = {
        'CreationTime': old_time,
        'LastUserActivityTimestamp': old_time
    }
    
    with patch('reaper.get_sagemaker_client', return_value=mock_sagemaker):
        idle_apps = reaper.find_idle_studio_apps()
        
        assert len(idle_apps) == 1
        assert idle_apps[0]['user_profile_name'] == 'fraud-alice'
        assert idle_apps[0]['team'] == 'fraud'
        assert idle_apps[0]['idle_hours'] > 24


def test_find_idle_studio_apps_space():
    """Test finding idle Studio apps for spaces."""
    mock_sagemaker = MagicMock()
    
    old_time = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(hours=30)
    
    mock_sagemaker.get_paginator.return_value.paginate.return_value = [
        {
            'Apps': [
                {
                    'DomainId': 'domain-123',
                    'SpaceName': 'fraud-space',
                    'AppType': 'JupyterServer',
                    'AppName': 'default',
                    'Status': 'InService',
                    'UserProfileName': None
                }
            ]
        }
    ]
    
    mock_sagemaker.describe_app.return_value = {
        'CreationTime': old_time,
        'LastUserActivityTimestamp': old_time
    }
    
    with patch('reaper.get_sagemaker_client', return_value=mock_sagemaker):
        idle_apps = reaper.find_idle_studio_apps()
        
        assert len(idle_apps) == 1
        assert idle_apps[0]['space_name'] == 'fraud-space'
        assert idle_apps[0]['team'] == 'fraud'


def test_format_notification():
    """Test notification message formatting."""
    findings = {
        'endpoints': [{'name': 'ep1', 'invocations': 0, 'created': datetime.now(datetime.now().astimezone().tzinfo), 'age_days': 10}],
        'apps': [{'app_name': 'app1', 'idle_hours': 30}]
    }
    results = {'deleted_endpoints': [], 'deleted_apps': []}
    
    message = reaper.format_notification('fraud', findings, results)
    
    assert 'fraud' in message
    assert 'ep1' in message
    assert 'app1' in message
    assert 'REPORT-ONLY' in message
