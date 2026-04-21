#!/bin/bash
# =============================================================
# stage/upload_weights.sh
# Downloads Qwen3.5-27B AWQ weights from HuggingFace and uploads
# them (plus service_spec.yaml) to the Snowflake model stage.
#
# Prerequisites:
#   pip install huggingface_hub
#   snow CLI configured with SNOW_CONNECTION
# =============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi
SNOW_CONNECTION="${SNOW_CONNECTION:-default}"

HF_REPO="QuantTrio/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2-AWQ"
MODEL_DIR="$SCRIPT_DIR/../qwen-opus-dist-awq"
SPEC_DIR="$SCRIPT_DIR/../spcs"
STAGE="@YOUR_DATABASE.YOUR_SCHEMA.YOUR_MODEL_STAGE"

echo "=== Step 1: Download AWQ weights from HuggingFace (~21 GiB) ==="
python3 - <<PY
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="$HF_REPO",
    local_dir="$MODEL_DIR",
    local_dir_use_symlinks=False,
)
PY
echo "Download complete."

echo ""
echo "=== Step 2: Upload model directory to stage ==="
snow stage copy "$MODEL_DIR" "${STAGE}/qwen-opus-dist-awq/" \
  -c "$SNOW_CONNECTION" --recursive --overwrite

echo ""
echo "=== Step 3: Upload service spec ==="
snow stage copy "$SPEC_DIR/service_spec.yaml" "${STAGE}/" \
  -c "$SNOW_CONNECTION" --overwrite

echo ""
echo "=== Done ==="
snow sql -c "$SNOW_CONNECTION" -q "LIST ${STAGE};"
