#!/usr/bin/env bash
# The sync moved to .sdlc/scripts/sync-sdlc.sh in v0.11 (#133). A repo on an older version
# runs its own copy, which looks for the new one here, so this forwards to it. It isn't
# synced to consumers.
exec bash "$(dirname "$0")/../.sdlc/scripts/sync-sdlc.sh" "$@"
