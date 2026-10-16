#!/usr/bin/env bash

set -euo pipefail

case "${1:-}" in
    -i|-v|"") ;;
    *)
        echo "Usage: $0 [-i|-v]" >&2
        exit 1
        ;;
esac

POSTGRES_VOLUME="$PWD/volumes/postgres"
mkdir -p "$POSTGRES_VOLUME"

export POSTGRES_VOLUME

docker compose --env-file .env down --volumes

# `up --wait` does not handle the one-shot migration service (it waits on the exited
# container), so start detached and wait for the migration to finish explicitly.
up_detached() {
    docker compose --env-file .env up \
        --build \
        --remove-orphans \
        -d

    MIGRATION_EXIT_CODE=$(docker wait "$(docker compose --env-file .env ps -aq migration)")
    if [ "$MIGRATION_EXIT_CODE" != "0" ]; then
        docker compose --env-file .env logs migration >&2
        echo "Migration failed with exit code $MIGRATION_EXIT_CODE" >&2
        exit 1
    fi
}

case "${1:-}" in
    -i)
        docker compose --env-file .env up \
            --build \
            --remove-orphans
        ;;
    -v)
        up_detached
        docker compose --env-file .env logs -f
        ;;
    "")
        up_detached
        ;;
esac
