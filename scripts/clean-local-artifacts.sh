#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEEP_CLEAN=0
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --deep)
      DEEP_CLEAN=1
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: scripts/clean-local-artifacts.sh [--dry-run] [--deep]" >&2
      exit 1
      ;;
  esac
done

remove_path() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    return
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] remove $path"
    return
  fi
  rm -rf "$path"
  echo "[clean] removed $path"
}

while IFS= read -r path; do
  remove_path "$path"
done < <(
  find . \
    \( -path "./.git" -o -path "./.venv" -o -path "./outputs" -o -path "./workspace" \) -prune \
    -o -name ".DS_Store" -print
)

while IFS= read -r path; do
  remove_path "$path"
done < <(
  find . \
    \( -path "./.git" -o -path "./.venv" -o -path "./outputs" -o -path "./workspace" \) -prune \
    -o -type d -name "__pycache__" -print
)

while IFS= read -r path; do
  remove_path "$path"
done < <(find tests -maxdepth 1 -type d -name ".tmp*" -print 2>/dev/null || true)

for path in .pytest_cache .ruff_cache .mypy_cache .uv-cache htmlcov .coverage coverage.xml; do
  remove_path "$path"
done

if [[ "$DEEP_CLEAN" -eq 1 ]]; then
  for path in outputs workspace .venv; do
    remove_path "$path"
  done
fi

echo "[clean] done"
