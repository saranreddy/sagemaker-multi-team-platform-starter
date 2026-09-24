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
    echo "You may need to manually delete Studio apps and spaces before destroying"
    exit 0
fi

# Check if jq is available
if ! command -v jq >/dev/null 2>&1; then
    echo "Warning: jq not found, skipping pre-destroy cleanup"
    echo "Install jq or manually delete Studio apps and spaces before destroying"
    exit 0
fi

# Get domain ID from Terraform state
DOMAIN_ID=$(terraform output -raw studio_domain_id 2>/dev/null || echo "")

if [ -z "$DOMAIN_ID" ] || [ "$DOMAIN_ID" = "" ]; then
    echo "No SageMaker domain found in state, skipping cleanup"
    exit 0
fi

echo "Found SageMaker domain: $DOMAIN_ID"

# Delete all apps in the domain
echo "Deleting Studio apps..."
APPS=$("$AWS_CMD" sagemaker list-apps --region "$REGION" --output json 2>/dev/null || echo '{"Apps":[]}')

echo "$APPS" | jq -r '.Apps[] | select(.DomainId == "'"$DOMAIN_ID"'") | [.DomainId, .UserProfileName // .SpaceName, .AppType, .AppName, .SpaceName] | @tsv' | while IFS=$'\t' read -r domain user_or_space app_type app_name space_name; do
    if [ -n "$space_name" ] && [ "$space_name" != "null" ]; then
        # Space app
        echo "  Deleting space app: $app_name (type=$app_type, space=$space_name)"
        "$AWS_CMD" sagemaker delete-app \
            --region "$REGION" \
            --domain-id "$domain" \
            --space-name "$space_name" \
            --app-type "$app_type" \
            --app-name "$app_name" 2>/dev/null || true
    else
        # User profile app
        echo "  Deleting user app: $app_name (type=$app_type, user=$user_or_space)"
        "$AWS_CMD" sagemaker delete-app \
            --region "$REGION" \
            --domain-id "$domain" \
            --user-profile-name "$user_or_space" \
            --app-type "$app_type" \
            --app-name "$app_name" 2>/dev/null || true
    fi
done

# Wait for apps to finish deleting
echo "Waiting for apps to finish deleting..."
sleep 10

MAX_WAIT=300  # 5 minutes
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    REMAINING=$("$AWS_CMD" sagemaker list-apps --region "$REGION" --output json 2>/dev/null | jq -r "[.Apps[] | select(.DomainId == \"$DOMAIN_ID\")] | length")
    
    if [ "$REMAINING" = "0" ]; then
        echo "All apps deleted successfully"
        break
    fi
    
    echo "  Still waiting... ($REMAINING apps remaining)"
    sleep 10
    WAITED=$((WAITED + 10))
done

# Delete all spaces in the domain
echo "Deleting Studio spaces..."
SPACES=$("$AWS_CMD" sagemaker list-spaces --domain-id "$DOMAIN_ID" --region "$REGION" --output json 2>/dev/null || echo '{"Spaces":[]}')

echo "$SPACES" | jq -r '.Spaces[] | .SpaceName' | while read -r space_name; do
    if [ -n "$space_name" ]; then
        echo "  Deleting space: $space_name"
        "$AWS_CMD" sagemaker delete-space \
            --region "$REGION" \
            --domain-id "$DOMAIN_ID" \
            --space-name "$space_name" 2>/dev/null || true
    fi
done

# Wait for spaces to finish deleting
if [ -n "$(echo "$SPACES" | jq -r '.Spaces[] | .SpaceName')" ]; then
    echo "Waiting for spaces to finish deleting..."
    sleep 10
    
    MAX_WAIT=300
    WAITED=0
    while [ $WAITED -lt $MAX_WAIT ]; do
        REMAINING=$("$AWS_CMD" sagemaker list-spaces --domain-id "$DOMAIN_ID" --region "$REGION" --output json 2>/dev/null | jq -r '.Spaces | length')
        
        if [ "$REMAINING" = "0" ]; then
            echo "All spaces deleted successfully"
            break
        fi
        
        echo "  Still waiting... ($REMAINING spaces remaining)"
        sleep 10
        WAITED=$((WAITED + 10))
    done
fi

echo "Pre-destroy cleanup complete"
echo ""
echo "Note: After Terraform destroy, the domain security group and EFS ENIs may take"
echo "a few minutes to be removed by AWS. This is normal and does not affect cleanup."
