#!/bin/sh
set -eu

: "${DOCKER_ARGS_FILE:?DOCKER_ARGS_FILE is required}"
: "${DOCKER_METADATA_ARGS_FILE:?DOCKER_METADATA_ARGS_FILE is required}"

for argument in "$@"; do
    if [ "$argument" = "stat" ]; then
        printf '%s\n' "$@" > "$DOCKER_METADATA_ARGS_FILE"
        if [ "${STAT_EXIT_CODE:-0}" -ne 0 ]; then
            exit "$STAT_EXIT_CODE"
        fi
        printf '%s\n' "${STAT_GID-20}"
        exit 0
    fi
done

printf '%s\n' "$@" > "$DOCKER_ARGS_FILE"
