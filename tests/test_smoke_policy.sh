#!/bin/bash
# Test script to validate smoke test temporary user policy JSON generation

set -e

echo "Testing smoke test policy JSON generation..."

# Mock TEAM_DETAILS (same format as terraform output)
TEAM_DETAILS='{
  "fraud": {
    "execution_role_arn": "arn:aws:iam::123456789012:role/fraud-execution-role"
  },
  "recsys": {
    "execution_role_arn": "arn:aws:iam::123456789012:role/recsys-execution-role"
  }
}'

# Generate policy using the same jq command from smoke-test.sh
POLICY_DOC=$(echo "$TEAM_DETAILS" | jq -c '{
    Version: "2012-10-17",
    Statement: [{
        Effect: "Allow",
        Action: "sts:AssumeRole",
        Resource: [.[] | .execution_role_arn]
    }]
}')

echo "Generated policy:"
echo "$POLICY_DOC" | jq .

# Validate it's valid JSON
if ! echo "$POLICY_DOC" | jq empty 2>/dev/null; then
    echo "✗ FAILED: Generated invalid policy JSON"
    exit 1
fi

# Check it has the expected structure
if ! echo "$POLICY_DOC" | jq -e '.Version == "2012-10-17"' >/dev/null; then
    echo "✗ FAILED: Missing or incorrect Version"
    exit 1
fi

if ! echo "$POLICY_DOC" | jq -e '.Statement[0].Effect == "Allow"' >/dev/null; then
    echo "✗ FAILED: Missing or incorrect Effect"
    exit 1
fi

if ! echo "$POLICY_DOC" | jq -e '.Statement[0].Action == "sts:AssumeRole"' >/dev/null; then
    echo "✗ FAILED: Missing or incorrect Action"
    exit 1
fi

RESOURCE_COUNT=$(echo "$POLICY_DOC" | jq '.Statement[0].Resource | length')
if [ "$RESOURCE_COUNT" != "2" ]; then
    echo "✗ FAILED: Expected 2 resources, got $RESOURCE_COUNT"
    exit 1
fi

# Verify no double-quoted ARNs (the original bug)
if echo "$POLICY_DOC" | grep -q '""arn:'; then
    echo "✗ FAILED: Policy contains double-quoted ARNs"
    exit 1
fi

echo "✓ All policy validation checks passed"
