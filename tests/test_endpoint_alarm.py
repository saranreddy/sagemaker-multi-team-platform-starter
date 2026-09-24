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
            'EndpointStatus': 'IN_SERVICE',
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
        'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/fraud-model-endpoint',
        'EndpointConfigName': 'fraud-model-config'
    }
    mock_sagemaker.describe_endpoint_config.return_value = {
        'ProductionVariants': [
            {'VariantName': 'AllTraffic'}
        ]
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
        
        # Should create 3 alarms per variant (1 variant = 3 alarms)
        assert mock_cloudwatch.put_metric_alarm.call_count == 3


def test_lambda_handler_without_team_tag(endpoint_event):
    """Test lambda handler with untagged endpoint."""
    mock_sagemaker = MagicMock()
    mock_cloudwatch = MagicMock()
    mock_sns = MagicMock()
    
    # Mock endpoint without team tag
    mock_sagemaker.describe_endpoint.return_value = {
        'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/fraud-model-endpoint',
        'EndpointConfigName': 'fraud-model-config'
    }
    mock_sagemaker.describe_endpoint_config.return_value = {
        'ProductionVariants': [
            {'VariantName': 'AllTraffic'}
        ]
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
    mock_sagemaker = MagicMock()
    mock_cloudwatch = MagicMock()
    
    # Mock variant lookup
    mock_sagemaker.describe_endpoint.return_value = {
        'EndpointConfigName': 'test-config'
    }
    mock_sagemaker.describe_endpoint_config.return_value = {
        'ProductionVariants': [
            {'VariantName': 'variant-1'},
            {'VariantName': 'variant-2'}
        ]
    }
    
    endpoint_name = 'test-endpoint'
    team = 'fraud'
    sns_topic = 'arn:aws:sns:us-east-1:123:fraud'
    
    with patch('endpoint_alarm.get_sagemaker_client', return_value=mock_sagemaker), \
         patch('endpoint_alarm.get_cloudwatch_client', return_value=mock_cloudwatch):
        
        endpoint_alarm.create_endpoint_alarms(endpoint_name, team, sns_topic)
        
        # Should create 3 alarms per variant (2 variants × 3 = 6)
        assert mock_cloudwatch.put_metric_alarm.call_count == 6
        
        # Check alarm properties
        calls = mock_cloudwatch.put_metric_alarm.call_args_list
        
        # Check first alarm (5XX errors for variant-1)
        alarm_5xx_v1 = calls[0][1]
        assert 'variant-1' in alarm_5xx_v1['AlarmName']
        assert '5xx-errors' in alarm_5xx_v1['AlarmName']
        assert alarm_5xx_v1['MetricName'] == 'Invocation5XXErrors'
        assert alarm_5xx_v1['AlarmActions'] == [sns_topic]
        assert {'Name': 'EndpointName', 'Value': endpoint_name} in alarm_5xx_v1['Dimensions']
        assert {'Name': 'VariantName', 'Value': 'variant-1'} in alarm_5xx_v1['Dimensions']
        assert any(tag['Key'] == 'Team' and tag['Value'] == team for tag in alarm_5xx_v1['Tags'])
        
        # Check latency alarm (variant-1)
        alarm_latency_v1 = calls[1][1]
        assert 'variant-1' in alarm_latency_v1['AlarmName']
        assert 'high-latency' in alarm_latency_v1['AlarmName']
        assert alarm_latency_v1['MetricName'] == 'ModelLatency'
        assert alarm_latency_v1['ExtendedStatistic'] == 'p90'
        assert alarm_latency_v1['Threshold'] == 10000000.0  # 10 seconds in microseconds
        assert {'Name': 'VariantName', 'Value': 'variant-1'} in alarm_latency_v1['Dimensions']
        
        # Check invocation drop alarm
        alarm_drop_v1 = calls[2][1]
        assert 'variant-1' in alarm_drop_v1['AlarmName']
        assert 'invocation-drop' in alarm_drop_v1['AlarmName']
        assert alarm_drop_v1['MetricName'] == 'Invocations'
        assert {'Name': 'VariantName', 'Value': 'variant-1'} in alarm_drop_v1['Dimensions']


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


def test_lambda_handler_with_in_service_status():
    """Test lambda handler with InService status (without underscore)."""
    event = {
        'detail-type': 'SageMaker Endpoint State Change',
        'source': 'aws.sagemaker',
        'detail': {
            'EndpointName': 'fraud-model-endpoint',
            'EndpointStatus': 'InService',
            'EndpointArn': 'arn:aws:sagemaker:us-east-1:123456789:endpoint/fraud-model-endpoint'
        }
    }
    
    mock_sagemaker = MagicMock()
    mock_cloudwatch = MagicMock()
    mock_sns = MagicMock()
    
    mock_sagemaker.describe_endpoint.return_value = {
        'EndpointArn': 'arn:aws:sagemaker:us-east-1:123:endpoint/fraud-model-endpoint',
        'EndpointConfigName': 'fraud-model-config'
    }
    mock_sagemaker.describe_endpoint_config.return_value = {
        'ProductionVariants': [
            {'VariantName': 'AllTraffic'}
        ]
    }
    mock_sagemaker.list_tags.return_value = {
        'Tags': [{'Key': 'Team', 'Value': 'fraud'}]
    }
    
    with patch('endpoint_alarm.get_sagemaker_client', return_value=mock_sagemaker), \
         patch('endpoint_alarm.get_cloudwatch_client', return_value=mock_cloudwatch), \
         patch('endpoint_alarm.get_sns_client', return_value=mock_sns):
        
        result = endpoint_alarm.lambda_handler(event, None)
        
        assert result['statusCode'] == 200
        # Should create 3 alarms for 1 variant
        assert mock_cloudwatch.put_metric_alarm.call_count == 3


def test_lambda_handler_skips_non_inservice_status():
    """Test lambda handler skips endpoints not in service."""
    event = {
        'detail-type': 'SageMaker Endpoint State Change',
        'source': 'aws.sagemaker',
        'detail': {
            'EndpointName': 'fraud-model-endpoint',
            'EndpointStatus': 'Creating',
            'EndpointArn': 'arn:aws:sagemaker:us-east-1:123456789:endpoint/fraud-model-endpoint'
        }
    }
    
    mock_sagemaker = MagicMock()
    mock_cloudwatch = MagicMock()
    mock_sns = MagicMock()
    
    with patch('endpoint_alarm.get_sagemaker_client', return_value=mock_sagemaker), \
         patch('endpoint_alarm.get_cloudwatch_client', return_value=mock_cloudwatch), \
         patch('endpoint_alarm.get_sns_client', return_value=mock_sns):
        
        result = endpoint_alarm.lambda_handler(event, None)
        
        assert result['statusCode'] == 200
        assert 'Skipped' in result['body']
        # Should not create any alarms
        assert mock_cloudwatch.put_metric_alarm.call_count == 0

