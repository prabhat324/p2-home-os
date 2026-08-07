#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_DIR="$SCRIPT_DIR/modules"

echo "========================================="
echo " P² Compute OS Bootstrap"
echo "========================================="

for module in "$MODULE_DIR"/*.sh; do
    echo
    echo "Running $(basename "$module")"
    bash "$module"
done

echo
echo "P² Compute OS bootstrap completed."
