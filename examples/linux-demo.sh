#!/usr/bin/env bash
# First use: prepare once, rehearse once, and show the terminal report.
# Repeat with the same arguments to reuse only the verified prepared runtime.
set -euo pipefail
if [ "$#" -ne 3 ]; then
  printf 'Usage: bash examples/linux-demo.sh PYTHON_3_12_3 POSTGRES_18_6_BIN NATIVE_WORK_PARENT\n' >&2
  exit 2
fi
SCHEMA_PYTHON="$1"
SCHEMA_PG_BIN="$2"
SCHEMA_PARENT="$3"
SCHEMA_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA_ENV="$SCHEMA_PARENT/environment"
cd -- "$SCHEMA_ROOT"
"$SCHEMA_PYTHON" -B tools/sandbox.py doctor --python "$SCHEMA_PYTHON" \
  --pg-bin "$SCHEMA_PG_BIN" --output-parent "$SCHEMA_PARENT"
if [ ! -e "$SCHEMA_ENV" ] && [ ! -L "$SCHEMA_ENV" ]; then
  "$SCHEMA_PYTHON" -B tools/sandbox.py prepare --python "$SCHEMA_PYTHON" \
    --pg-bin "$SCHEMA_PG_BIN" --work-dir "$SCHEMA_ENV"
fi
# A failed or changed environment is refused by run; never silently rebuild it.
if SCHEMA_RESULT="$("$SCHEMA_PYTHON" -B tools/sandbox.py run \
  --environment "$SCHEMA_ENV" --output-parent "$SCHEMA_PARENT")"; then
  :
else
  SCHEMA_EXIT="$?"
  printf '%s\n' "$SCHEMA_RESULT"
  exit "$SCHEMA_EXIT"
fi
printf '%s\n' "$SCHEMA_RESULT"
SCHEMA_RUN="$(printf '%s\n' "$SCHEMA_RESULT" | "$SCHEMA_PYTHON" -B -c \
  'import json,sys; print(json.load(sys.stdin)["run"])')"
"$SCHEMA_PYTHON" -B tools/report.py --run "$SCHEMA_RUN"
