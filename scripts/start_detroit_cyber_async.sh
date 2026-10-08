#!/bin/bash
set -u
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "$APP/logs" "$APP/runtime/llama"
LOG="$APP/logs/llama-cyber.log"
health(){ curl -fsS --max-time 3 http://127.0.0.1:8083/health >/dev/null 2>&1; }
health && { touch "$APP/runtime/llama/cyber_available"; exit 0; }
rm -f "$APP/runtime/llama/cyber_available"
sleep 20
health && { touch "$APP/runtime/llama/cyber_available"; exit 0; }
LLAMA="$(command -v llama-server 2>/dev/null || true)"
[ -n "$LLAMA" ] || [ ! -x /opt/homebrew/bin/llama-server ] || LLAMA=/opt/homebrew/bin/llama-server
[ -n "$LLAMA" ] || exit 0
FILE=WhiteRabbitNeo_WhiteRabbitNeo-V3-7B-Q4_K_M.gguf
REPO=bartowski/WhiteRabbitNeo_WhiteRabbitNeo-V3-7B-GGUF
MODEL=""
for base in "$HOME/.cache/huggingface/hub/models--bartowski--WhiteRabbitNeo_WhiteRabbitNeo-V3-7B-GGUF/snapshots" "$HOME/.cache/llama.cpp" "$HOME/Library/Caches/llama.cpp" "$APP/models"; do
  [ -d "$base" ] || continue
  MODEL="$(find "$base" -type f -name "$FILE" -print -quit 2>/dev/null || true)"
  [ -n "$MODEL" ] && break
done
: > "$LOG"
if [ -n "$MODEL" ]; then
  nohup "$LLAMA" -m "$MODEL" --alias agentopia-cyber --host 127.0.0.1 --port 8083 --parallel 6 --kv-unified --kv-unified-per-slot 16384 --cont-batching --threads 12 --threads-batch 12 --batch-size 2048 --ubatch-size 512 --n-gpu-layers all --flash-attn on --metrics >> "$LOG" 2>&1 &
else
  nohup "$LLAMA" -hf "$REPO" --hf-file "$FILE" --alias agentopia-cyber --host 127.0.0.1 --port 8083 --parallel 6 --kv-unified --kv-unified-per-slot 16384 --cont-batching --threads 12 --threads-batch 12 --batch-size 2048 --ubatch-size 512 --n-gpu-layers all --flash-attn on --metrics >> "$LOG" 2>&1 &
fi
PID=$!
echo "$PID" > "$APP/runtime/llama/cyber.pid"
for _ in $(seq 1 180); do
  health && { touch "$APP/runtime/llama/cyber_available"; exit 0; }
  kill -0 "$PID" 2>/dev/null || exit 0
  sleep 2
done
exit 0
