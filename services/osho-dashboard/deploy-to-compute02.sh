#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-compute-02}"
REMOTE_DIR="${OSHO_DASHBOARD_REMOTE_DIR:-/srv/compose/osho-dashboard}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$REMOTE_DIR/backups/$STAMP"

printf 'Deploying Project Osho Dashboard v0.4 to %s:%s\n' "$TARGET" "$REMOTE_DIR"

ssh "$TARGET" "mkdir -p '$REMOTE_DIR/app/static' '$REMOTE_DIR/data' '$BACKUP_DIR'"

# Preserve the currently deployed source/config before replacement. Runtime DB remains in ./data.
ssh "$TARGET" "
    set -e
    REMOTE_DIR='$REMOTE_DIR'
    BACKUP_DIR='$BACKUP_DIR'
    cd \"\$REMOTE_DIR\"
    for item in Dockerfile requirements.txt compose.yml app/main.py app/static/index.html; do
        if [ -f \"\$item\" ]; then
            mkdir -p \"\$BACKUP_DIR/\$(dirname \"\$item\")\"
            cp -a \"\$item\" \"\$BACKUP_DIR/\$item\"
        fi
    done
"

# Application/build files are updated from Git.
rsync -av \
    "$SCRIPT_DIR/Dockerfile" \
    "$SCRIPT_DIR/requirements.txt" \
    "$TARGET:$REMOTE_DIR/"

rsync -av \
    "$SCRIPT_DIR/app/main.py" \
    "$TARGET:$REMOTE_DIR/app/main.py"

rsync -av \
    "$SCRIPT_DIR/app/static/index.html" \
    "$TARGET:$REMOTE_DIR/app/static/index.html"

# Preserve an existing live compose.yml because it may contain host-specific settings.
# Install the repository baseline only when no compose file exists remotely.
if ! ssh "$TARGET" "test -f '$REMOTE_DIR/compose.yml'"; then
    rsync -av "$SCRIPT_DIR/compose.yml" "$TARGET:$REMOTE_DIR/compose.yml"
    echo "Installed repository baseline compose.yml"
else
    echo "Preserved existing compute-02 compose.yml"
fi

ssh "$TARGET" "
    set -e
    cd '$REMOTE_DIR'
    docker compose config >/dev/null
    docker compose up -d --build
    sleep 3
    curl -fsS http://127.0.0.1:8787/health | python3 -m json.tool
    echo
    curl -fsS http://127.0.0.1:8787/api/dashboard | python3 -m json.tool | head -120
"

echo
echo "Dashboard deployment complete. Existing database preserved at $REMOTE_DIR/data/osho.db"
echo "Previous source/config backup: $BACKUP_DIR"
