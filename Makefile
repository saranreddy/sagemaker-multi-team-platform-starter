.PHONY: help doctor init plan apply smoke destroy test fmt validate lint clean

# Auto-approve flags for CI
ifdef AUTO_APPROVE
	APPROVE_FLAG := -auto-approve
endif

ifdef CI
	APPROVE_FLAG := -auto-approve
endif

# Force flag for destroy
ifdef FORCE
	DESTROY_FLAG := -force
endif

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

doctor: ## Check prerequisites (Terraform, AWS CLI, Python)
	@./scripts/doctor.sh

init: doctor ## Initialize Terraform
	terraform init

fmt: ## Format Terraform files
	terraform fmt -recursive

validate: init ## Validate Terraform configuration
	terraform validate

lint: ## Run tflint
	@if command -v tflint >/dev/null 2>&1; then \
		tflint --init; \
		tflint; \
	else \
		echo "tflint not installed, skipping"; \
	fi

test: ## Run Python unit tests for Lambda functions
	@echo "Installing test dependencies..."
	@pip install -q -r tests/requirements.txt
	@echo "Running pytest..."
	@pytest tests/

plan: validate ## Show Terraform plan
	terraform plan

apply: validate ## Apply Terraform configuration
	terraform apply $(APPROVE_FLAG)

smoke: ## Run smoke tests (requires applied infrastructure)
	@./scripts/smoke-test.sh

destroy: ## Destroy all Terraform resources
	@./scripts/pre-destroy.sh
	terraform destroy $(APPROVE_FLAG) $(DESTROY_FLAG)

clean: ## Clean temporary files
	rm -rf .terraform
	rm -f .terraform.lock.hcl
	rm -f terraform.tfstate*
	rm -rf modules/reaper-lambda/lambda_package.zip
	rm -rf modules/endpoint-alarm-lambda/lambda_package.zip
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true

add-team: ## Add a new team (usage: make add-team NAME=newteam)
	@if [ -z "$(NAME)" ]; then \
		echo "Error: NAME is required. Usage: make add-team NAME=teamname"; \
		exit 1; \
	fi
	@echo "Adding new team: $(NAME)"
	@echo ""
	@echo "Add the following to your terraform.tfvars:"
	@echo ""
	@echo "  $(NAME) = {"
	@echo "    members = [\"user1\", \"user2\"]"
	@echo "    email_alerts = []"
	@echo "    monthly_budget_usd = 1000"
	@echo "    allowed_instance_types = ["
	@echo "      \"ml.t3.medium\","
	@echo "      \"ml.m5.xlarge\""
	@echo "    ]"
	@echo "  }"
	@echo ""
