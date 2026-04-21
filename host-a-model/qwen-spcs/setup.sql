-- ============================================================
-- setup.sql
-- Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled SPCS POC
-- Object Provisioning
--
-- Run order:
--   1. CONFIG                (edit variables below)
--   2. ACCOUNTADMIN section  (POC role + grants)
--   3. SYSADMIN section      (database, schema, warehouse, compute pools)
--   4. QWEN_POC_ROLE section (image repo, stage)
--   5. VERIFY                (spot-check all objects)
--
-- CREATE SERVICE is in create_service.sql and runs AFTER
-- the Docker image is pushed and model weights are staged.
-- ============================================================


-- ------------------------------------------------------------
-- CONFIG
-- Values are injected from .env via `snow sql --variable`.
-- Edit .env, not this file.
-- ------------------------------------------------------------

-- Identifiers
SET poc_role               = '<% ROLE %>';
SET compute_pool           = '<% QWEN_POOL %>';
SET database               = '<% DB %>';
SET schema                 = '<% SCHEMA %>';
SET warehouse              = '<% WH %>';
SET image_repo             = '<% QWEN_REPO %>';
SET model_stage            = '<% QWEN_STAGE %>';

-- Compute pool config
SET pool_min_nodes         = <% QWEN_MIN_NODES %>;
SET pool_max_nodes         = <% QWEN_MAX_NODES %>;
SET pool_instance_family   = '<% QWEN_INSTANCE %>';
SET pool_auto_suspend_secs = <% QWEN_SUSPEND %>;

-- Warehouse config
SET wh_size                = '<% WH_SIZE %>';
SET wh_auto_suspend        = <% WH_SUSPEND %>;

-- User to grant the POC role to
SET grant_user             = '<% USER %>';

-- Agent server objects (LangGraph agent — CPU only)
SET agent_pool             = '<% AGENT_POOL %>';
SET agent_pool_instance    = '<% AGENT_INSTANCE %>';
SET agent_repo             = '<% AGENT_REPO %>';
SET agent_stage            = '<% AGENT_STAGE %>';
SET agent_secret           = '<% AGENT_SECRET %>';

-- Derived
SET schema_fqn             = $database || '.' || $schema;


-- -------------------------------------------------------
-- SECTION 1: ACCOUNTADMIN
-- Creates dedicated POC role and grants it to SYSADMIN
-- and the target user.
-- -------------------------------------------------------
USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS IDENTIFIER($poc_role)
  COMMENT = 'Owner role for Qwen3.5-27B SPCS POC';

GRANT ROLE IDENTIFIER($poc_role) TO ROLE SYSADMIN;

SET grant_role_sql = 'GRANT ROLE ' || $poc_role || ' TO USER ' || $grant_user;
EXECUTE IMMEDIATE $grant_role_sql;

GRANT CREATE DATABASE ON ACCOUNT TO ROLE SYSADMIN;
GRANT BIND SERVICE ENDPOINT ON ACCOUNT TO ROLE IDENTIFIER($poc_role);


-- -------------------------------------------------------
-- SECTION 2: SYSADMIN
-- Creates database, schema, warehouse, and compute pools.
-- Transfers ownership of DB/schema/WH to the POC role.
-- -------------------------------------------------------
USE ROLE SYSADMIN;

CREATE DATABASE IF NOT EXISTS IDENTIFIER($database)
  COMMENT = 'Innovation Igloo demo database';

CREATE SCHEMA IF NOT EXISTS IDENTIFIER($schema_fqn)
  COMMENT = 'Qwen3.5-27B Claude Opus Distilled SPCS POC';

SET create_wh_sql =
  'CREATE WAREHOUSE IF NOT EXISTS ' || $warehouse ||
  ' WAREHOUSE_SIZE = ''' || $wh_size || '''' ||
  ' AUTO_SUSPEND = ' || $wh_auto_suspend ||
  ' AUTO_RESUME = TRUE' ||
  ' INITIALLY_SUSPENDED = TRUE' ||
  ' COMMENT = ''Admin warehouse for Qwen POC DDL queries (not used for inference)''';
EXECUTE IMMEDIATE $create_wh_sql;

-- GPU compute pool for Qwen inference
SET create_pool_sql =
  'CREATE COMPUTE POOL IF NOT EXISTS ' || $compute_pool ||
  ' MIN_NODES = ' || $pool_min_nodes ||
  ' MAX_NODES = ' || $pool_max_nodes ||
  ' INSTANCE_FAMILY = ' || $pool_instance_family ||
  ' AUTO_RESUME = TRUE' ||
  ' AUTO_SUSPEND_SECS = ' || $pool_auto_suspend_secs ||
  ' COMMENT = ''Qwen3.5-27B vLLM inference — 4x A10G (96 GB VRAM)''';
EXECUTE IMMEDIATE $create_pool_sql;

-- Agent CPU compute pool
SET create_agent_pool_sql =
  'CREATE COMPUTE POOL IF NOT EXISTS ' || $agent_pool ||
  ' MIN_NODES = 1' ||
  ' MAX_NODES = 1' ||
  ' INSTANCE_FAMILY = ' || $agent_pool_instance ||
  ' AUTO_RESUME = TRUE' ||
  ' AUTO_SUSPEND_SECS = 3600' ||
  ' COMMENT = ''LangGraph agent server — CPU only''';
EXECUTE IMMEDIATE $create_agent_pool_sql;

-- Grant compute pool privileges to POC role
GRANT USAGE   ON COMPUTE POOL IDENTIFIER($compute_pool) TO ROLE IDENTIFIER($poc_role);
GRANT OPERATE ON COMPUTE POOL IDENTIFIER($compute_pool) TO ROLE IDENTIFIER($poc_role);
GRANT MONITOR ON COMPUTE POOL IDENTIFIER($compute_pool) TO ROLE IDENTIFIER($poc_role);

GRANT USAGE   ON COMPUTE POOL IDENTIFIER($agent_pool) TO ROLE IDENTIFIER($poc_role);
GRANT OPERATE ON COMPUTE POOL IDENTIFIER($agent_pool) TO ROLE IDENTIFIER($poc_role);
GRANT MONITOR ON COMPUTE POOL IDENTIFIER($agent_pool) TO ROLE IDENTIFIER($poc_role);

-- Transfer ownership to POC role
GRANT OWNERSHIP ON DATABASE  IDENTIFIER($database)    TO ROLE IDENTIFIER($poc_role) COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA    IDENTIFIER($schema_fqn)  TO ROLE IDENTIFIER($poc_role) COPY CURRENT GRANTS;
GRANT OWNERSHIP ON WAREHOUSE IDENTIFIER($warehouse)   TO ROLE IDENTIFIER($poc_role) COPY CURRENT GRANTS;


-- -------------------------------------------------------
-- SECTION 3: QWEN_POC_ROLE
-- Creates image repository and model weights stage.
-- Role owns these objects from creation.
-- -------------------------------------------------------
USE ROLE      IDENTIFIER($poc_role);
USE DATABASE  IDENTIFIER($database);
USE SCHEMA    IDENTIFIER($schema_fqn);
USE WAREHOUSE IDENTIFIER($warehouse);

CREATE IMAGE REPOSITORY IF NOT EXISTS IDENTIFIER($image_repo);

CREATE STAGE IF NOT EXISTS IDENTIFIER($model_stage)
  DIRECTORY = (ENABLE = TRUE)
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = 'Qwen3.5-27B model weights and service_spec.yaml';

-- Agent container image repo
CREATE IMAGE REPOSITORY IF NOT EXISTS IDENTIFIER($agent_repo)
  COMMENT = 'Multi-Agent Studio agent container images';

-- Runtime-mounted config stage for agent service
CREATE STAGE IF NOT EXISTS IDENTIFIER($agent_stage)
  DIRECTORY = (ENABLE = TRUE)
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = 'Runtime-mounted config for agent service (config.yaml)';

-- Agent PAT secret. Populate via `make agent-secret-rotate` after setup.
CREATE SECRET IF NOT EXISTS IDENTIFIER($agent_secret)
  TYPE = GENERIC_STRING
  SECRET_STRING = 'REPLACE_ME_AFTER_CREATE'
  COMMENT = 'PAT used by agent container to auth to Qwen SPCS + Cortex APIs';


-- -------------------------------------------------------
-- VERIFY
-- Run these after all three sections to confirm objects.
-- -------------------------------------------------------
SET show_pool_sql = 'SHOW COMPUTE POOLS LIKE ''' || $compute_pool || '''';
EXECUTE IMMEDIATE $show_pool_sql;
SHOW IMAGE REPOSITORIES IN SCHEMA IDENTIFIER($schema_fqn);
SHOW STAGES             IN SCHEMA IDENTIFIER($schema_fqn);
SET show_wh_sql = 'SHOW WAREHOUSES LIKE ''' || $warehouse || '''';
EXECUTE IMMEDIATE $show_wh_sql;
SET show_agent_pool_sql = 'SHOW COMPUTE POOLS LIKE ''' || $agent_pool || '''';
EXECUTE IMMEDIATE $show_agent_pool_sql;
SHOW SECRETS IN SCHEMA IDENTIFIER($schema_fqn);
