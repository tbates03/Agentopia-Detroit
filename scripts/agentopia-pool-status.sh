#!/bin/bash
set -u
for SPEC in "SOCIAL 8084" "CITIZEN 8081" "STRATEGY 8082" "CYBER 8083"; do
  NAME="${SPEC%% *}"
  PORT="${SPEC##* }"
  printf '%-10s ' "$NAME"
  if DATA="$(curl -fsS "http://127.0.0.1:$PORT/slots" 2>/dev/null)"; then
    printf '%s' "$DATA" | python3 -c 'import sys,json; d=json.load(sys.stdin); busy=sum(1 for x in d if x.get("is_processing")); print("%d/%d slots busy" % (busy,len(d)))'
  else
    echo "OFFLINE"
  fi
done
