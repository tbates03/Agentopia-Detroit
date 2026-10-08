#!/bin/bash
set -u
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "$APP/logs" "$APP/runtime/llama"
LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-$(command -v llama-server 2>/dev/null || true)}"
[ -n "$LLAMA_SERVER_BIN" ] || [ ! -x /opt/homebrew/bin/llama-server ] || LLAMA_SERVER_BIN=/opt/homebrew/bin/llama-server
[ -n "$LLAMA_SERVER_BIN" ] || [ ! -x /usr/local/bin/llama-server ] || LLAMA_SERVER_BIN=/usr/local/bin/llama-server
[ -n "$LLAMA_SERVER_BIN" ] || { echo "ERROR llama-server missing"; exit 2; }
THREADS="$(sysctl -n hw.perflevel0.physicalcpu 2>/dev/null || echo 12)"
[ "$THREADS" -gt 12 ] && THREADS=12
[ "$THREADS" -lt 4 ] && THREADS=4
CTX=16384

health(){ curl -fsS --max-time 3 "http://127.0.0.1:$1/health" >/dev/null 2>&1; }
find_cached(){
  local repo="$1" file="$2" modeldir hit
  modeldir="models--${repo//\//--}"
  for base in "$HOME/.cache/huggingface/hub/$modeldir/snapshots" "$HOME/.cache/llama.cpp" "$HOME/Library/Caches/llama.cpp" "$APP/models"; do
    [ -d "$base" ] || continue
    hit="$(find "$base" -type f -name "$file" -print -quit 2>/dev/null || true)"
    [ -n "$hit" ] && { printf '%s\n' "$hit"; return 0; }
  done
  return 1
}
wait_model(){
  local name="$1" port="$2" pid="$3" i=0
  while [ "$i" -lt 150 ]; do
    health "$port" && return 0
    kill -0 "$pid" 2>/dev/null || return 1
    sleep 2
    i=$((i+1))
  done
  return 1
}
stop_listener(){
  local port="$1" pid cmd
  pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  [ -n "$pid" ] || return 0
  health "$port" && return 0
  cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  case "$cmd" in *llama-server*) kill -TERM "$pid" 2>/dev/null || true; sleep 2;; *) echo "ERROR port $port occupied by $cmd"; return 1;; esac
}
start_model(){
  local name="$1" port="$2" repo="$3" file="$4" alias="$5" slots="$6" pidfile localfile log pid
  health "$port" && { echo "$name already healthy"; return 0; }
  pidfile="$APP/runtime/llama/$name.pid"
  if [ -f "$pidfile" ]; then
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "$name already loading pid=$pid"
      wait_model "$name" "$port" "$pid" && return 0
      kill -TERM "$pid" 2>/dev/null || true
      sleep 2
    fi
  fi
  stop_listener "$port" || return 1
  log="$APP/logs/llama-$name.log"
  : > "$log"
  localfile="$(find_cached "$repo" "$file" || true)"
  if [ -n "$localfile" ]; then
    echo "$name using cached model: $localfile"
    nohup "$LLAMA_SERVER_BIN" -m "$localfile" --alias "$alias" --host 127.0.0.1 --port "$port" \
      --parallel "$slots" --kv-unified --kv-unified-per-slot "$CTX" --cont-batching \
      --threads "$THREADS" --threads-batch "$THREADS" --batch-size 2048 --ubatch-size 512 \
      --n-gpu-layers all --flash-attn on --metrics >> "$log" 2>&1 &
  else
    echo "$name cache not found; using Hugging Face resolver"
    nohup "$LLAMA_SERVER_BIN" -hf "$repo" --hf-file "$file" --alias "$alias" --host 127.0.0.1 --port "$port" \
      --parallel "$slots" --kv-unified --kv-unified-per-slot "$CTX" --cont-batching \
      --threads "$THREADS" --threads-batch "$THREADS" --batch-size 2048 --ubatch-size 512 \
      --n-gpu-layers all --flash-attn on --metrics >> "$log" 2>&1 &
  fi
  pid=$!
  printf '%s\n' "$pid" > "$pidfile"
  wait_model "$name" "$port" "$pid"
}

# Only the three core pools block world startup.
start_model social 8084 LiquidAI/LFM2.5-350M-GGUF LFM2.5-350M-QAD-Q4_0.gguf agentopia-social 48 || { echo "SOCIAL FAILED"; tail -80 "$APP/logs/llama-social.log"; exit 21; }
start_model citizen 8081 LiquidAI/LFM2.5-1.2B-Instruct-GGUF LFM2.5-1.2B-Instruct-QAD-Q4_0.gguf agentopia-citizen 32 || { echo "CITIZEN FAILED"; tail -80 "$APP/logs/llama-citizen.log"; exit 22; }
start_model strategy 8082 LiquidAI/LFM2.5-2.6B-GGUF LFM2.5-2.6B-QAD-Q4_0.gguf agentopia-strategy 8 || { echo "STRATEGY FAILED"; tail -80 "$APP/logs/llama-strategy.log"; exit 23; }
exit 0
