#!/bin/bash
set -e

# Pre-destroy script to handle SageMaker Studio cleanup
# Studio apps and spaces must be deleted before profiles and domain can be deleted

echo "=== Pre-destroy: Cleaning up SageMaker Studio resources ==="

AWS_CMD="${AWS_CLI:-aws}"
REGION="${AWS_REGION:-us-east-1}"

# Check if AWS CLI is available
if ! command -v "$AWS_CMD" >/dev/null 2>&1; then
    echo "Warning: AWS CLI not found, skipping pre-destroy cleanup"
    echo "You may need to manually delete Studio apps before destroying"
    exit 0
fi

# Get domain ID from Terraform state
DOMAIN_ID=$(terraform output -raw studio_domain_id 2>/dev/null || echo "")

if [ -z "$DOMAIN_ID" ]; then
    echo "No SageMaker domain found in state, skipping cleanup"
    exit 0
fi

echo "Found SageMaker domain: $DOMAIN_ID"
echo "Cleaning up apps and spaces..."

# Delete all apps in the domain
echo "Deleting Studio apps..."
APPS=$("$AWS_CMD" sagemaker list-apps --region "$REGION" --output json 2>/dev/null || echo '{"Apps":[]}')

echo "$APPS" | grep -o '"DomainId":"[^"]*","UserProfileName":"[^"]*","AppType":"[^"]*","AppName":"[^"]*"' | while read -r line; do
    DOMAIN=$(echo "$line" | grep -o '"DomainId":"[^"]*"' | cut -d'"' -f4)
    USER=$(echo "$line" | grep -o '"UserProfileName":"[^"]*"' | cut -d'"' -f4)
    APP_TYPE=$(echo "$line" | grep -o '"AppType":"[^"]*"' | cut -d'"' -f4)
    APP_NAME=$(echo "$line" | grep -o '"AppName":"[^"]*"' | cut -d'"' -f4)
    
    if [ "$DOMAIN" = "$DOMAIN_ID" ]; then
        echo "  Deleting app: $APP_NAME (type=$APP_TYPE, user=$USER)"
        "$AWS_CMD" sagemaker delete-app \
            --region "$REGION" \
            --domain-id "$DOMAIN" \
            --user-profile-name "$USER" \
            --app-type "$APP_TYPE" \
            --app-name "$APP_NAME" 2>/dev/null || true
    fi
done

# Wait for apps to finish deleting
echo "Waiting for apps to finish deleting (this may take a few minutes)..."
sleep 10

MAX_WAIT=300  # 5 minutes
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    REMAINING=$("$AWS_CMD" sagemaker list-apps --region "$REGION" --output json 2>/dev/null | grep -c "\"DomainId\":\"$DOMAIN_ID\"" || echo "0")
    
    if [ "$REMAINING" -eq 0 ]; then
        echo "All apps deleted successfully"
        break
    fi
    
    echo "  Still waiting... ($REMAINING apps remaining)"
    sleep 10
    WAITED=$((WAITED + 10))
done

echo "Pre-destroy cleanup complete"
