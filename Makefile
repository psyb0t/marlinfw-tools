SHELL := /bin/bash

IMAGE ?= marlinfw-tools:dev
TEST_IMAGE ?= marlinfw-tools:test
PORT ?=

.PHONY: help build test test-unit test-integration test-real lint format clean

help: ## Show the shit this Makefile can do.

	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*##/ {printf "%-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build the locked-down printer toolbox.

	docker build --target runtime --tag $(IMAGE) .

test: test-unit test-integration ## Put the fake printer through all the tests.

test-unit: ## Test CLI behavior against the fake printer.

	docker build --target test --tag $(TEST_IMAGE) .
	docker run --rm --network=none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
		--entrypoint python $(TEST_IMAGE) -m unittest tests.test_cli -v

test-integration: ## Test the real Docker wrapper without real hardware.

	docker build --target test --tag $(TEST_IMAGE) .
	docker run --rm --network=none --read-only --tmpfs /tmp:rw,nosuid,size=16m \
		--entrypoint python $(TEST_IMAGE) -m unittest tests.test_docker_runner -v

test-real: ## Read one real printer without changing the damn thing.

	@test -n "$(PORT)" || { echo "PORT is required" >&2; exit 2; }
	.agents/skills/marlinfw-control/scripts/marlinfw-tools.sh inspect --port "$(PORT)"

lint: ## Check the Python and shell code in Docker.

	docker build --target test --tag $(TEST_IMAGE) .
	docker run --rm --network=none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
		--env RUFF_CACHE_DIR=/tmp/ruff-cache --entrypoint /bin/sh $(TEST_IMAGE) \
		-c 'ruff check . && ruff format --check . && shellcheck --shell=bash /work/marlinfw-tools.sh && shellcheck --shell=sh /work/tests/fixtures/docker-fixture.sh'

format: ## Make Ruff clean up the Python formatting in Docker.

	docker build --target test --tag $(TEST_IMAGE) .
	docker run --rm --user "$$(id -u):$$(id -g)" --network=none -v "$$PWD:/work" \
		--entrypoint ruff $(TEST_IMAGE) format /work/marlinfw_tools /work/tests

clean: ## Explain why cleanup never deletes your shit automatically.

	@echo "No automatic image removal. Remove $(IMAGE) or $(TEST_IMAGE) manually if wanted."
