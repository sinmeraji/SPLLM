#!/usr/bin/env bash
set -euo pipefail
pkill -9 -f 'uvicorn .*backend.app.main:app' || true
echo "Stopped backend (if running)."


