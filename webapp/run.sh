#!/usr/bin/env bash
#
# One-command local launcher for the Entity Map web app + Services Dashboard.
# Creates a virtualenv, installs dependencies, loads optional .env, and starts
# the Flask server. Safe to re-run.
#
#   ./run.sh                # http://127.0.0.1:8888  (map) and /dashboard
#
# Configuration is read from the environment or a local .env file (see
# .env.example). Nothing cloud-related is required for the map + dashboard;
# the sample datasets are bundled.
set -euo pipefail

cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

if [ ! -d .venv ]; then
  echo "Creating virtualenv (.venv)..."
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

# Load .env (KEY=VALUE lines) if present.
if [ -f .env ]; then
  echo "Loading .env"
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-8888}"

echo ""
echo "  Entity Map:  http://${HOST}:${PORT}/"
echo "  Dashboard:   http://${HOST}:${PORT}/dashboard"
echo ""
exec python app.py
