#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PAGES_REPO_URL="${PAGES_REPO_URL:-git@github.com:HGX-Team/hypergraphx-data.git}"
PAGES_DIR="${PAGES_DIR:-"$REPO_ROOT/../hypergraphx-data"}"
COMMIT_MESSAGE="${COMMIT_MESSAGE:-Update site}"
PUSH=0
COMMIT=1
ALLOW_DIRTY=0

usage() {
  cat <<'EOF'
Usage: scripts/deploy_pages.sh [options]

Build the static site from this backend repository, copy the built files plus
reproducibility/ into the public GitHub Pages repository, then optionally push.

Options:
  --pages-dir PATH        Local checkout of HGX-Team/hypergraphx-data.
  --pages-repo URL        Git URL to clone if --pages-dir does not exist.
  --message TEXT          Commit message for the Pages repo.
  --no-commit             Copy files but do not commit.
  --push                  Push the Pages repo after committing.
  --allow-dirty           Allow deploying into a dirty Pages repo checkout.
  -h, --help              Show this help.

Environment overrides:
  PAGES_DIR, PAGES_REPO_URL, COMMIT_MESSAGE
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pages-dir)
      PAGES_DIR="$2"
      shift 2
      ;;
    --pages-repo)
      PAGES_REPO_URL="$2"
      shift 2
      ;;
    --message)
      COMMIT_MESSAGE="$2"
      shift 2
      ;;
    --no-commit)
      COMMIT=0
      shift
      ;;
    --push)
      PUSH=1
      shift
      ;;
    --allow-dirty)
      ALLOW_DIRTY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "$REPO_ROOT"

if [[ ! -d "$PAGES_DIR/.git" ]]; then
  mkdir -p "$(dirname "$PAGES_DIR")"
  git clone "$PAGES_REPO_URL" "$PAGES_DIR"
fi

if [[ "$ALLOW_DIRTY" -ne 1 ]] && [[ -n "$(git -C "$PAGES_DIR" status --porcelain)" ]]; then
  echo "Pages repo has uncommitted changes: $PAGES_DIR" >&2
  echo "Commit/stash them first, or rerun with --allow-dirty." >&2
  exit 1
fi

BUILD_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$BUILD_DIR"
}
trap cleanup EXIT

SITE_DIST_DIR="$BUILD_DIR" python3 scripts/build_site.py

rsync -a --delete --exclude '.git/' "$BUILD_DIR"/ "$PAGES_DIR"/
rsync -a --delete reproducibility/ "$PAGES_DIR/reproducibility"/

git -C "$PAGES_DIR" status --short

if [[ "$COMMIT" -eq 1 ]]; then
  git -C "$PAGES_DIR" add -A
  if git -C "$PAGES_DIR" diff --cached --quiet; then
    echo "No Pages changes to commit."
  else
    git -C "$PAGES_DIR" commit -m "$COMMIT_MESSAGE"
  fi
fi

if [[ "$PUSH" -eq 1 ]]; then
  git -C "$PAGES_DIR" push
fi

echo "Pages deployment prepared in: $PAGES_DIR"
