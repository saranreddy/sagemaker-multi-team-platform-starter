"""
Unit tests for endpoint alarm attachment Lambda function.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

# Set up environment variables before importing the module
os.environ['TEAM_SNS_TOPICS'] = json.dumps({'fraud': 'arn:aws:sns:us-east-1:123:fraud', 'recsys': 'arn:aws:sns:us-east-1:123:recsys'})
os.environ['PLATFORM_SNS_TOPIC_ARN'] = 'arn:aws:sns:us-east-1:123:platform'

# Import after setting env vars
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../modules/endpoint-alarm-lambda/src'))
import endpoint_alarm


@pytest.fixture
def endpoint_event():
    """Sample EventBridge event for endpoint state change."""
    return {
        'detail-type': 'SageMaker Endpoint State Change',
        'source': 'aws.sagemaker',
        'detail': {
            'EndpointName': 'fraud-model-endpoint',
            'EndpointStatus': 'InService',
            'EndpointArn': 'arn:aws:sagemaker:us-east-1:123456789:endpoint/fraud-model-endpoint'
        }
    }


def test_lambda_handler_with_team_tag(endpoint_event):
    """Test lambda handler with properly tagged endpoint."""
    mock_sagemaker = MagicMock()
    mock_cloudwatch = MagicMock()
    mock_sns = MagicMock()
    
    # Mock endpoint description and tags
    mock_sagemaker.describe_endpoint.return_value = {
        'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/fraud-model-endpoint'
    }
    mock_sagemaker.list_tags.return_value = {
        'Tags': [{'Key': 'Team', 'Value': 'fraud'}]
    }
    
    with patch('endpoint_alarm.get_sagemaker_client', return_value=mock_sagemaker), \
         patch('endpoint_alarm.get_cloudwatch_client', return_value=mock_cloudwatch), \
         patch('endpoint_alarm.get_sns_client', return_value=mock_sns):
        
        result = endpoint_alarm.lambda_handler(endpoint_event, {})
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['endpoint'] == 'fraud-model-endpoint'
        assert body['team'] == 'fraud'
        assert body['alarms_created'] is True
        
        # Should create 3 alarms
        assert mock_cloudwatch.put_metric_alarm.call_count == 3


def test_lambda_handler_without_team_tag(endpoint_event):
    """Test lambda handler with untagged endpoint."""
    mock_sagemaker = MagicMock()
    mock_cloudwatch = MagicMock()
    mock_sns = MagicMock()
    
    # Mock endpoint without team tag
    mock_sagemaker.describe_endpoint.return_value = {
        'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/fraud-model-endpoint'
    }
    mock_sagemaker.list_tags.return_value = {
        'Tags': []
    }
    
    with patch('endpoint_alarm.get_sagemaker_client', return_value=mock_sagemaker), \
         patch('endpoint_alarm.get_cloudwatch_client', return_value=mock_cloudwatch), \
         patch('endpoint_alarm.get_sns_client', return_value=mock_sns):
        
        result = endpoint_alarm.lambda_handler(endpoint_event, {})
        
        assert result['statusCode'] == 200
        # Should alert platform team about untagged endpoint
        assert mock_sns.publish.called
        call_args = mock_sns.publish.call_args
        assert 'Untagged' in call_args[1]['Subject']


def test_lambda_handler_not_in_service(endpoint_event):
    """Test that alarms are not created for endpoints not in service."""
    mock_sagemaker = MagicMock()
    mock_cloudwatch = MagicMock()
    mock_sns = MagicMock()
    
    endpoint_event['detail']['EndpointStatus'] = 'Creating'
    
    with patch('endpoint_alarm.get_sagemaker_client', return_value=mock_sagemaker), \
         patch('endpoint_alarm.get_cloudwatch_client', return_value=mock_cloudwatch), \
         patch('endpoint_alarm.get_sns_client', return_value=mock_sns):
        
        result = endpoint_alarm.lambda_handler(endpoint_event, {})
        
        assert result['statusCode'] == 200
        # Should not create any alarms
        assert not mock_cloudwatch.put_metric_alarm.called


def test_get_endpoint_team():
    """Test team extraction from endpoint tags."""
    mock_sagemaker = MagicMock()
    mock_sagemaker.describe_endpoint.return_value = {
        'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/test'
    }
    mock_sagemaker.list_tags.return_value = {
        'Tags': [
            {'Key': 'Team', 'Value': 'fraud'},
            {'Key': 'Environment', 'Value': 'prod'}
        ]
    }
    
    with patch('endpoint_alarm.get_sagemaker_client', return_value=mock_sagemaker):
        team = endpoint_alarm.get_endpoint_team('test-endpoint')
        
        assert team == 'fraud'


def test_get_endpoint_team_no_tag():
    """Test team extraction when no team tag exists."""
    mock_sagemaker = MagicMock()
    mock_sagemaker.describe_endpoint.return_value = {
        'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/test'
    }
    mock_sagemaker.list_tags.return_value = {
        'Tags': []
    }
    
    with patch('endpoint_alarm.get_sagemaker_client', return_value=mock_sagemaker):
        team = endpoint_alarm.get_endpoint_team('test-endpoint')
        
        assert team is None


def test_create_endpoint_alarms():
    """Test alarm creation for endpoint."""
    mock_cloudwatch = MagicMock()
    
    endpoint_name = 'test-endpoint'
    team = 'fraud'
    sns_topic = 'arn:aws:sns:us-east-1:123:fraud'
    
    with patch('endpoint_alarm.get_cloudwatch_client', return_value=mock_cloudwatch):
        endpoint_alarm.create_endpoint_alarms(endpoint_name, team, sns_topic)
        
        # Should create 3 alarms: 5XX errors, latency, invocation drop
        assert mock_cloudwatch.put_metric_alarm.call_count == 3
        
        # Check that alarms have correct properties
        calls = mock_cloudwatch.put_metric_alarm.call_args_list
        
        # Check 5XX error alarm
        alarm_5xx = calls[0][1]
        assert '5xx-errors' in alarm_5xx['AlarmName']
        assert alarm_5xx['MetricName'] == 'ModelInvocation5XXErrors'
        assert alarm_5xx['AlarmActions'] == [sns_topic]
        assert any(tag['Key'] == 'Team' and tag['Value'] == team for tag in alarm_5xx['Tags'])
        
        # Check latency alarm
        alarm_latency = calls[1][1]
        assert 'high-latency' in alarm_latency['AlarmName']
        assert alarm_latency['MetricName'] == 'ModelLatency'
        assert alarm_latency['ExtendedStatistic'] == 'p90'
        
        # Check invocation drop alarm
        alarm_drop = calls[2][1]
        assert 'invocation-drop' in alarm_drop['AlarmName']
        assert alarm_drop['MetricName'] == 'Invocations'


def test_alert_untagged_endpoint():
    """Test platform alerting for untagged endpoint."""
    mock_sns = MagicMock()
    
    with patch('endpoint_alarm.get_sns_client', return_value=mock_sns):
        endpoint_alarm.alert_untagged_endpoint('untagged-endpoint')
        
        assert mock_sns.publish.called
        call_args = mock_sns.publish.call_args
        assert call_args[1]['TopicArn'] == 'arn:aws:sns:us-east-1:123:platform'
        assert 'Untagged' in call_args[1]['Subject']
        assert 'untagged-endpoint' in call_args[1]['Message']
