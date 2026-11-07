#!/bin/sh
# Run on the Unraid host. Uses its Docker engine and host Tailscale plugin.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_ROOT=${1:-/mnt/user/appdata/craft-web}
PYTHON_IMAGE=python@sha256:e064671ca452259bab50e8e2c7bd896e39e9a343bb06ca25234adf6fe18d0fc7
APP_SPECS="pdfcraft:8443:18765 cadcraft:10443:18767 photocraft:11443:18768 vectorcraft:12443:18769"
case "$DEPLOY_ROOT" in /*) ;; *) echo 'Use an absolute deployment directory.' >&2; exit 1;; esac
command -v docker >/dev/null || { echo 'Enable Docker in Unraid first.' >&2; exit 1; }
command -v tailscale >/dev/null || { echo 'Install and connect the host Tailscale plugin first.' >&2; exit 1; }
docker compose version >/dev/null || { echo 'Install Docker Compose v2 (for example, Compose Manager Plus) first.' >&2; exit 1; }
docker version --format '{{.Server.Version}}' >/dev/null
mkdir -p "$DEPLOY_ROOT"
DNS_NAME=$(tailscale status --json | docker run --rm -i "$PYTHON_IMAGE" python -c '
import json,sys
s=json.load(sys.stdin)
if s.get("BackendState") != "Running": raise SystemExit("Connect Tailscale first")
n=s.get("Self",{}).get("DNSName", "").rstrip(".")
if not n: raise SystemExit("Enable Tailscale MagicDNS and HTTPS first")
print(n)
')
check_endpoint() {
    tailscale serve status --json | docker run --rm -i \
        --mount "type=bind,src=$SCRIPT_DIR,dst=/installer,readonly" \
        "$PYTHON_IMAGE" python -c '
import json,sys
sys.path.insert(0,"/installer")
from install import validate_endpoint
validate_endpoint(json.load(sys.stdin),sys.argv[1],int(sys.argv[2]),sys.argv[3])
' "$DNS_NAME" "$1" "http://127.0.0.1:$2"
}
# Validate every requested endpoint before changing any running application.
for ENTRY in $APP_SPECS; do
    REST=${ENTRY#*:}
    check_endpoint "${REST%%:*}" "${REST#*:}"
done
if [ ! -e "$DEPLOY_ROOT/tailscale-serve-before.json" ]; then
    tailscale serve status --json > "$DEPLOY_ROOT/tailscale-serve-before.json"
fi
for ENTRY in $APP_SPECS; do
    APP=${ENTRY%%:*}
    REST=${ENTRY#*:}
    HTTPS_PORT=${REST%%:*}
    LOCAL_PORT=${REST#*:}
    printf '\nInstalling %s...\n' "$APP"
    docker run --rm \
        --mount "type=bind,src=$DEPLOY_ROOT,dst=/deploy" \
        --mount "type=bind,src=$SCRIPT_DIR,dst=/installer,readonly" \
        "$PYTHON_IMAGE" python /installer/install.py --prepare-only \
        --app "$APP" --install-dir "/deploy/$APP" --local-port "$LOCAL_PORT" --https-port "$HTTPS_PORT"
    COMPOSE_FILE="$DEPLOY_ROOT/$APP/compose.json"
    docker compose -f "$COMPOSE_FILE" build
    docker compose -f "$COMPOSE_FILE" run --rm --no-deps web -t
    docker compose -f "$COMPOSE_FILE" up -d --wait
    check_endpoint "$HTTPS_PORT" "$LOCAL_PORT"
    tailscale serve --bg --yes --https="$HTTPS_PORT" "http://127.0.0.1:$LOCAL_PORT"
    printf '\n%s: https://%s:%s/\n' "$APP" "$DNS_NAME" "$HTTPS_PORT"
done
printf '\nAll four apps are ready. Open these links from either Windows VM:\n'
: > "$DEPLOY_ROOT/app-urls.txt"
for ENTRY in $APP_SPECS; do
    APP=${ENTRY%%:*}
    REST=${ENTRY#*:}
    printf '%s: https://%s:%s/\n' "$APP" "$DNS_NAME" "${REST%%:*}" | tee -a "$DEPLOY_ROOT/app-urls.txt"
done
printf '\nSaved links: %s/app-urls.txt\n' "$DEPLOY_ROOT"
