# =============================================================================
# qwen-spcs — Unified Makefile
# =============================================================================
# Deploys the whole stack:
#   1. Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled vLLM service (GPU)
#   2. Snowflake Multi-Agent Studio (LangGraph agent + React UI, CPU)
#
# All identifiers flow from .env — single source of truth.
#
# -----------------------------------------------------------------------------
# Quick start
# -----------------------------------------------------------------------------
#   cp .env.example .env      # edit values for your environment
#   make setup                # provision all Snowflake objects (once)
#   make all                  # build+push images, upload assets, deploy both
#
# Step-by-step (prefer this the first time):
#   make setup
#   make qwen-docker          # build + push vLLM image
#   make qwen-weights         # download AWQ + upload to stage
#   make qwen-deploy          # create Qwen service
#   make qwen-endpoints       # grab Qwen URL → paste into agent/config.yaml
#   make agent-secret-rotate  # AGENT_PAT from ~/.snowflake/connections.toml
#   make agent-stage-config   # upload agent/config.yaml → @AGENT_STAGE
#   make agent-docker         # multi-stage build (UI + Python) + push
#   make agent-deploy         # create agent service
#   make agent-endpoints      # public URL (UI at /, API at /chat + /health)
#
#   make help                 # print all targets grouped by subsystem
# =============================================================================

-include .env
export

# =============================================================================
# 1. CONFIG
# =============================================================================
# Everything below is derived from .env. Do not edit here — edit .env.
# -----------------------------------------------------------------------------

# Snowflake CLI
SNOW_CONNECTION ?= innovation-igloo
SNOW             = snow sql -c $(SNOW_CONNECTION) --format json

# Repo paths
ROOT_DIR    := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
DOCKER_DIR  := $(ROOT_DIR)docker
SPCS_DIR    := $(ROOT_DIR)spcs
STAGE_DIR   := $(ROOT_DIR)stage
TEST_DIR    := $(ROOT_DIR)test
AGENT_DIR   := $(ROOT_DIR)agent
AGENT_UI    := $(AGENT_DIR)/ui

# Snowflake registry (lazy — only resolved when a docker target runs)
REGISTRY     = $(shell snow spcs image-registry url -c $(SNOW_CONNECTION) 2>/dev/null | tr -d '[:space:]')

# Lowercase variants for container image paths (Snowflake registry returns lowercase)
DB_LOWER           = $(shell echo $(SNOWFLAKE_DATABASE) | tr '[:upper:]' '[:lower:]')
SCHEMA_LOWER       = $(shell echo $(SNOWFLAKE_SCHEMA) | tr '[:upper:]' '[:lower:]')
QWEN_REPO_LOWER    = $(shell echo $(QWEN_IMAGE_REPO_NAME) | tr '[:upper:]' '[:lower:]')
AGENT_REPO_LOWER   = $(shell echo $(AGENT_REPO_NAME) | tr '[:upper:]' '[:lower:]')

# Fully qualified object names
QWEN_SERVICE_FQN   = $(SNOWFLAKE_DATABASE).$(SNOWFLAKE_SCHEMA).$(QWEN_SERVICE_NAME)
AGENT_SERVICE_FQN  = $(SNOWFLAKE_DATABASE).$(SNOWFLAKE_SCHEMA).$(AGENT_SERVICE_NAME)
AGENT_SECRET_FQN   = $(SNOWFLAKE_DATABASE).$(SNOWFLAKE_SCHEMA).$(AGENT_SECRET_NAME)
QWEN_STAGE_FQN     = @$(SNOWFLAKE_DATABASE).$(SNOWFLAKE_SCHEMA).$(QWEN_STAGE_NAME)
AGENT_STAGE_FQN    = @$(SNOWFLAKE_DATABASE).$(SNOWFLAKE_SCHEMA).$(AGENT_STAGE_NAME)

# Container image paths
QWEN_IMAGE_REPO    = $(DB_LOWER)/$(SCHEMA_LOWER)/$(QWEN_REPO_LOWER)
AGENT_IMAGE_REPO   = $(DB_LOWER)/$(SCHEMA_LOWER)/$(AGENT_REPO_LOWER)
QWEN_FULL          = $(REGISTRY)/$(QWEN_IMAGE_REPO)/$(QWEN_IMAGE_NAME):$(QWEN_IMAGE_TAG)
AGENT_FULL         = $(REGISTRY)/$(AGENT_IMAGE_REPO)/$(AGENT_IMAGE_NAME):$(AGENT_IMAGE_TAG)

# Local dev test knobs
API_URL ?= http://localhost:8080
MSG     ?= Hello — which Cortex Agent is wired up right now?

# One bundled --variable set passed to every file-based `snow sql -f` call.
# setup.sql and create_service.sql files reference these as &{VAR}.
SNOW_VARS = \
  --variable ROLE=$(SNOWFLAKE_ROLE) \
  --variable DB=$(SNOWFLAKE_DATABASE) \
  --variable SCHEMA=$(SNOWFLAKE_SCHEMA) \
  --variable WH=$(SNOWFLAKE_WAREHOUSE) \
  --variable USER=$(SNOWFLAKE_USER) \
  --variable WH_SIZE=$(WH_SIZE) \
  --variable WH_SUSPEND=$(WH_AUTO_SUSPEND) \
  --variable QWEN_POOL=$(QWEN_POOL_NAME) \
  --variable QWEN_INSTANCE=$(QWEN_POOL_INSTANCE) \
  --variable QWEN_MIN_NODES=$(QWEN_POOL_MIN_NODES) \
  --variable QWEN_MAX_NODES=$(QWEN_POOL_MAX_NODES) \
  --variable QWEN_SUSPEND=$(QWEN_POOL_AUTO_SUSPEND) \
  --variable QWEN_REPO=$(QWEN_IMAGE_REPO_NAME) \
  --variable QWEN_STAGE=$(QWEN_STAGE_NAME) \
  --variable QWEN_SERVICE=$(QWEN_SERVICE_NAME) \
  --variable QWEN_IMAGE_NAME=$(QWEN_IMAGE_NAME) \
  --variable QWEN_IMAGE_TAG=$(QWEN_IMAGE_TAG) \
  --variable QWEN_REPO_LOWER=$(QWEN_REPO_LOWER) \
  --variable AGENT_POOL=$(AGENT_POOL_NAME) \
  --variable AGENT_INSTANCE=$(AGENT_POOL_INSTANCE) \
  --variable AGENT_REPO=$(AGENT_REPO_NAME) \
  --variable AGENT_STAGE=$(AGENT_STAGE_NAME) \
  --variable AGENT_SECRET=$(AGENT_SECRET_NAME) \
  --variable AGENT_SERVICE=$(AGENT_SERVICE_NAME) \
  --variable AGENT_IMAGE_NAME=$(AGENT_IMAGE_NAME) \
  --variable AGENT_IMAGE_TAG=$(AGENT_IMAGE_TAG) \
  --variable AGENT_REPO_LOWER=$(AGENT_REPO_LOWER) \
  --variable DB_LOWER=$(DB_LOWER) \
  --variable SCHEMA_LOWER=$(SCHEMA_LOWER)


# =============================================================================
# 2. HELP
# =============================================================================

.DEFAULT_GOAL := help
.PHONY: help

help: ## Print all targets grouped by subsystem
	@awk 'BEGIN {FS = ":.*?##"} \
	  /^# ── / {printf "\n\033[1m%s\033[0m\n", substr($$0, 6)} \
	  /^[a-zA-Z][a-zA-Z0-9_-]*:.*?##/ {printf "  %-26s %s\n", $$1, $$2}' \
	  $(firstword $(MAKEFILE_LIST))


# =============================================================================
# 3. ORCHESTRATORS
# =============================================================================
# End-to-end one-liners. `make all` assumes `make setup` already ran.
# -----------------------------------------------------------------------------

# ── Orchestrators
.PHONY: all qwen-all agent-all

all: qwen-all agent-all ## Full deploy: Qwen image+weights+service, Agent secret+config+image+service

qwen-all: qwen-docker qwen-weights qwen-deploy ## Qwen: build+push image, upload weights, deploy service

agent-all: agent-secret-rotate agent-stage-config agent-docker agent-deploy ## Agent: populate secret, upload config, build+push image, deploy service


# =============================================================================
# 4. SETUP
# =============================================================================
# Runs setup.sql as ACCOUNTADMIN. Provisions:
#   - SNOWFLAKE_ROLE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA, SNOWFLAKE_WAREHOUSE
#   - QWEN_POOL + AGENT_POOL compute pools
#   - QWEN + AGENT image repos and stages
#   - AGENT_PAT placeholder secret (rotate with agent-secret-rotate)
# -----------------------------------------------------------------------------

# ── Setup
.PHONY: setup

setup: ## One-time: provision all Snowflake objects for Qwen + Agent (reads .env)
	$(SNOW) $(SNOW_VARS) -f $(ROOT_DIR)setup.sql


# =============================================================================
# 5. QWEN ── DOCKER
# =============================================================================

# ── Qwen docker
.PHONY: qwen-docker-build qwen-docker-login qwen-docker-push qwen-docker

qwen-docker-build: ## Build vLLM image for linux/amd64
	docker build --platform linux/amd64 \
	  -t $(QWEN_IMAGE_NAME):$(QWEN_IMAGE_TAG) \
	  $(DOCKER_DIR)

qwen-docker-login: ## Authenticate Docker to the Snowflake image registry
	snow spcs image-registry login -c $(SNOW_CONNECTION)

qwen-docker-push: ## Tag + push Qwen image
	@test -n "$(REGISTRY)" || (echo "ERROR: Could not resolve registry URL"; exit 1)
	docker tag $(QWEN_IMAGE_NAME):$(QWEN_IMAGE_TAG) $(QWEN_FULL)
	docker push $(QWEN_FULL)

qwen-docker: qwen-docker-build qwen-docker-login qwen-docker-push ## Full Qwen image pipeline: build → login → push


# =============================================================================
# 6. QWEN ── WEIGHTS
# =============================================================================

# ── Qwen weights
.PHONY: qwen-stage-upload qwen-stage-list qwen-weights

qwen-stage-upload: ## Download AWQ weights and upload to model stage
	bash $(STAGE_DIR)/upload_weights.sh

qwen-stage-list: ## List files on model weights stage
	$(SNOW) -q "LIST $(QWEN_STAGE_FQN);"

qwen-weights: qwen-stage-upload qwen-stage-list ## Full weights pipeline: download → upload → verify


# =============================================================================
# 7. QWEN ── DEPLOY
# =============================================================================

# ── Qwen deploy
.PHONY: qwen-deploy qwen-upgrade qwen-endpoints qwen-service-grant

qwen-deploy: ## Create Qwen service (image + weights must be ready)
	$(SNOW) $(SNOW_VARS) -f $(SPCS_DIR)/create_service.sql

qwen-upgrade: ## Upgrade service spec in-place (preserves endpoint URL)
	$(SNOW) -q "ALTER SERVICE $(QWEN_SERVICE_FQN) FROM $(QWEN_STAGE_FQN) SPECIFICATION_FILE='service_spec.yaml';"

qwen-endpoints: ## Show public Qwen HTTPS inference URL
	$(SNOW) -q "SHOW ENDPOINTS IN SERVICE $(QWEN_SERVICE_FQN);"

qwen-service-grant: ## Grant inference_user service role to SALES_ENGINEER
	$(SNOW) -q "GRANT SERVICE ROLE $(QWEN_SERVICE_FQN)!inference_user TO ROLE SALES_ENGINEER;"


# =============================================================================
# 8. QWEN ── DEBUG
# =============================================================================

# ── Qwen debug
.PHONY: qwen-pool-status qwen-pool-describe qwen-service-status qwen-service-describe qwen-service-events qwen-service-logs

qwen-pool-status: ## Check Qwen pool state (must be ACTIVE or IDLE before deploy)
	$(SNOW) -q "DESCRIBE COMPUTE POOL $(QWEN_POOL_NAME);"

qwen-pool-describe: ## Describe Qwen pool (alias of qwen-pool-status)
	$(SNOW) -q "DESCRIBE COMPUTE POOL $(QWEN_POOL_NAME);"

qwen-service-status: ## Show running Qwen containers and instance health
	$(SNOW) -q "SHOW SERVICE CONTAINERS IN SERVICE $(QWEN_SERVICE_FQN);"

qwen-service-describe: ## Full Qwen service description including spec and status
	$(SNOW) -q "DESCRIBE SERVICE $(QWEN_SERVICE_FQN);"

qwen-service-events: ## Show last 50 Qwen service events (startup errors, OOM, probes)
	$(SNOW) -q "SELECT * FROM TABLE(INFORMATION_SCHEMA.SERVICE_EVENTS('$(QWEN_SERVICE_FQN)')) ORDER BY TIMESTAMP DESC LIMIT 50;"

qwen-service-logs: ## Tail last 100 lines of Qwen container logs
	$(SNOW) -q "CALL SYSTEM\$$GET_SERVICE_LOGS('$(QWEN_SERVICE_FQN)', 0, '$(QWEN_IMAGE_NAME)', 100);"


# =============================================================================
# 9. QWEN ── TEST
# =============================================================================

# ── Qwen test
.PHONY: qwen-smoke-test qwen-client-test

qwen-smoke-test: ## Run curl smoke tests against the live Qwen service
	bash $(TEST_DIR)/smoke_test.sh

qwen-client-test: ## Run Python openai client examples against the live Qwen service
	python3 $(TEST_DIR)/client.py


# =============================================================================
# 10. QWEN ── TEARDOWN
# =============================================================================

# ── Qwen teardown
.PHONY: qwen-service-suspend qwen-service-drop qwen-pool-suspend qwen-nuke

qwen-service-suspend: ## Suspend Qwen service (pauses billing, config preserved)
	$(SNOW) -q "ALTER SERVICE $(QWEN_SERVICE_FQN) SUSPEND;"

qwen-service-drop: ## Drop Qwen service permanently
	$(SNOW) -q "DROP SERVICE IF EXISTS $(QWEN_SERVICE_FQN);"

qwen-pool-suspend: ## Suspend Qwen GPU pool (stops node billing)
	$(SNOW) -q "ALTER COMPUTE POOL $(QWEN_POOL_NAME) SUSPEND;"

qwen-nuke: qwen-service-drop qwen-pool-suspend ## Drop Qwen service + suspend pool
	@echo "Qwen service dropped. GPU pool suspended."


# =============================================================================
# 11. AGENT ── LOCAL DEV
# =============================================================================

# ── Agent local dev
.PHONY: agent-install agent-ui-install agent-ui-build agent-dev agent-api agent-ui

agent-install: ## pip install -e agent/ (Python deps)
	pip install -e $(AGENT_DIR)

agent-ui-install: ## npm install in agent/ui
	cd $(AGENT_UI) && npm install

agent-ui-build: ## Build React UI production bundle (standalone; docker does this internally too)
	cd $(AGENT_UI) && npm run build

agent-dev: ## Start FastAPI (8080) and Vite (5173) in parallel
	@trap 'kill 0' SIGINT; \
	  CONFIG_PATH=$(AGENT_DIR)/config.yaml PYTHONPATH=$(AGENT_DIR) python3 -m uvicorn server.app:app --app-dir $(AGENT_DIR) --host 0.0.0.0 --port 8080 --reload & \
	  cd $(AGENT_UI) && npm run dev & \
	  wait

agent-api: ## Start FastAPI server only (port 8080)
	CONFIG_PATH=$(AGENT_DIR)/config.yaml PYTHONPATH=$(AGENT_DIR) python3 -m uvicorn server.app:app --app-dir $(AGENT_DIR) --host 0.0.0.0 --port 8080 --reload

agent-ui: ## Start Vite dev server only (port 5173)
	cd $(AGENT_UI) && npm run dev


# =============================================================================
# 12. AGENT ── TEST
# =============================================================================

# ── Agent test
.PHONY: agent-test agent-health agent-chat

agent-test: ## Run pytest unit tests
	cd $(AGENT_DIR) && python3 -m pytest tests/ -v

agent-health: ## Check FastAPI /health endpoint
	curl -s $(API_URL)/health | python3 -m json.tool

agent-chat: ## Send a test message (set MSG="your question")
	curl -s -N -X POST $(API_URL)/chat \
	  -H "Content-Type: application/json" \
	  -d '{"message": "$(MSG)"}' | \
	  grep "data:" | sed 's/data: //g' | python3 -c \
	  "import sys,json; [print(j.get('content','')) for line in sys.stdin for j in [json.loads(line)] if j.get('content')]"


# =============================================================================
# 13. AGENT ── SECRET + CONFIG
# =============================================================================

# ── Agent secret + config
.PHONY: agent-secret-rotate agent-stage-config

agent-secret-rotate: ## Populate AGENT_PAT secret from connections.toml (or pass PAT=<value>)
	@PAT_VALUE="$(PAT)"; \
	  if [ -z "$$PAT_VALUE" ]; then \
	    PAT_VALUE=$$(python3 -c "import tomllib,os; \
	      f=open(os.path.expanduser('~/.snowflake/connections.toml'),'rb'); \
	      d=tomllib.load(f); print(d['$(SNOW_CONNECTION)']['password'])"); \
	  fi; \
	  if [ -z "$$PAT_VALUE" ]; then echo "ERROR: Could not resolve PAT"; exit 1; fi; \
	  $(SNOW) -q "ALTER SECRET $(AGENT_SECRET_FQN) SET SECRET_STRING = '$$PAT_VALUE';" && \
	  echo "$(AGENT_SECRET_NAME) rotated."

agent-stage-config: ## Upload agent/config.yaml to agent stage
	@test -f $(AGENT_DIR)/config.yaml || (echo "ERROR: agent/config.yaml missing — cp agent/config.example.yaml agent/config.yaml"; exit 1)
	snow stage copy $(AGENT_DIR)/config.yaml $(AGENT_STAGE_FQN) \
	  --overwrite -c $(SNOW_CONNECTION)


# =============================================================================
# 14. AGENT ── DOCKER
# =============================================================================
# Multi-stage build: stage 1 compiles the React UI with Node, stage 2 is the
# slim Python runtime with the built dist baked in at /app/ui-dist.
# -----------------------------------------------------------------------------

# ── Agent docker
.PHONY: agent-docker-build agent-docker-login agent-docker-push agent-docker

agent-docker-build: ## Build agent image (multi-stage: UI + Python)
	docker build --platform linux/amd64 -t $(AGENT_IMAGE_NAME):$(AGENT_IMAGE_TAG) $(AGENT_DIR)

agent-docker-login: ## Authenticate Docker to the Snowflake image registry
	snow spcs image-registry login -c $(SNOW_CONNECTION)

agent-docker-push: ## Tag + push agent image
	@test -n "$(REGISTRY)" || (echo "ERROR: Could not resolve registry URL"; exit 1)
	docker tag $(AGENT_IMAGE_NAME):$(AGENT_IMAGE_TAG) $(AGENT_FULL)
	docker push $(AGENT_FULL)

agent-docker: agent-docker-build agent-docker-login agent-docker-push ## Full agent image pipeline: build → login → push


# =============================================================================
# 15. AGENT ── DEPLOY
# =============================================================================

# ── Agent deploy
.PHONY: agent-deploy agent-upgrade agent-endpoints

agent-deploy: ## Create agent service (runs agent/spcs/create_service.sql)
	$(SNOW) $(SNOW_VARS) -f $(AGENT_DIR)/spcs/create_service.sql

agent-upgrade: agent-stage-config ## Config-only update: re-upload config + bounce service
	$(SNOW) -q "ALTER SERVICE $(AGENT_SERVICE_FQN) SUSPEND;"
	$(SNOW) -q "ALTER SERVICE $(AGENT_SERVICE_FQN) RESUME;"

agent-endpoints: ## Show public agent endpoint URL (UI at /, API at /chat)
	$(SNOW) -q "SHOW ENDPOINTS IN SERVICE $(AGENT_SERVICE_FQN);"


# =============================================================================
# 16. AGENT ── DEBUG
# =============================================================================

# ── Agent debug
.PHONY: agent-pool-status agent-service-status agent-service-describe agent-service-events agent-service-logs

agent-pool-status: ## Describe agent CPU pool
	$(SNOW) -q "DESCRIBE COMPUTE POOL $(AGENT_POOL_NAME);"

agent-service-status: ## Show agent service container health
	$(SNOW) -q "SHOW SERVICE CONTAINERS IN SERVICE $(AGENT_SERVICE_FQN);"

agent-service-describe: ## Full agent service description
	$(SNOW) -q "DESCRIBE SERVICE $(AGENT_SERVICE_FQN);"

agent-service-events: ## Show last 50 agent service events
	$(SNOW) -q "SELECT * FROM TABLE(INFORMATION_SCHEMA.SERVICE_EVENTS('$(AGENT_SERVICE_FQN)')) ORDER BY TIMESTAMP DESC LIMIT 50;"

agent-service-logs: ## Tail last 100 lines of agent container logs
	$(SNOW) -q "CALL SYSTEM\$$GET_SERVICE_LOGS('$(AGENT_SERVICE_FQN)', 0, 'agent', 100);"


# =============================================================================
# 17. AGENT ── TEARDOWN
# =============================================================================

# ── Agent teardown
.PHONY: agent-service-suspend agent-service-resume agent-service-drop agent-pool-suspend agent-nuke

agent-service-suspend: ## Suspend agent service
	$(SNOW) -q "ALTER SERVICE $(AGENT_SERVICE_FQN) SUSPEND;"

agent-service-resume: ## Resume agent service
	$(SNOW) -q "ALTER SERVICE $(AGENT_SERVICE_FQN) RESUME;"

agent-service-drop: ## Drop agent service permanently
	$(SNOW) -q "DROP SERVICE IF EXISTS $(AGENT_SERVICE_FQN);"

agent-pool-suspend: ## Suspend agent CPU pool
	$(SNOW) -q "ALTER COMPUTE POOL $(AGENT_POOL_NAME) SUSPEND;"

agent-nuke: agent-service-drop agent-pool-suspend ## Drop agent service + suspend pool
	@echo "Agent service dropped. CPU pool suspended."
