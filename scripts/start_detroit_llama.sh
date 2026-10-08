#!/bin/bash
set -u

APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "$APP/logs" "$APP/runtime/llama"

LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-$(command -v llama-server 2>/dev/null || true)}"
[ -n "$LLAMA_SERVER_BIN" ] || [ ! -x /opt/homebrew/bin/llama-server ] || LLAMA_SERVER_BIN=/opt/homebrew/bin/llama-server
[ -n "$LLAMA_SERVER_BIN" ] || [ ! -x /usr/local/bin/llama-server ] || LLAMA_SERVER_BIN=/usr/local/bin/llama-server
[ -n "$LLAMA_SERVER_BIN" ] || { echo "ERROR llama-server missing"; exit 2; }

detect_mem_gb(){
  local bytes="" kb=""
  bytes="$(sysctl -n hw.memsize 2>/dev/null || true)"
  if [ -z "$bytes" ] && [ -r /proc/meminfo ]; then
    kb="$(awk '/MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || true)"
    [ -z "$kb" ] || bytes=$((kb * 1024))
  fi
  if [ -n "$bytes" ] && [ "$bytes" -gt 0 ] 2>/dev/null; then
    echo $((bytes / 1024 / 1024 / 1024))
  else
    echo 0
  fi
}

detect_threads(){
  local n=""
  n="$(sysctl -n hw.perflevel0.physicalcpu 2>/dev/null || true)"
  [ -n "$n" ] || n="$(command -v nproc >/dev/null 2>&1 && nproc || true)"
  [ -n "$n" ] || n="$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)"
  [ -n "$n" ] || n=4
  [ "$n" -gt 12 ] && n=12
  [ "$n" -lt 2 ] && n=2
  echo "$n"
}

MEM_GB="$(detect_mem_gb)"
THREADS="${AGENTOPIA_THREADS:-$(detect_threads)}"
PROFILE="${AGENTOPIA_PROFILE:-auto}"

if [ "$PROFILE" = "auto" ]; then
  if [ "$MEM_GB" -ge 48 ]; then
    PROFILE=performance
  elif [ "$MEM_GB" -ge 24 ]; then
    PROFILE=balanced
  else
    PROFILE=light
  fi
fi

case "$PROFILE" in
  light)
    CTX=8192
    SOCIAL_SLOTS=8
    CITIZEN_SLOTS=4
    STRATEGY_SLOTS=2
    ;;
  balanced)
    CTX=12288
    SOCIAL_SLOTS=16
    CITIZEN_SLOTS=8
    STRATEGY_SLOTS=4
    ;;
  performance)
    CTX=16384
    SOCIAL_SLOTS=48
    CITIZEN_SLOTS=32
    STRATEGY_SLOTS=8
    ;;
  *)
    echo "ERROR unknown AGENTOPIA_PROFILE=$PROFILE (use auto, light, balanced, performance)"
    exit 3
    ;;
esac

CTX="${AGENTOPIA_CONTEXT_TOKENS:-$CTX}"
SOCIAL_SLOTS="${AGENTOPIA_SOCIAL_SLOTS:-$SOCIAL_SLOTS}"
CITIZEN_SLOTS="${AGENTOPIA_CITIZEN_SLOTS:-$CITIZEN_SLOTS}"
STRATEGY_SLOTS="${AGENTOPIA_STRATEGY_SLOTS:-$STRATEGY_SLOTS}"
GPU_LAYERS="${AGENTOPIA_GPU_LAYERS:-all}"

echo "============================================================"
echo "AGENTOPIA DETROIT - RIGHT-SIZED LOCAL MODEL POOL"
echo "============================================================"
echo "Profile       : $PROFILE"
echo "Detected RAM  : ${MEM_GB} GB"
echo "Threads       : $THREADS"
echo "Context       : $CTX"
echo "Social slots  : $SOCIAL_SLOTS"
echo "Citizen slots : $CITIZEN_SLOTS"
echo "Strategy slots: $STRATEGY_SLOTS"
echo "GPU layers    : $GPU_LAYERS"
echo

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
  case "$cmd" in
    *llama-server*) kill -TERM "$pid" 2>/dev/null || true; sleep 2;;
    *) echo "ERROR port $port occupied by $cmd"; return 1;;
  esac
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
      --n-gpu-layers "$GPU_LAYERS" --flash-attn on --metrics >> "$log" 2>&1 &
  else
    echo "$name cache not found; requesting official configured model via Hugging Face resolver"
    nohup "$LLAMA_SERVER_BIN" -hf "$repo" --hf-file "$file" --alias "$alias" --host 127.0.0.1 --port "$port" \
      --parallel "$slots" --kv-unified --kv-unified-per-slot "$CTX" --cont-batching \
      --threads "$THREADS" --threads-batch "$THREADS" --batch-size 2048 --ubatch-size 512 \
      --n-gpu-layers "$GPU_LAYERS" --flash-attn on --metrics >> "$log" 2>&1 &
  fi

  pid=$!
  printf '%s\n' "$pid" > "$pidfile"
  wait_model "$name" "$port" "$pid"
}

# Three core right-sized pools. These block world startup because the
# persistent simulation expects social, citizen and strategy capacity.
start_model social 8084 LiquidAI/LFM2.5-350M-GGUF LFM2.5-350M-QAD-Q4_0.gguf agentopia-social "$SOCIAL_SLOTS" || {
  echo "SOCIAL FAILED"
  tail -80 "$APP/logs/llama-social.log"
  exit 21
}

start_model citizen 8081 LiquidAI/LFM2.5-1.2B-Instruct-GGUF LFM2.5-1.2B-Instruct-QAD-Q4_0.gguf agentopia-citizen "$CITIZEN_SLOTS" || {
  echo "CITIZEN FAILED"
  tail -80 "$APP/logs/llama-citizen.log"
  exit 22
}

start_model strategy 8082 LiquidAI/LFM2.5-2.6B-GGUF LFM2.5-2.6B-QAD-Q4_0.gguf agentopia-strategy "$STRATEGY_SLOTS" || {
  echo "STRATEGY FAILED"
  tail -80 "$APP/logs/llama-strategy.log"
  exit 23
}

echo
echo "RIGHT-SIZED MODEL POOL READY"
exit 0
