#!/bin/sh
set -eu

: "${DOCKER_ARGS_FILE:?DOCKER_ARGS_FILE is required}"
printf '%s\n' "$@" > "$DOCKER_ARGS_FILE"
