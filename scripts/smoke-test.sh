#!/bin/bash
set -e

# Smoke test - validates infrastructure is working and isolation is enforced

echo "=== SageMaker Multi-Team Platform - Smoke Test ==="
echo ""

AWS_CMD="${AWS_CLI:-aws}"
REGION="${AWS_REGION:-us-east-1}"

ERRORS=0

# Check prerequisites
if ! command -v "$AWS_CMD" >/dev/null 2>&1; then
    echo "✗ AWS CLI not found"
    exit 1
fi

if ! command -v terraform >/dev/null 2>&1; then
    echo "✗ Terraform not found"
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "✗ jq not found (required for parsing JSON)"
    exit 1
fi

# Get outputs from Terraform
echo "Fetching Terraform outputs..."
OUTPUTS=$(terraform output -json)

DOMAIN_ID=$(echo "$OUTPUTS" | jq -r '.studio_domain_id.value')
TEAM_DETAILS=$(echo "$OUTPUTS" | jq -r '.team_details.value')
REAPER_LAMBDA=$(echo "$OUTPUTS" | jq -r '.reaper_lambda_function_name.value')
ALARM_LAMBDA=$(echo "$OUTPUTS" | jq -r '.endpoint_alarm_lambda_function_name.value')

echo "Domain ID: $DOMAIN_ID"
echo ""

# Test 1: Verify Studio domain exists
echo "Test 1: Verify Studio domain exists"
if "$AWS_CMD" sagemaker describe-domain --domain-id "$DOMAIN_ID" --region "$REGION" >/dev/null 2>&1; then
    echo "  ✓ Studio domain exists"
else
    echo "  ✗ Studio domain not found"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Test 2: Verify team resources exist
echo "Test 2: Verify team resources exist"
TEAM_NAMES=$(echo "$TEAM_DETAILS" | jq -r 'keys[]')

for TEAM in $TEAM_NAMES; do
    echo "  Team: $TEAM"
    
    # Check S3 bucket
    BUCKET=$(echo "$TEAM_DETAILS" | jq -r ".\"$TEAM\".s3_bucket")
    if "$AWS_CMD" s3 ls "s3://$BUCKET" --region "$REGION" >/dev/null 2>&1; then
        echo "    ✓ S3 bucket exists: $BUCKET"
    else
        echo "    ✗ S3 bucket not accessible: $BUCKET"
        ERRORS=$((ERRORS + 1))
    fi
    
    # Check ECR repository
    ECR_REPO=$(echo "$TEAM_DETAILS" | jq -r ".\"$TEAM\".ecr_repository_url" | cut -d'/' -f2-)
    if "$AWS_CMD" ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" >/dev/null 2>&1; then
        echo "    ✓ ECR repository exists: $ECR_REPO"
    else
        echo "    ✗ ECR repository not found: $ECR_REPO"
        ERRORS=$((ERRORS + 1))
    fi
    
    # Check Model Package Group
    MPG=$(echo "$TEAM_DETAILS" | jq -r ".\"$TEAM\".model_package_group")
    if "$AWS_CMD" sagemaker describe-model-package-group --model-package-group-name "$MPG" --region "$REGION" >/dev/null 2>&1; then
        echo "    ✓ Model package group exists: $MPG"
    else
        echo "    ✗ Model package group not found: $MPG"
        ERRORS=$((ERRORS + 1))
    fi
    
    # Check SNS topic
    SNS_TOPIC=$(echo "$TEAM_DETAILS" | jq -r ".\"$TEAM\".sns_topic_arn")
    if "$AWS_CMD" sns get-topic-attributes --topic-arn "$SNS_TOPIC" --region "$REGION" >/dev/null 2>&1; then
        echo "    ✓ SNS topic exists"
    else
        echo "    ✗ SNS topic not found"
        ERRORS=$((ERRORS + 1))
    fi
    
    # Check Budget
    BUDGET=$(echo "$TEAM_DETAILS" | jq -r ".\"$TEAM\".budget_name")
    ACCOUNT_ID=$("$AWS_CMD" sts get-caller-identity --query Account --output text)
    if "$AWS_CMD" budgets describe-budget --account-id "$ACCOUNT_ID" --budget-name "$BUDGET" --region us-east-1 >/dev/null 2>&1; then
        echo "    ✓ Budget exists: $BUDGET"
    else
        echo "    ✗ Budget not found: $BUDGET"
        ERRORS=$((ERRORS + 1))
    fi
done
echo ""

# Test 3: Test S3 isolation (if enable_smoke_test_assume is true)
echo "Test 3: Test S3 access isolation"
TEAMS_ARRAY=($TEAM_NAMES)
if [ ${#TEAMS_ARRAY[@]} -lt 2 ]; then
    echo "  ✗ FAILED: Need at least 2 teams to test isolation (found ${#TEAMS_ARRAY[@]})"
    ERRORS=$((ERRORS + 1))
elif [ ${#TEAMS_ARRAY[@]} -ge 2 ]; then
    TEAM_A=${TEAMS_ARRAY[0]}
    TEAM_B=${TEAMS_ARRAY[1]}
    
    ROLE_A=$(echo "$TEAM_DETAILS" | jq -r ".\"$TEAM_A\".execution_role_arn")
    BUCKET_A=$(echo "$TEAM_DETAILS" | jq -r ".\"$TEAM_A\".s3_bucket")
    BUCKET_B=$(echo "$TEAM_DETAILS" | jq -r ".\"$TEAM_B\".s3_bucket")
    
    echo "  Testing $TEAM_A role access to its own bucket..."
    TEST_FILE="smoke-test-$(date +%s).txt"
    
    # Assume team A role
    CREDS=$("$AWS_CMD" sts assume-role --role-arn "$ROLE_A" --role-session-name smoke-test --output json 2>&1)
    
    if echo "$CREDS" | jq -e '.Credentials.AccessKeyId' >/dev/null 2>&1; then
        export AWS_ACCESS_KEY_ID=$(echo "$CREDS" | jq -r '.Credentials.AccessKeyId')
        export AWS_SECRET_ACCESS_KEY=$(echo "$CREDS" | jq -r '.Credentials.SecretAccessKey')
        export AWS_SESSION_TOKEN=$(echo "$CREDS" | jq -r '.Credentials.SessionToken')
        
        # Test write to own bucket
        if echo "test" | "$AWS_CMD" s3 cp - "s3://$BUCKET_A/$TEST_FILE" --region "$REGION" >/dev/null 2>&1; then
            echo "    ✓ Team A can write to its own bucket"
            
            # Test read from own bucket
            if "$AWS_CMD" s3 cp "s3://$BUCKET_A/$TEST_FILE" - --region "$REGION" >/dev/null 2>&1; then
                echo "    ✓ Team A can read from its own bucket"
            else
                echo "    ✗ Team A cannot read from its own bucket"
                ERRORS=$((ERRORS + 1))
            fi
            
            # Clean up
            "$AWS_CMD" s3 rm "s3://$BUCKET_A/$TEST_FILE" --region "$REGION" >/dev/null 2>&1 || true
        else
            echo "    ✗ Team A cannot write to its own bucket"
            ERRORS=$((ERRORS + 1))
        fi
        
        # Test access to team B bucket (should be denied) - CRITICAL TEST
        if echo "test" | "$AWS_CMD" s3 cp - "s3://$BUCKET_B/$TEST_FILE" --region "$REGION" >/dev/null 2>&1; then
            echo "    ✗ ISOLATION BREACH: Team A can write to Team B bucket!"
            ERRORS=$((ERRORS + 1))
            # Clean up if somehow succeeded
            "$AWS_CMD" s3 rm "s3://$BUCKET_B/$TEST_FILE" --region "$REGION" >/dev/null 2>&1 || true
        else
            echo "    ✓ Team A cannot access Team B bucket (isolation working)"
        fi
        
        # Clear credentials
        unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
    else
        echo "    ✗ FAILED: Cannot assume role $ROLE_A"
        echo "    This is a critical failure when enable_smoke_test_assume=true"
        ERRORS=$((ERRORS + 1))
    fi
fi
echo ""

# Test 4: Verify Lambda functions
echo "Test 4: Verify Lambda functions"

echo "  Testing reaper Lambda..."
if "$AWS_CMD" lambda get-function --function-name "$REAPER_LAMBDA" --region "$REGION" >/dev/null 2>&1; then
    echo "    ✓ Reaper Lambda exists"
    
    # Test invocation (dry run)
    RESULT=$("$AWS_CMD" lambda invoke \
        --function-name "$REAPER_LAMBDA" \
        --region "$REGION" \
        --payload '{}' \
        /tmp/reaper-output.json 2>&1)
    
    if [ $? -eq 0 ]; then
        echo "    ✓ Reaper Lambda invocation successful"
        if [ -f /tmp/reaper-output.json ]; then
            REAPER_STATUS=$(jq -r '.statusCode' /tmp/reaper-output.json 2>/dev/null || echo "unknown")
            echo "      Status code: $REAPER_STATUS"
        fi
    else
        echo "    ✗ Reaper Lambda invocation failed"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "    ✗ Reaper Lambda not found"
    ERRORS=$((ERRORS + 1))
fi

echo "  Testing endpoint alarm Lambda..."
if "$AWS_CMD" lambda get-function --function-name "$ALARM_LAMBDA" --region "$REGION" >/dev/null 2>&1; then
    echo "    ✓ Endpoint alarm Lambda exists"
else
    echo "    ✗ Endpoint alarm Lambda not found"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Summary
echo "=== Smoke Test Summary ==="
if [ $ERRORS -eq 0 ]; then
    echo "✓ All smoke tests passed!"
    exit 0
else
    echo "✗ Found $ERRORS error(s)"
    exit 1
fi
