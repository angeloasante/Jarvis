#!/usr/bin/env bash
# Install git hooks that keep CHANGELOG.md updated automatically.
#
#   bash scripts/install-hooks.sh
#
# After this, every `git commit` regenerates the ## [Unreleased] section of
# CHANGELOG.md from your commit messages and stages it — you never hand-write
# the changelog again. To turn it off: rm .git/hooks/post-commit
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK="$REPO_ROOT/.git/hooks/post-commit"

cat > "$HOOK" <<'HOOK_EOF'
#!/usr/bin/env bash
# Auto-update CHANGELOG.md from commit messages, then stage it.
# Guard against recursion: skip if this commit only touched the changelog.
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Don't loop on changelog-only commits.
changed="$(git diff-tree --no-commit-id --name-only -r HEAD 2>/dev/null || true)"
if [ "$changed" = "CHANGELOG.md" ]; then
  exit 0
fi

PY="$(command -v python3 || command -v python || true)"
[ -z "$PY" ] && exit 0

"$PY" scripts/changelog.py >/dev/null 2>&1 || exit 0

# Stage the regenerated changelog so it rides along with your next commit.
git add CHANGELOG.md 2>/dev/null || true
HOOK_EOF

chmod +x "$HOOK"
echo "✓ Installed post-commit hook → CHANGELOG.md now auto-updates from commits."
echo "  Disable any time with: rm .git/hooks/post-commit"
