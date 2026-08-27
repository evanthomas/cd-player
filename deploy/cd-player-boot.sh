#!/usr/bin/env bash
# ExecStartPre for cd-player.service (invoked as `ExecStartPre=-...`, so a
# nonzero exit here is logged but never blocks the unit from starting -- an
# appliance must still come up and play a physical CD even if this step
# fails outright, e.g. no network at all).
#
# network-online.target (the unit's own After=/Wants=) only means the
# network stack is up, not that any specific remote is actually reachable
# yet (WiFi association/DHCP can still be settling) -- so this retries the
# fetch itself, bounded, rather than assuming one attempt will succeed.
# Never touches uncommitted local changes or a diverged branch.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${CD_PLAYER_GIT_REMOTE:-origin}"
TIMEOUT_SECONDS="${CD_PLAYER_UPDATE_TIMEOUT_SECONDS:-120}"
RETRY_INTERVAL_SECONDS=5

# BatchMode=yes: fail fast instead of hanging on a passphrase/host-key
# prompt, since a boot-time service has no TTY to answer one.
export GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10"

cd "$REPO_DIR" || exit 1

echo "cd-player-boot: waiting up to ${TIMEOUT_SECONDS}s for '$REMOTE' to be reachable"
elapsed=0
until git fetch --quiet "$REMOTE"; do
    elapsed=$((elapsed + RETRY_INTERVAL_SECONDS))
    if [ "$elapsed" -ge "$TIMEOUT_SECONDS" ]; then
        echo "cd-player-boot: '$REMOTE' unreachable after ${TIMEOUT_SECONDS}s -- starting with the code already on disk" >&2
        exit 1
    fi
    sleep "$RETRY_INTERVAL_SECONDS"
done

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "cd-player-boot: uncommitted local changes present -- not updating, to avoid clobbering them" >&2
    exit 0
fi

branch="$(git rev-parse --abbrev-ref HEAD)"
if git merge --ff-only "$REMOTE/$branch"; then
    echo "cd-player-boot: up to date at $(git rev-parse --short HEAD)"
else
    echo "cd-player-boot: local branch has diverged from $REMOTE/$branch -- leaving code as-is" >&2
    exit 1
fi
