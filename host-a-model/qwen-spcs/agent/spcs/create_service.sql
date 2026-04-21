-- ============================================================
-- create_service.sql
-- Snowflake Multi-Agent Studio — SPCS service (LangGraph agent + React UI)
--
-- Variables injected by `snow sql --variable` (see root Makefile):
--   <% ROLE %>, <% DB %>, <% SCHEMA %>, <% DB_LOWER %>, <% SCHEMA_LOWER %>
--   <% AGENT_SERVICE %>, <% AGENT_POOL %>
--   <% AGENT_REPO_LOWER %>, <% AGENT_IMAGE_NAME %>, <% AGENT_IMAGE_TAG %>
--   <% AGENT_SECRET %>, <% AGENT_STAGE %>
-- ============================================================

USE ROLE      IDENTIFIER('<% ROLE %>');
USE DATABASE  IDENTIFIER('<% DB %>');
USE SCHEMA    IDENTIFIER('<% SCHEMA %>');

CREATE SERVICE IF NOT EXISTS IDENTIFIER('<% AGENT_SERVICE %>')
  IN COMPUTE POOL IDENTIFIER('<% AGENT_POOL %>')
  FROM SPECIFICATION $$
spec:
  containers:
    - name: agent
      image: /<% DB_LOWER %>/<% SCHEMA_LOWER %>/<% AGENT_REPO_LOWER %>/<% AGENT_IMAGE_NAME %>:<% AGENT_IMAGE_TAG %>
      env:
        CONFIG_PATH: /app/config/config.yaml
      secrets:
        - snowflakeSecret: <% AGENT_SECRET %>
          secretKeyRef: secret_string
          envVarName: SNOWFLAKE_PAT
      resources:
        requests:
          cpu: "1"
          memory: 2Gi
        limits:
          cpu: "2"
          memory: 4Gi
      volumeMounts:
        - name: config
          mountPath: /app/config
  endpoints:
    - name: agent-api
      port: 8080
      public: true
      protocol: HTTP
  volumes:
    - name: config
      source: "@<% DB %>.<% SCHEMA %>.<% AGENT_STAGE %>"
      uid: 0
      gid: 0
  logExporters:
    eventTableConfig:
      logLevel: INFO
serviceRoles:
  - name: agent_user
    endpoints:
      - agent-api
$$
  MIN_INSTANCES = 1
  MAX_INSTANCES = 1
  COMMENT = 'Snowflake Multi-Agent Studio agent service';

GRANT SERVICE ROLE <% DB %>.<% SCHEMA %>.<% AGENT_SERVICE %>!agent_user TO ROLE SYSADMIN;

SHOW ENDPOINTS IN SERVICE IDENTIFIER('<% AGENT_SERVICE %>');
