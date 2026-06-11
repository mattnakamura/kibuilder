#!/usr/bin/env bash
# Build (if needed) and run the kibuilder container, mounting a project dir.
#
# Usage:
#   scripts/docker-run.sh                       # mount ./examples/openpauw
#   scripts/docker-run.sh /path/to/project      # mount that dir as /work
#
# Then point a browser at:
#   http://localhost:6080/vnc.html?autoconnect=true&resize=remote

set -euo pipefail

cd "$(dirname "$0")/.."

PROJECT_DIR="${1:-$PWD/examples/openpauw}"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"   # absolutize

if ! docker image inspect kibuilder:latest >/dev/null 2>&1; then
    echo ">>> Building kibuilder image (this takes 5-10 min on a cold cache)"
    docker build -t kibuilder:latest .
fi

# Remove any leftover container with the same name from a prior crash / SIGKILL.
if docker ps -a --format '{{.Names}}' | grep -qx kibuilder; then
    echo ">>> Removing leftover 'kibuilder' container from a previous run"
    docker rm -f kibuilder >/dev/null
fi

echo ">>> Mounting $PROJECT_DIR as /work in the container"
echo ">>> Browser:  http://localhost:6901/"
echo ">>> (Ctrl-C here to stop the container)"
echo

exec docker run --rm \
    -p 6901:6901 \
    -v "$PROJECT_DIR:/work:rw" \
    -e KIBUILDER_GEOM=1600x1000 \
    --name kibuilder \
    kibuilder:latest
