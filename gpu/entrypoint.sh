#!/bin/sh
# Seed the writable caches in the /cache volume, then run the worker.
set -e
mkdir -p "$HF_HOME" "$TRITON_CACHE_DIR" "$(dirname "$FLEX_GEMM_AUTOTUNE_CACHE_PATH")"
[ -f "$FLEX_GEMM_AUTOTUNE_CACHE_PATH" ] || cp /venv/flex_gemm_autotune_cache.json "$FLEX_GEMM_AUTOTUNE_CACHE_PATH"
exec "$@"
