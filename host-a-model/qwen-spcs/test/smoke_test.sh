#!/bin/bash
# =============================================================
# Qwen3.5-27B SPCS — API Smoke Tests
#
# Usage:
#   ENDPOINT=https://<spcs-public-url> bash test/smoke_test.sh
#
# Get the ENDPOINT from:  make endpoints
#
# Auth: PAT is auto-read from ~/.snowflake/connections.toml
# (the `password` field under [$SNOW_CONNECTION]). No token needed.
#
# Tests covered:
#   1. Health check          GET  /health
#   2. List models           GET  /v1/models
#   3. Chat completion       POST /v1/chat/completions  (thinking ON)
#   4. Chat completion       POST /v1/chat/completions  (thinking OFF)
#   5. Chat with reasoning   POST /v1/chat/completions
#   6. Tokenize              POST /tokenize
#   7. Prometheus metrics    GET  /metrics
#   8. Tool calling          POST /v1/chat/completions
# =============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi
SNOW_CONNECTION="${SNOW_CONNECTION:-innovation-igloo}"

BASE="${ENDPOINT:-http://localhost:8000}"
MODEL="qwen3.5-27b"
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

pass() { echo -e "${GREEN}PASS${NC} $1"; }
fail() { echo -e "${RED}FAIL${NC} $1"; exit 1; }

if [ -z "${TOKEN:-}" ] && [[ "$BASE" == https://*.snowflakecomputing.app* ]]; then
  echo "No TOKEN set — reading PAT from connections.toml..."
  TOKEN=$(python3 -c "
import tomllib, pathlib, os
conn_name = os.environ.get('SNOW_CONNECTION','$SNOW_CONNECTION')
with open(pathlib.Path.home() / '.snowflake' / 'connections.toml', 'rb') as f:
    cfg = tomllib.load(f)
print(cfg[conn_name]['password'])
") || fail "Could not read PAT from connections.toml"
fi

AUTH_HEADER=()
if [ -n "${TOKEN:-}" ]; then
  AUTH_HEADER=(-H "Authorization: Snowflake Token=\"${TOKEN}\"")
fi

echo ""
echo "Target: $BASE"
echo "Model:  $MODEL"
if [ -n "${TOKEN:-}" ]; then
  echo "Auth:   PAT set (${#TOKEN} chars)"
else
  echo "Auth:   none (localhost mode)"
fi
echo "=================================================="

# ----------------------------------------------------------
# 1. Health check
# ----------------------------------------------------------
echo ""
echo "=== 1. Health check ==="
STATUS=$(curl -sf -o /dev/null -w "%{http_code}" "${AUTH_HEADER[@]}" "$BASE/health") || fail "Health check request failed"
[ "$STATUS" = "200" ] && pass "/health → $STATUS" || fail "/health returned $STATUS"

# ----------------------------------------------------------
# 2. List models
# ----------------------------------------------------------
echo ""
echo "=== 2. List models ==="
MODELS=$(curl -sf "${AUTH_HEADER[@]}" "$BASE/v1/models") || fail "List models request failed"
echo "$MODELS" | python3 -m json.tool
echo "$MODELS" | python3 -c "
import json, sys
data = json.load(sys.stdin)
names = [m['id'] for m in data.get('data', [])]
assert '$MODEL' in names, f'$MODEL not found in {names}'
print('Model $MODEL found in registry.')
" && pass "/v1/models" || fail "/v1/models did not return expected model"

# ----------------------------------------------------------
# 3. Chat completion — thinking ON (default)
# ----------------------------------------------------------
echo ""
echo "=== 3. Chat completion (thinking ON) ==="
RESP=$(curl -sf "${AUTH_HEADER[@]}" "$BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"$MODEL\",
    \"messages\": [{\"role\": \"user\", \"content\": \"What is 17 * 23? Show your reasoning.\"}],
    \"max_tokens\": 512
  }") || fail "Chat completion (thinking ON) request failed"
echo "$RESP" | python3 -m json.tool
echo "$RESP" | python3 -c "
import json, sys
resp = json.load(sys.stdin)
msg = resp['choices'][0]['message']
reasoning = msg.get('reasoning', '')
content = msg.get('content', '')
assert content, 'Empty content'
print(f'reasoning tokens: {len(reasoning.split())} words')
print(f'answer: {content[:120]}...')
" && pass "/v1/chat/completions (thinking ON)" || fail "Unexpected response shape"

# ----------------------------------------------------------
# 4. Chat completion — thinking OFF
# ----------------------------------------------------------
echo ""
echo "=== 4. Chat completion (thinking OFF) ==="
RESP=$(curl -sf "${AUTH_HEADER[@]}" "$BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"$MODEL\",
    \"messages\": [{\"role\": \"user\", \"content\": \"What is the capital of France?\"}],
    \"max_tokens\": 64,
    \"chat_template_kwargs\": {\"enable_thinking\": false}
  }") || fail "Chat completion (thinking OFF) request failed"
echo "$RESP" | python3 -c "
import json, sys
resp = json.load(sys.stdin)
content = resp['choices'][0]['message'].get('content', '')
print(f'answer: {content}')
assert content, 'Empty content'
" && pass "/v1/chat/completions (thinking OFF)" || fail "Unexpected response shape"

# ----------------------------------------------------------
# 5. Chat completion — thinking token budget
# ----------------------------------------------------------
echo ""
echo "=== 5. Chat completion (short thinking via max_tokens) ==="
RESP=$(curl -sf "${AUTH_HEADER[@]}" "$BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"$MODEL\",
    \"messages\": [{\"role\": \"user\", \"content\": \"Which is larger: 9.11 or 9.8?\"}],
    \"max_tokens\": 1024
  }") || fail "Chat completion (short) request failed"
echo "$RESP" | python3 -c "
import json, sys
resp = json.load(sys.stdin)
msg = resp['choices'][0]['message']
reasoning = msg.get('reasoning') or ''
print(f'reasoning chars: {len(reasoning)}')
print(f'answer: {msg.get(\"content\", \"\")}')
assert msg.get('content'), 'Empty content'
" && pass "/v1/chat/completions (with reasoning)" || fail "Unexpected response shape"

# ----------------------------------------------------------
# 6. Tokenize
# ----------------------------------------------------------
echo ""
echo "=== 6. Tokenize ==="
RESP=$(curl -sf "${AUTH_HEADER[@]}" "$BASE/tokenize" \
  -H "Content-Type: application/json" \
  -d "{\"model\": \"$MODEL\", \"prompt\": \"Hello, world!\"}") || fail "Tokenize request failed"
echo "$RESP" | python3 -c "
import json, sys
resp = json.load(sys.stdin)
tokens = resp.get('tokens', [])
assert len(tokens) > 0, 'No tokens returned'
print(f'token count: {len(tokens)}, tokens: {tokens}')
" && pass "/v1/tokenize" || fail "Unexpected tokenize response"

# ----------------------------------------------------------
# 7. Prometheus metrics
# ----------------------------------------------------------
echo ""
echo "=== 7. Prometheus metrics ==="
METRICS=$(curl -sf "${AUTH_HEADER[@]}" "$BASE/metrics") || fail "Metrics request failed"
echo "$METRICS" | head -20
echo "$METRICS" | grep -q "vllm" && pass "/metrics (vllm metrics present)" || fail "/metrics missing vllm entries"

# ----------------------------------------------------------
# 8. Tool calling
# ----------------------------------------------------------
echo ""
echo "=== 8. Tool calling ==="
RESP=$(curl -sf "${AUTH_HEADER[@]}" "$BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"$MODEL\",
    \"messages\": [{\"role\": \"user\", \"content\": \"What is the weather in New York City?\"}],
    \"tools\": [{
      \"type\": \"function\",
      \"function\": {
        \"name\": \"get_weather\",
        \"description\": \"Get current weather for a location\",
        \"parameters\": {
          \"type\": \"object\",
          \"properties\": {\"location\": {\"type\": \"string\"}},
          \"required\": [\"location\"]
        }
      }
    }],
    \"tool_choice\": \"auto\",
    \"max_tokens\": 512,
    \"chat_template_kwargs\": {\"enable_thinking\": false}
  }") || fail "Tool calling request failed"
echo "$RESP" | python3 -c "
import json, sys
resp = json.load(sys.stdin)
msg    = resp['choices'][0]['message']
finish = resp['choices'][0]['finish_reason']
print(f'finish_reason: {finish}')
tcs = msg.get('tool_calls') or []
assert tcs or finish == 'tool_calls', f'Expected tool_calls, got finish_reason={finish}'
if tcs:
    tc = tcs[0]
    print(f'tool: {tc[\"function\"][\"name\"]}')
    print(f'args: {tc[\"function\"][\"arguments\"]}')
" && pass "/v1/chat/completions (tool_calls)" || fail "No tool call in response"

# ----------------------------------------------------------
echo ""
echo "=================================================="
echo -e "${GREEN}All smoke tests passed.${NC}"
