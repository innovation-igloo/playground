#!/bin/bash
set -euo pipefail

exec python3 -m vllm.entrypoints.openai.api_server \
  --model /models/qwen-opus-dist-awq \
  --served-model-name qwen3.5-27b \
  --tensor-parallel-size 4 \
  --language-model-only \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --enable-prefix-caching \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.85 \
  --quantization awq \
  --host 0.0.0.0 \
  --port 8000
