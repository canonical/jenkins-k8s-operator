PROJECT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

SRC := $(PROJECT)src
TESTS := $(PROJECT)tests
ALL := $(SRC) $(TESTS)

export PYTHONPATH = $(PROJECT):$(PROJECT)/lib:$(SRC)
export PY_COLORS=1

.PHONY: help
help: ## Show this help.
	@printf "%-30s %s\n" "Target" "Description"
	@printf "%-30s %s\n" "------" "-----------"
	@fgrep " ## " $(MAKEFILE_LIST) | fgrep -v grep | awk -F ': .*## ' '{$$1 = sprintf("%-30s", $$1)} 1'


.PHONY: setup-development
setup-development: ## Install development tools required for development
	uv add bandit black codespell coverage isort mypy pydocstyle pylint pytest
	uv add -r requirements.txt

.PHONY: fmt
fmt: ## Apply coding style standards to code
	uv run isort $(ALL)
	uv run black $(ALL)

.PHONY: lint
lint: ## Check code against coding standards
	uv run pydocstyle $(SRC)
	uv run codespell $(PROJECT)\
		--skip "$(PROJECT).*" \
		--skip $(PROJECT)icon.svg \
		--skip $(PROJECT)lib \
		--skip $(PROJECT)uv.lock
	uv run pflake8 $(ALL)
	uv run isort --check-only --diff $(ALL)
	uv run black --check --diff $(ALL)
	uv run mypy $(ALL)
	uv run pylint $(ALL)
	uv run pydocstyle $(SRC)

.PHONY: generate-unit-test-coverage
generate-unit-test-converage:
	uv run coverage run \
		--source=$(SRC) \
		-m pytest --ignore=$(TESTS)/integration \
		-v --tb native -s

.PHONY: test-unit
test-unit: generate-unit-test-coverage ## Run unit tests
	uv run coverage report

.PHONY: coverage-report
coverage-report: ## Generate unit test coverage report
	uv run coverage report

.PHONY: install-charm-tools
install-charm-tools:
	sudo snap install charmcraft --classic
	sudo snap install rockcraft --classic

.PHONY: pack-charm
pack-charm:
	charmcraft pack

.PHONY: pack-rock
pack-rock:
	@for dir in *_rock; do \
		if [ -d "$$dir" ]; then \
			cd "$$dir" && rockcraft pack; \
		fi; \
	done


.PHONY: build
build: pack-charm pack-rock ## Build necessary artefacts

.PHONY: clean
clean: ## Clean artifacts from building, testing, etc.
	@for dir in *_rock; do \
		if [ -d "$$dir" ]; then \
			cd "$$dir" && rockcraft clean; \
		fi; \
	done
	charmcraft clean

KUBE_CONFIG := .kube_config
JENKINS_IMAGE := localhost:32000/jenkins-image:test
JENKINS_CHARM_PATH := ./jenkins-k8s_ubuntu-22.04-amd64.charm

.PHONY: setup-microk8s
setup-microk8s: ## Setup microk8s plugins for this integration test
	sudo microk8s enable dns ingress rbac storage registry

.PHONY: setup-integration
setup-integration: build ## Install required artefacts for integration tests
	rockcraft.skopeo \
		--insecure-policy copy \
		--dest-tls-verify=false \
		oci-archive:jenkins_rock/jenkins_1.0_amd64.rock docker-daemon:$(JENKINS_IMAGE)
	sudo microk8s config > $(KUBE_CONFIG)

.PHONY: test-integration
test-integration: ## Run integration tests
	uv run pytest \
		--tb native \
		--ignore=$(TESTS)/unit \
		--log-cli-level=INFO \
		--jenkins-image=$(JENKINS_IMAGE) \
		--charm-file=$(JENKINS_CHARM_PATH) \
		--kube-config=$(KUBE_CONFIG)
