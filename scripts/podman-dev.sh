#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$root"

if ! command -v podman >/dev/null || ! provider="$(command -v podman-compose)"; then
    printf '%s\n' "Install Podman and podman-compose in WSL first." >&2
    exit 1
fi
export PODMAN_COMPOSE_PROVIDER="$provider"

compose() {
    podman compose --file compose.yml "$@"
}

validate_config() {
    "$provider" --file compose.yml config >/dev/null
}

wait_for_stores() {
    local attempt
    for ((attempt = 0; attempt < 60; attempt++)); do
        if compose exec -T postgres pg_isready -h 127.0.0.1 -U donke -d donke >/dev/null 2>&1 &&
           compose exec -T redis redis-cli ping >/dev/null 2>&1; then
            return
        fi
        sleep 1
    done
    printf '%s\n' "PostgreSQL or Redis did not become ready. See scripts/podman-dev.sh logs." >&2
    exit 1
}

case "${1:-up}" in
    up)
        validate_config
        podman build --file Containerfile --tag localhost/donke-backend:dev .
        compose up -d postgres redis
        wait_for_stores
        compose run --rm migrate
        compose up -d app matchmaking jobs scheduler voice
        ;;
    smoke)
        sessions_dir="$(mktemp -d)"
        trap 'rm -f -- "$sessions_dir/demo-sessions.json"; rmdir -- "$sessions_dir"' EXIT
        umask 077
        compose exec -T app sh -eu -c '
            sessions_dir="$(mktemp -d)"
            trap '"'"'rm -f -- "$sessions_dir/demo-sessions.json"; rmdir -- "$sessions_dir"'"'"' EXIT
            python -m scripts.seed_demo --sessions "$sessions_dir/demo-sessions.json" >&2
            cat -- "$sessions_dir/demo-sessions.json"
        ' > "$sessions_dir/demo-sessions.json"
        uv run --locked python -m scripts.demo_smoke --sessions "$sessions_dir/demo-sessions.json"
        ;;
    config)
        validate_config
        printf '%s\n' "Podman Compose configuration is valid."
        ;;
    down|ps|logs|exec)
        compose "$@"
        ;;
    *)
        printf '%s\n' "Usage: scripts/podman-dev.sh [up|smoke|down|ps|logs|exec|config]" >&2
        exit 2
        ;;
esac
