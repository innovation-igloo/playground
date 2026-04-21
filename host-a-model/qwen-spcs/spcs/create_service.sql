-- ============================================================
-- create_service.sql
-- Qwen vLLM inference service
--
-- Variables injected by `snow sql --variable` (see root Makefile):
--   <% ROLE %>, <% DB %>, <% SCHEMA %>
--   <% QWEN_SERVICE %>, <% QWEN_POOL %>, <% QWEN_STAGE %>
-- ============================================================

USE ROLE      IDENTIFIER('<% ROLE %>');
USE DATABASE  IDENTIFIER('<% DB %>');
USE SCHEMA    IDENTIFIER('<% SCHEMA %>');

CREATE SERVICE IF NOT EXISTS IDENTIFIER('<% QWEN_SERVICE %>')
  IN COMPUTE POOL IDENTIFIER('<% QWEN_POOL %>')
  FROM @<% DB %>.<% SCHEMA %>.<% QWEN_STAGE %>
  SPECIFICATION_FILE='service_spec.yaml'
  MIN_INSTANCES = 1
  MAX_INSTANCES = 1
  COMMENT = 'Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled via vLLM';

GRANT SERVICE ROLE <% DB %>.<% SCHEMA %>.<% QWEN_SERVICE %>!inference_user TO ROLE SYSADMIN;

SHOW ENDPOINTS IN SERVICE IDENTIFIER('<% QWEN_SERVICE %>');
