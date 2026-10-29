#!/bin/bash
# Run the optional cloud scan with a hard deadline and a retained diagnostic log.
set -euo pipefail
if [ "$#" -ne 3 ]; then
  echo "usage: $0 <output_dir> <log_path> <timeout_seconds>" >&2
  exit 2
fi
OUT_DIR="$1"
LOG_PATH="$2"
LIMIT="$3"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
umask 077
# Preserve the latest attempt outside the collector's temporary directory.
# Audit runs pass their sandbox log path instead of the normal log directory.
if command -v timeout >/dev/null 2>&1; then
  DEADLINE=timeout
elif command -v gtimeout >/dev/null 2>&1; then
  DEADLINE=gtimeout
else
  echo "ERROR: cloud collection skipped: no timeout command available" > "$LOG_PATH"
  exit 127
fi
rc=0
"$DEADLINE" --kill-after=5 "$LIMIT" bash "$SCRIPT_DIR/collect_cloud_tokens.sh" "$OUT_DIR" > "$LOG_PATH" 2>&1 || rc=$?
if [ "$rc" -eq 124 ]; then
  echo "ERROR: cloud collection timed out after ${LIMIT}s" >> "$LOG_PATH"
elif [ "$rc" -eq 137 ]; then
  echo "ERROR: cloud collection was killed (deadline or external signal)" >> "$LOG_PATH"
elif [ "$rc" -ne 0 ]; then
  echo "ERROR: cloud collection exited with status $rc" >> "$LOG_PATH"
fi
exit "$rc"
