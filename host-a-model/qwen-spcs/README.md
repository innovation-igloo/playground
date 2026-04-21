# Qwen3.5-27B + Multi-Agent Studio on Snowflake SPCS

Self-hosted inference of [Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2](https://huggingface.co/Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2) (AWQ 4-bit, quantized by [QuantTrio](https://huggingface.co/QuantTrio/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2-AWQ)) via vLLM on Snowpark Container Services, fronted by a LangGraph multi-agent server with a React chat UI.

## Architecture

| Component | Detail |
|---|---|
| **Qwen vLLM service** | |
| Model | Qwen3.5-27B v2, AWQ 4-bit (~21 GiB) |
| Quantization | AWQ (4-bit, data-free, by [QuantTrio](https://huggingface.co/QuantTrio/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2-AWQ)) |
| Serving engine | vLLM v0.19.1 (OpenAI-compatible API) |
| Compute pool | `GPU_NV_M` — 4x NVIDIA A10G (24 GiB each) |
| Tensor parallelism | 4 (one shard per GPU, ~5.25 GiB/GPU) |
| Max context | 32,768 tokens |
| GPU memory utilization | 0.85 |
| Endpoint | Public HTTPS with `Snowflake Token` auth |
| **Agent service** | |
| Runtime | LangGraph + FastAPI (Python), React chat UI (Vite + Tailwind) |
| Compute pool | `CPU_X64_S` — 1 node |
| Tool backends | **Cortex Analyst REST** and **Cortex Agents :run** — switchable at runtime via UI toggle |
| Config | `config.yaml` mounted from `@AGENT_STAGE` |
| Secret | `AGENT_PAT` — generic-string secret holding a PAT for Qwen + Cortex APIs |
| Endpoint | Public HTTPS — UI at `/`, API at `/chat` + `/health` |

> **AWQ v2 tradeoffs:** 24% shorter reasoning chains, +31.6% more correct solutions per token. -1.24% on HumanEval+, -7.2% on MMLU-Pro vs BF16 base. Ideal for agent/tool-calling workloads.

## Prerequisites

- Docker Desktop (linux/amd64 builds)
- Snowflake CLI (`snow`) — [install guide](https://docs.snowflake.com/en/developer-guide/snowflake-cli/index)
- `huggingface_hub` Python package (`pip install huggingface_hub`) — for AWQ weight download
- Node.js + npm — for local agent UI development (optional; the Docker build handles this)
- A Snowflake connection in `~/.snowflake/connections.toml` with a PAT as the `password` field
- Snowflake role with `CREATE COMPUTE POOL`, `CREATE SERVICE`, and `CREATE IMAGE REPOSITORY` grants

## Quick Start (Makefile)

Every step is wrapped in a `make` target. Run `make help` to see all available targets.

```bash
# 0. One-time config (copy templates, then edit)
cp .env.example .env                                        # set SNOW_CONNECTION + SNOWFLAKE_USER
cp agent/config.example.yaml agent/config.yaml              # edit after step 6
cp spcs/service_spec.example.yaml spcs/service_spec.yaml    # fill in your DB/schema/repo/stage
cp stage/upload_weights.example.sh stage/upload_weights.sh   # fill in your connection + stage
chmod +x stage/upload_weights.sh

# 1. Setup — provisions schema, warehouse, both pools, repos, stages, secret
make setup

# 2. Wait for GPU pool to go ACTIVE/IDLE
make qwen-pool-status

# 3. Build + push vLLM image
make qwen-docker-build
make qwen-docker-login
make qwen-docker-push

# 4. Download AWQ weights + upload to stage (~21 GiB)
make qwen-weights

# 5. Deploy Qwen service
make qwen-deploy

# 6. Get Qwen endpoint URL → paste into agent/config.yaml
make qwen-endpoints

# 7. Populate agent PAT secret
make agent-secret-rotate

# 8. Upload agent config to stage
make agent-stage-config

# 9. Build + push agent image (multi-stage: React UI + Python)
make agent-docker-build
make agent-docker-login
make agent-docker-push

# 10. Deploy agent service
make agent-deploy

# 11. Get agent endpoint URL
make agent-endpoints
```

Test the live Qwen service:

```bash
ENDPOINT=https://<url-from-step-6> make qwen-smoke-test
```

Stop billing:

```bash
make qwen-nuke            # Drop Qwen service + suspend GPU pool
make agent-nuke           # Drop agent service + suspend CPU pool
```

## Configuration Files

This project uses an **example file pattern** — real config files are gitignored, and `.example` templates are committed. Copy each example, then fill in your values.

| Example (committed) | Real file (gitignored) | What to edit |
|---|---|---|
| `.env.example` | `.env` | Snowflake connection name, user, database, schema, warehouse, pool names |
| `agent/config.example.yaml` | `agent/config.yaml` | Qwen endpoint URL (from step 6), Snowflake account, semantic view FQN |
| `spcs/service_spec.example.yaml` | `spcs/service_spec.yaml` | Image repo path, model weights stage path |
| `stage/upload_weights.example.sh` | `stage/upload_weights.sh` | Snowflake connection name, stage FQN |

All SQL scripts (`setup.sql`, `spcs/create_service.sql`, `agent/spcs/create_service.sql`) are fully parameterized via `<% ... %>` variables injected from `.env` by the Makefile. You should never need to edit the SQL files directly.

## Dual Backend Toggle

The agent supports two tool backends for querying your semantic model, switchable at runtime via a pill toggle in the UI header:

| Backend | Label | How it works |
|---|---|---|
| **Cortex Analyst REST** | `Analyst` | Calls the `/api/v2/cortex/analyst/message` REST API directly via httpx. Generates SQL from natural language using your semantic view, executes it, and returns results. |
| **Cortex Agents :run** | `Agent` | Calls a named Cortex Agent via the `/api/v2/databases/.../agents/<name>:run` endpoint. The agent handles SQL generation, execution, and response formatting server-side. |

Both backends use `Bearer <PAT>` + `X-Snowflake-Authorization-Token-Type: PROGRAMMATIC_ACCESS_TOKEN` for authentication.

Configure both in `agent/config.yaml`:

```yaml
tools:
  cortex_analyst:
    backend: "rest"                  # default backend
    semantic_view: "DB.SCHEMA.YOUR_SEMANTIC_VIEW"
    cortex_agents:
      database: "YOUR_DB"
      schema: "YOUR_SCHEMA"
      agent_name: "YOUR_CORTEX_AGENT"
      timeout_seconds: 120
    rest:
      timeout_seconds: 60
      stream: true
```

## Step-by-Step Details

### Step 1 — Provision Snowflake Objects

```bash
make setup
```

Creates every Snowflake object both services need in a single `setup.sql` execution. Run this once.

<details>
<summary>What this provisions</summary>

Runs as ACCOUNTADMIN, then SYSADMIN, then the POC role. All identifiers come from `.env`.

| Object | Name (from .env) | Purpose |
|--------|-------------------|---------|
| Role | `SNOWFLAKE_ROLE` | Owner of all POC objects |
| Database | `SNOWFLAKE_DATABASE` | Top-level container |
| Schema | `SNOWFLAKE_SCHEMA` | All services, stages, repos live here |
| Warehouse | `SNOWFLAKE_WAREHOUSE` | Admin DDL queries (not used for inference) |
| GPU compute pool | `QWEN_POOL_NAME` | 4x A10G for vLLM (`GPU_NV_M`) |
| CPU compute pool | `AGENT_POOL_NAME` | LangGraph agent (`CPU_X64_S`) |
| Image repo | `QWEN_IMAGE_REPO_NAME` | vLLM container image |
| Image repo | `AGENT_REPO_NAME` | Agent container image |
| Stage | `QWEN_STAGE_NAME` | AWQ weights + `service_spec.yaml` |
| Stage | `AGENT_STAGE_NAME` | Runtime-mounted `config.yaml` |
| Secret | `AGENT_SECRET_NAME` | Placeholder — populated in step 7 |

</details>

### Step 2 — Wait for GPU Pool

```bash
make qwen-pool-status
```

Runs `DESCRIBE COMPUTE POOL`. Re-run until the state shows **ACTIVE** or **IDLE**. Pool provisioning can take a few minutes on first create.

### Step 3 — Build + Push vLLM Image

```bash
make qwen-docker-build    # docker build --platform linux/amd64
make qwen-docker-login    # snow spcs image-registry login
make qwen-docker-push     # docker tag + docker push to Snowflake registry
```

Or all three at once:

```bash
make qwen-docker
```

### Step 4 — Download AWQ Weights + Upload to Stage

```bash
make qwen-weights
```

Downloads the AWQ 4-bit weights (~21 GiB, 8 safetensor shards) from [QuantTrio's HuggingFace repo](https://huggingface.co/QuantTrio/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2-AWQ) into `qwen-opus-dist-awq/`, then uploads them to your model weights stage. Also copies `spcs/service_spec.yaml` to the same stage.

Verify the upload:

```bash
make qwen-stage-list
```

### Step 5 — Deploy Qwen Service

```bash
make qwen-deploy
```

Creates the SPCS service from the staged `service_spec.yaml`. The service mounts the model weights stage at `/models` and requests 4 GPUs + 100 GiB RAM.

Model loading takes ~5 minutes with AWQ weights (~9 minutes with BF16). Monitor progress:

```bash
make qwen-service-logs
```

### Step 6 — Get Qwen Endpoint URL

```bash
make qwen-endpoints
```

Copy the HTTPS URL and paste it into `agent/config.yaml` under `llm.base_url`:

```yaml
llm:
  base_url: "https://<url-from-this-step>/v1"
  model: "qwen3.5-27b"
```

> The endpoint URL changes when you drop and recreate the service. Use `make qwen-upgrade` instead of drop/redeploy to preserve the URL.

### Step 7 — Populate Agent PAT Secret

```bash
make agent-secret-rotate
```

Reads the PAT from `~/.snowflake/connections.toml` and stores it in the Snowflake secret. The agent container receives this at runtime as the `SNOWFLAKE_PAT` environment variable.

You can also pass a PAT explicitly:

```bash
PAT=<your-pat> make agent-secret-rotate
```

### Step 8 — Upload Agent Config to Stage

```bash
make agent-stage-config
```

Copies `agent/config.yaml` to the agent stage with `--overwrite`. The agent service mounts this stage at `/app/config/` inside the container.

### Step 9 — Build + Push Agent Image

```bash
make agent-docker-build    # multi-stage: Node builds React UI, Python runtime ships the bundle
make agent-docker-login    # snow spcs image-registry login
make agent-docker-push     # docker tag + docker push to Snowflake registry
```

Or all three at once:

```bash
make agent-docker
```

<details>
<summary>Multi-stage build details</summary>

The agent `Dockerfile` (`agent/Dockerfile`) uses two stages:

1. **Stage 1 (Node)** — Installs npm dependencies and runs `npm run build` in `agent/ui/`, producing a static React bundle.
2. **Stage 2 (Python)** — Installs Python dependencies from `agent/pyproject.toml`, copies the built UI bundle into `/app/ui-dist`, and sets the entrypoint to launch the FastAPI server via `uvicorn`.

</details>

### Step 10 — Deploy Agent Service

```bash
make agent-deploy
```

Creates the agent SPCS service on the CPU compute pool.

### Step 11 — Get Agent Endpoint URL

```bash
make agent-endpoints
```

The public URL serves:

| Path | Description |
|------|-------------|
| `/` | React chat UI with backend toggle |
| `/chat` | SSE streaming chat API (accepts `backend` field: `"rest"` or `"cortex_agents"`) |
| `/health` | Health check |

## Authentication

SPCS public endpoints require a **Programmatic Access Token (PAT)**, not a session token. The auth header format is:

```
Authorization: Snowflake Token="<your-PAT>"
```

The smoke test (`test/smoke_test.sh`) handles this automatically by reading the PAT from your Snow CLI connection config. For manual curl calls:

```bash
PAT=$(python3 -c "
import tomllib, pathlib, os
conn = os.getenv('SNOW_CONNECTION', 'default')
with open(pathlib.Path.home() / '.snowflake' / 'connections.toml', 'rb') as f:
    cfg = tomllib.load(f)
print(cfg[conn]['password'])
")

curl -H "Authorization: Snowflake Token=\"${PAT}\"" \
  https://<endpoint-url>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.5-27b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 256
  }'
```

> **Note:** `Authorization: Bearer <token>` does NOT work for SPCS ingress — Snowflake returns a 302 redirect. You must use the `Snowflake Token="..."` format. (The Cortex REST APIs use `Bearer` + `X-Snowflake-Authorization-Token-Type` instead — this is handled internally by the agent.)

## API Reference

The served model name is `qwen3.5-27b`. All endpoints are verified by the smoke test suite.

| # | Endpoint | Method | Path | Notes |
|---|---|---|---|---|
| 1 | Health | GET | `/health` | Returns 200 when model is loaded and ready |
| 2 | Models | GET | `/v1/models` | Lists served model with `max_model_len` |
| 3 | Chat (thinking ON) | POST | `/v1/chat/completions` | Default mode — response includes `reasoning` field |
| 4 | Chat (thinking OFF) | POST | `/v1/chat/completions` | Set `chat_template_kwargs: {enable_thinking: false}` at top level |
| 5 | Chat (with reasoning) | POST | `/v1/chat/completions` | Standard request with reasoning — increase `max_tokens` to avoid truncation |
| 6 | Tokenize | POST | `/tokenize` | **Not** `/v1/tokenize` (returns 404) |
| 7 | Prometheus metrics | GET | `/metrics` | vLLM internal metrics in Prometheus format |
| 8 | Tool calling | POST | `/v1/chat/completions` | Pass `tools` array + `tool_choice: auto` |

### Example: Thinking ON (default)

```json
{
  "model": "qwen3.5-27b",
  "messages": [{"role": "user", "content": "What is 17 * 23? Show your reasoning."}],
  "max_tokens": 512
}
```

Response includes `choices[0].message.reasoning` (chain-of-thought) and `choices[0].message.content` (final answer).

### Example: Thinking OFF

```json
{
  "model": "qwen3.5-27b",
  "messages": [{"role": "user", "content": "What is the capital of France?"}],
  "max_tokens": 64,
  "chat_template_kwargs": {"enable_thinking": false}
}
```

### Example: Tool Calling

```json
{
  "model": "qwen3.5-27b",
  "messages": [{"role": "user", "content": "What is the weather in NYC?"}],
  "tools": [{
    "type": "function",
    "function": {
      "name": "get_weather",
      "description": "Get current weather for a location",
      "parameters": {
        "type": "object",
        "properties": {"location": {"type": "string"}},
        "required": ["location"]
      }
    }
  }],
  "tool_choice": "auto",
  "max_tokens": 256
}
```

### Multi-Turn Conversations

The API is stateless — there is no server-side session. For multi-turn conversations, accumulate the message history on the client and send it with each request:

```json
{
  "model": "qwen3.5-27b",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What's the capital of France?"},
    {"role": "assistant", "content": "Paris."},
    {"role": "user", "content": "What's its population?"}
  ],
  "max_tokens": 256
}
```

## Monitoring

### Qwen service

```bash
make qwen-service-logs       # Tail last 100 lines of container logs
make qwen-service-status     # Show running containers
make qwen-service-describe   # Full service description
make qwen-service-events     # Last 50 service events (startup errors, OOM, probes)
make qwen-pool-status        # Describe GPU compute pool
```

### Agent service

```bash
make agent-service-logs      # Tail last 100 lines of agent container logs
make agent-service-status    # Show agent service container health
make agent-service-describe  # Full agent service description
make agent-service-events    # Last 50 agent service events
make agent-pool-status       # Describe CPU compute pool
```

## Cost Management

```bash
make qwen-pool-suspend       # Suspend GPU pool (stops node billing)
make qwen-service-suspend    # Suspend Qwen service (config preserved)
make qwen-nuke               # Drop Qwen service + suspend GPU pool

make agent-pool-suspend      # Suspend CPU pool
make agent-service-suspend   # Suspend agent service
make agent-nuke              # Drop agent service + suspend CPU pool
```

Both pools auto-suspend after 1 hour of no running services. Auto-resume triggers when a service is submitted.

To update the agent config without redeploying:

```bash
# edit agent/config.yaml, then:
make agent-upgrade           # re-uploads config + bounces the service
```

## Local Development (Agent)

```bash
make agent-install           # pip install -e agent/
make agent-ui-install        # npm install in agent/ui
make agent-dev               # Start FastAPI (8080) + Vite (5173) in parallel
make agent-test              # pytest unit tests
make agent-health            # curl /health
make agent-chat              # Send a test message (set MSG="your question")
```

## Troubleshooting

| Issue | Fix |
|---|---|
| CUDA OOM on startup | Reduce `--max-model-len` and `--gpu-memory-utilization` in `docker/entrypoint.sh`. AWQ at 64K + 0.90 OOM'd during CUDA graph compilation on A10G. 32K + 0.85 fits comfortably. For 64K, move to `GPU_NV_L` (8x A100-40GB). |
| 302 redirect on API calls | You're using `Bearer` auth — SPCS requires `Snowflake Token="<PAT>"` format instead. |
| 401 from Cortex Analyst REST | Ensure auth uses `Bearer <PAT>` + `X-Snowflake-Authorization-Token-Type: PROGRAMMATIC_ACCESS_TOKEN`, not `Snowflake Token`. |
| DNS resolution failure after redeploy | The endpoint URL changes when you drop and recreate the service. Re-run `make qwen-endpoints` or `make agent-endpoints` to get the new URL. |
| `tokenizer.json` is 133 bytes | Incomplete AWQ download. Re-run `make qwen-weights` to re-fetch from HuggingFace. |
| Service stuck in PENDING | Check `make qwen-service-status` or `make agent-service-status` — likely GPU/CPU capacity. Try a different region or wait. |
| Slow first request | Model loads into GPU on first inference after service start. Subsequent requests are fast due to prefix caching. |
| Public endpoint 403 | Ensure the calling role has the service role grant. |
| Thinking OFF returns empty content | `chat_template_kwargs` must be a top-level field, not nested inside `extra_body`. |
| Test 5 returns empty content | Reasoning can consume all `max_tokens` before content is generated. Increase `max_tokens`. |
| Agent config not picked up | Re-run `make agent-stage-config` to re-upload, then `make agent-upgrade` to bounce the service. |
| Agent can't reach Qwen endpoint | Verify the `base_url` in `agent/config.yaml` matches the URL from `make qwen-endpoints`. Check that the PAT secret is populated (`make agent-secret-rotate`). |
| LLM hallucinating tool results | Lower `temperature` in `agent/config.yaml` (0.2 recommended) and ensure the system prompt enforces data grounding. |

## File Structure

```
qwen-spcs/
├── .env.example                       # Template: connection, user, all identifiers
├── .gitignore
├── Makefile                           # All deployment, test, and teardown targets
├── README.md
├── setup.sql                          # One-shot Snowflake object provisioning (both services)
├── docker/
│   ├── Dockerfile                     # vLLM v0.19.1 base image
│   └── entrypoint.sh                  # vllm serve flags (TP=4, 32K ctx, AWQ, 0.85 mem)
├── spcs/
│   ├── service_spec.example.yaml      # Template: fill in your image repo + stage paths
│   └── create_service.sql             # CREATE SERVICE + GRANT for Qwen (parameterized)
├── stage/
│   └── upload_weights.example.sh      # Template: fill in your connection + stage
├── test/
│   ├── smoke_test.sh                  # 8 curl-based API tests with auto PAT auth
│   └── client.py                      # Python OpenAI SDK examples (4 patterns)
├── agent/                             # LangGraph agent server + React UI
│   ├── config.example.yaml            # Template — edit after step 6
│   ├── Dockerfile                     # Multi-stage: Node (UI build) + Python (runtime)
│   ├── pyproject.toml                 # Python dependencies
│   ├── agent/                         # LangGraph graph, nodes, state
│   │   ├── graph.py                   # StateGraph definition + compilation
│   │   ├── nodes.py                   # call_model, call_tools, should_continue
│   │   ├── llm.py                     # LLM client + PAT resolver
│   │   ├── config.py                  # Config loader (Pydantic models)
│   │   ├── state.py                   # Graph state schema
│   │   └── tools/                     # Tool implementations
│   │       ├── base.py                # Base class + shared tool interface
│   │       ├── cortex_agents.py       # Cortex Agents :run backend
│   │       ├── cortex_rest.py         # Cortex Analyst REST backend
│   │       ├── cortex_mcp.py          # Cortex MCP backend (experimental)
│   │       └── cortex_threads.py      # Thread management for multi-turn
│   ├── server/                        # FastAPI application
│   │   ├── app.py                     # Routes, dual-backend startup, per-request selection
│   │   ├── models.py                  # Pydantic request/response models
│   │   ├── middleware.py              # CORS, auth middleware
│   │   └── logging_config.py          # Structured logging
│   ├── spcs/
│   │   ├── create_service.sql         # CREATE SERVICE + GRANT for agent
│   │   └── agent_service_spec.example.yaml
│   ├── tests/                         # pytest suite
│   │   ├── test_graph.py
│   │   ├── test_tools.py
│   │   ├── test_config.py
│   │   └── test_middleware.py
│   └── ui/                            # React chat UI (Vite + Tailwind)
│       ├── index.html
│       ├── package.json
│       ├── vite.config.ts
│       ├── tailwind.config.js
│       └── src/
│           ├── App.tsx                # Main app with backend toggle state
│           ├── main.tsx
│           ├── hooks/useChat.ts       # SSE chat hook (accepts backend param)
│           └── components/
│               ├── BackendToggle.tsx   # Analyst/Agent pill toggle
│               ├── ChatWindow.tsx
│               ├── ChatInput.tsx
│               ├── MessageBubble.tsx
│               ├── ToolCallCard.tsx
│               ├── TokenPills.tsx
│               ├── SnowflakeMark.tsx
│               └── SnowflakePulse.tsx
└── docs/
    └── langgraph-deep-dive.md
```

## Roadmap

- [x] LangGraph agent server — multi-turn tool-calling agent backed by self-hosted model
- [x] React chat UI — browser-based interface for testing conversations
- [x] Streaming support — SSE streaming for real-time token delivery
- [x] Dual backend toggle — switch between Cortex Analyst REST and Cortex Agents at runtime
- [x] Data-grounded system prompt — LLM faithfully reports tool results without hallucination
- [ ] Cortex Search tool — RAG over internal document corpus
- [ ] Multi-model routing — fallback to Cortex-hosted models when GPU pool is suspended
