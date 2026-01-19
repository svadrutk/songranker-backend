#!/bin/bash
# Sync API Spec script

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BACKEND_DIR="$( cd "$DIR/.." && pwd )"
FRONTEND_DIR="$( cd "$BACKEND_DIR/../songranker-frontend" && pwd )"

echo "Syncing API spec..."

# Run the export script
"$BACKEND_DIR/.venv/bin/python3" "$BACKEND_DIR/scripts/export_openapi.py"

if [ $? -eq 0 ]; then
    echo "API spec synced to $FRONTEND_DIR/openapi.json"
else
    echo "Failed to sync API spec"
    exit 1
fi
