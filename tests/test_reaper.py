"""
Unit tests for idle resource reaper Lambda function.
"""

import json
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

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
    
    # Mock endpoint listing
    mock_sagemaker.get_paginator.return_value.paginate.return_value = [
        {
            'Endpoints': [
                {
                    'EndpointName': 'fraud-endpoint-1',
                    'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/fraud-endpoint-1',
                    'CreationTime': datetime.utcnow() - timedelta(days=10),
                }
            ]
        }
    ]
    
    # Mock tags
    mock_sagemaker.list_tags.return_value = {
        'Tags': [{'Key': 'Team', 'Value': 'fraud'}]
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


def test_find_idle_endpoints_with_invocations():
    """Test that endpoints with invocations are not marked as idle."""
    mock_sagemaker = MagicMock()
    mock_cloudwatch = MagicMock()
    
    mock_sagemaker.get_paginator.return_value.paginate.return_value = [
        {
            'Endpoints': [
                {
                    'EndpointName': 'active-endpoint',
                    'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/active-endpoint',
                    'CreationTime': datetime.utcnow(),
                }
            ]
        }
    ]
    
    mock_sagemaker.list_tags.return_value = {
        'Tags': [{'Key': 'Team', 'Value': 'fraud'}]
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
        invocations = reaper.get_endpoint_invocations('test-endpoint')
        
        assert invocations == 150
        assert mock_cloudwatch.get_metric_statistics.called


def test_extract_team_from_profile():
    """Test team extraction from user profile name."""
    assert reaper.extract_team_from_profile('domain-123', 'fraud-alice') == 'fraud'
    assert reaper.extract_team_from_profile('domain-123', 'recsys-bob') == 'recsys'
    assert reaper.extract_team_from_profile('domain-123', 'unknown') == 'unknown'


def test_format_notification():
    """Test notification message formatting."""
    findings = {
        'endpoints': [{'name': 'ep1', 'invocations': 0, 'created': datetime.utcnow()}],
        'apps': [{'app_name': 'app1', 'idle_hours': 30}]
    }
    results = {'deleted_endpoints': [], 'deleted_apps': []}
    
    message = reaper.format_notification('fraud', findings, results)
    
    assert 'fraud' in message
    assert 'ep1' in message
    assert 'app1' in message
    assert 'REPORT-ONLY' in message
