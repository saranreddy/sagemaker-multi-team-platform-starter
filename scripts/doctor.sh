#!/bin/bash
set -e

# Doctor script - checks prerequisites for the Terraform starter

echo "=== SageMaker Multi-Team Platform - Prerequisites Check ==="
echo ""

ERRORS=0

# Check Terraform
echo "Checking Terraform..."
if command -v terraform >/dev/null 2>&1; then
    TERRAFORM_VERSION=$(terraform version -json | grep -o '"terraform_version":"[^"]*' | cut -d'"' -f4)
    echo "  ✓ Terraform installed: $TERRAFORM_VERSION"
    
    # Check minimum version
    REQUIRED_VERSION="1.5.7"
    if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$TERRAFORM_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
        echo "  ✗ Terraform version $TERRAFORM_VERSION is below required $REQUIRED_VERSION"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "  ✗ Terraform not found"
    echo "    Install from: https://www.terraform.io/downloads"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Check AWS CLI (with override support for arm64/x86 issues)
echo "Checking AWS CLI..."
AWS_CMD="${AWS_CLI:-aws}"
if command -v "$AWS_CMD" >/dev/null 2>&1; then
    # Try to execute it
    if AWS_VERSION=$("$AWS_CMD" --version 2>&1); then
        echo "  ✓ AWS CLI available: $AWS_VERSION"
        
        # Check credentials
        if "$AWS_CMD" sts get-caller-identity >/dev/null 2>&1; then
            ACCOUNT_ID=$("$AWS_CMD" sts get-caller-identity --query Account --output text)
            CALLER_ARN=$("$AWS_CMD" sts get-caller-identity --query Arn --output text)
            echo "  ✓ AWS credentials configured"
            echo "    Account: $ACCOUNT_ID"
            echo "    Identity: $CALLER_ARN"
        else
            echo "  ✗ AWS credentials not configured or invalid"
            echo "    Run: aws configure"
            ERRORS=$((ERRORS + 1))
        fi
    else
        echo "  ✗ AWS CLI found but not executable (may be wrong architecture)"
        echo "    Set AWS_CLI environment variable to correct binary path"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "  ✗ AWS CLI not found"
    echo "    Install from: https://aws.amazon.com/cli/"
    echo "    Or set AWS_CLI env var to binary path"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Check Python (for Lambda development and testing)
echo "Checking Python..."
if command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    echo "  ✓ Python 3 installed: $PYTHON_VERSION"
    
    # Check pip
    if command -v pip3 >/dev/null 2>&1; then
        echo "  ✓ pip3 available"
    else
        echo "  ⚠ pip3 not found (needed for tests)"
    fi
else
    echo "  ✗ Python 3 not found"
    echo "    Needed for Lambda testing"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Optional tools
echo "Optional tools:"

if command -v tflint >/dev/null 2>&1; then
    TFLINT_VERSION=$(tflint --version | head -n1)
    echo "  ✓ tflint: $TFLINT_VERSION"
else
    echo "  ⚠ tflint not installed (recommended for linting)"
fi

if command -v pytest >/dev/null 2>&1; then
    echo "  ✓ pytest available"
else
    echo "  ⚠ pytest not installed (needed for 'make test')"
fi

echo ""

# Summary
if [ $ERRORS -eq 0 ]; then
    echo "✓ All required prerequisites are met!"
    exit 0
else
    echo "✗ Found $ERRORS error(s). Please fix the issues above."
    exit 1
fi
