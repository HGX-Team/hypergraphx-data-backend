#!/usr/bin/env bash
# Upload the local dataset directory to the download server without ever
# modifying or deleting a published version folder (<name>/<MAJOR.MINOR.PATCH>/).
#
#   REMOTE_HOST=user@cricca.disi.unitn.it scripts/upload_datasets.sh [--dry-run]
#
# Steps:
#   1. Verify local files against the checksums recorded in the configs
#      (scripts/release_dataset.py check); abort on any mismatch.
#   2. Add new files, never overwriting existing ones (new version folders).
#   3. Sync everything except version folders, deleting stale files, so the
#      latest alias files are updated while version folders stay untouched.
#
# Environment:
#   REMOTE_HOST      ssh destination, e.g. user@cricca.disi.unitn.it
#   REMOTE_DIR       directory served at the dataset base URL
#                    (default: /mnt/data/hypergraphx-data)
#   LOCAL_DATA_DIR   local dataset directory (default: data/)
#   CONFIG_DIR       dataset configs with recorded checksums
#                    (default: resources/datasets_config/)
#   UPLOAD_DEST      full rsync destination instead of REMOTE_HOST:REMOTE_DIR
#                    (e.g. a local path for testing); skips the remote chmod
#   SKIP_CHECK=1     skip step 1
#   SKIP_REMOTE_CHMOD=1  skip normalizing permissions on the server
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DATA_DIR="${LOCAL_DATA_DIR:-$REPO_ROOT/data}"
CONFIG_DIR="${CONFIG_DIR:-$REPO_ROOT/resources/datasets_config}"
REMOTE_DIR="${REMOTE_DIR:-/mnt/data/hypergraphx-data}"
VERSION_DIRS='/*/[0-9]*.[0-9]*.[0-9]*/'

DRY_RUN=()
case "${1:-}" in
  --dry-run|-n) DRY_RUN=(--dry-run) ;;
  "") ;;
  *) echo "Usage: $0 [--dry-run]" >&2; exit 2 ;;
esac

if [[ -n "${UPLOAD_DEST:-}" ]]; then
  DEST="$UPLOAD_DEST"
  REMOTE_HOST=""
elif [[ -n "${REMOTE_HOST:-}" ]]; then
  DEST="$REMOTE_HOST:$REMOTE_DIR"
else
  echo "Set REMOTE_HOST (e.g. user@cricca.disi.unitn.it) or UPLOAD_DEST." >&2
  exit 2
fi

LOCAL_DATA_DIR="$(cd "$LOCAL_DATA_DIR" && pwd -P)"

if [[ "${SKIP_CHECK:-0}" != "1" ]]; then
  echo "== Verifying local files against recorded checksums"
  python3 "$REPO_ROOT/scripts/release_dataset.py" --config-dir "$CONFIG_DIR" --data-dir "$LOCAL_DATA_DIR" check
fi

RSYNC_OPTS=(-a --perms --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r --itemize-changes ${DRY_RUN[@]+"${DRY_RUN[@]}"})

echo "== Adding new files (existing files on the server are never overwritten)"
rsync "${RSYNC_OPTS[@]}" --ignore-existing "$LOCAL_DATA_DIR"/ "$DEST"/

echo "== Updating latest files (version folders excluded: never modified or deleted)"
rsync "${RSYNC_OPTS[@]}" --delete --exclude="$VERSION_DIRS" "$LOCAL_DATA_DIR"/ "$DEST"/

if [[ -n "$REMOTE_HOST" && "${SKIP_REMOTE_CHMOD:-0}" != "1" && ${#DRY_RUN[@]} -eq 0 ]]; then
  REMOTE_DIR_Q="$(printf '%q' "$REMOTE_DIR")"
  ssh "$REMOTE_HOST" \
    "find $REMOTE_DIR_Q -type d -exec chmod 755 {} + && find $REMOTE_DIR_Q -type f -exec chmod 644 {} +"
fi

echo "Done. To verify the server copies: python3 scripts/release_dataset.py check --remote"
