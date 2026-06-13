#!/usr/bin/env bash
# Local dependency security scan for Python and frontend packages.
set -euo pipefail

REPORT_ONLY=false
if [[ "${1:-}" == "--report-only" ]]; then
    REPORT_ONLY=true
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
FAILED=0

run_check() {
    local name="$1"
    shift
    echo "=== ${name} ==="
    if ! "$@"; then
        FAILED=1
        if [[ "$REPORT_ONLY" != true ]]; then
            return 1
        fi
    fi
    return 0
}

cd "$ROOT_DIR"

if ! command -v pip-audit &>/dev/null; then
    python -m pip install pip-audit==2.7.3 -q
fi
run_check "Python dependency audit" pip-audit -r requirements.txt || true

echo ""
if [[ -d "$ROOT_DIR/frontend" ]]; then
    cd "$ROOT_DIR/frontend"
    run_check "Frontend dependency audit" npm audit --audit-level=moderate || true
else
    echo "frontend/ directory not found, skipping"
fi

echo ""
if [[ "$FAILED" -ne 0 ]]; then
    echo "Scan complete with findings."
    if [[ "$REPORT_ONLY" != true ]]; then
        exit 1
    fi
else
    echo "Scan complete with no blocking findings."
fi
