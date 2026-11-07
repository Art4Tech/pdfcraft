#!/bin/sh
# Run on the Unraid host, using its Docker engine and host Tailscale plugin.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_ROOT=${1:-/mnt/user/appdata/craft-web}
PYTHON_IMAGE=python@sha256:e064671ca452259bab50e8e2c7bd896e39e9a343bb06ca25234adf6fe18d0fc7
case "$DEPLOY_ROOT" in /*) ;; *) echo 'Use an absolute deployment directory.' >&2; exit 1;; esac
command -v docker >/dev/null || { echo 'Enable Docker in Unraid first.' >&2; exit 1; }
command -v tailscale >/dev/null || { echo 'Install and connect the host Tailscale plugin first.' >&2; exit 1; }
docker compose version >/dev/null || { echo 'Install Docker Compose v2 (for example, Compose Manager Plus) first.' >&2; exit 1; }
[ "$(docker version --format '{{.Server.Os}}')" = linux ] || { echo 'A Linux Docker engine is required.' >&2; exit 1; }
case "${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}" in
    unix://*) ;; *) echo 'Use the local Unraid Docker engine.' >&2; exit 1;;
esac
[ -S /var/run/docker.sock ] || { echo 'The local Docker socket is missing.' >&2; exit 1; }
SOCKET_GID=$(stat -c '%g' /var/run/docker.sock)
HOST_NAME=$(hostname)
mkdir -p "$DEPLOY_ROOT"
helper() {
    docker run --rm --mount "type=bind,source=$SCRIPT_DIR,target=/installer,readonly" \
        --mount "type=bind,source=$DEPLOY_ROOT,target=/deploy" \
        "$PYTHON_IMAGE" python /installer/unraid.py "$@"
}
# Verify the local dashboard bundle before changing any app or Tailscale endpoint.
helper verify
APP_SPECS=$(helper specs)
ALL_ENDPOINTS=$(helper endpoints)
DNS_NAME=$(tailscale status --json | docker run --rm -i "$PYTHON_IMAGE" python -c '
import json,sys
s=json.load(sys.stdin)
if s.get("BackendState") != "Running": raise SystemExit("Connect the host Tailscale plugin first.")
dns=s.get("Self",{}).get("DNSName", "").rstrip(".")
if not dns: raise SystemExit("Enable MagicDNS and HTTPS for the host Tailscale node.")
print(dns)
')
check_endpoint() {
    tailscale serve status --json | docker run --rm -i \
        --mount "type=bind,source=$SCRIPT_DIR,target=/installer,readonly" \
        "$PYTHON_IMAGE" python -c '
import json,sys
sys.path.insert(0,"/installer")
from install import validate_endpoint
validate_endpoint(json.load(sys.stdin),sys.argv[1],int(sys.argv[2]),sys.argv[3])
' "$DNS_NAME" "$1" "http://127.0.0.1:$2"
}
for spec in $ALL_ENDPOINTS; do
    app=${spec%%:*}; rest=${spec#*:}; https=${rest%%:*}; local=${rest#*:}
    check_endpoint "$https" "$local"
    expected="$app-tailnet-web-1"
    [ "$app" != dashboard ] || expected=artcraft-dashboard-studio-1
    occupants=$(docker ps --filter "publish=$local" --format '{{.Names}}')
    if [ -n "$occupants" ] && [ "$occupants" != "$expected" ]; then
        echo "Local port $local belongs to another container: $occupants. No apps were changed." >&2
        exit 1
    fi
done
if [ ! -e "$DEPLOY_ROOT/tailscale-serve-before.json" ]; then
    tailscale serve status --json > "$DEPLOY_ROOT/tailscale-serve-before.json"
fi
# Prepare dashboard configuration before downloading or starting the editors.
helper prepare --root /deploy/dashboard --dns "$DNS_NAME" --host "$HOST_NAME" --socket-gid "$SOCKET_GID"
for spec in $APP_SPECS; do
    app=${spec%%:*}; rest=${spec#*:}; https=${rest%%:*}; local=${rest#*:}
    docker run --rm --mount "type=bind,source=$SCRIPT_DIR,target=/installer,readonly" \
        --mount "type=bind,source=$DEPLOY_ROOT,target=/deploy" "$PYTHON_IMAGE" \
        python /installer/install.py --prepare-only --app "$app" \
        --install-dir "/deploy/$app" --local-port "$local" --project-name "$app-tailnet"
    compose="$DEPLOY_ROOT/$app/compose.json"
    docker compose -f "$compose" build
    docker compose -f "$compose" run --rm --no-deps web -t
    docker compose -f "$compose" up -d --wait
    check_endpoint "$https" "$local"
    tailscale serve --bg --yes --https="$https" "http://127.0.0.1:$local"
done
DASHBOARD_COMPOSE="$DEPLOY_ROOT/dashboard/compose.yaml"
docker compose --env-file "$DEPLOY_ROOT/dashboard/.env" -f "$DASHBOARD_COMPOSE" build studio
docker compose --env-file "$DEPLOY_ROOT/dashboard/.env" -f "$DASHBOARD_COMPOSE" up -d --pull never --wait
check_endpoint 7443 18760
tailscale serve --bg --yes --https=7443 http://127.0.0.1:18760
{
    echo "Artcraft dashboard: https://$DNS_NAME:7443/"
    for spec in $APP_SPECS; do
        app=${spec%%:*}; rest=${spec#*:}; https=${rest%%:*}
        echo "$app: https://$DNS_NAME:$https/"
    done
} > "$DEPLOY_ROOT/app-urls.txt"
cat "$DEPLOY_ROOT/app-urls.txt"
echo 'Bookmark the dashboard in each Windows VM. Keep Docker and the host Tailscale plugin running.'
echo 'The dashboard source bundle is local; this host now runs independently.'
