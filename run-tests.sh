#!/usr/bin/env bash
# Run every test suite in this marketplace.
#
# BB_COLLECT=<path> runs the branch-board suite against another copy of the
# collector. That is how those tests were shown to be red before the fixes landed.
set -euo pipefail
cd "$(dirname "$0")"

# The clean-code TypeScript tests measure through the repo's own typescript
# package (package.json). Install it once; without npm those tests skip.
if [ -f package.json ] && [ ! -d node_modules/typescript ] && command -v npm > /dev/null; then
  mkdir -p tmp/claude-logs
  npm_log="tmp/claude-logs/npm-ci-$(date +%Y%m%d-%H%M%S).log"
  echo "run-tests: installing test dependencies (npm ci), log: $npm_log"
  npm ci > "$npm_log" 2>&1 || echo "run-tests: npm ci failed, see $npm_log; the TypeScript tests will skip"
fi

python3 tests/test_collect.py "$@"
python3 tests/test_pipeline.py "$@"
python3 tests/test_measure.py "$@"
python3 tests/test_boundaries.py "$@"
python3 tests/test_revisions.py "$@"
python3 tests/test_skills.py "$@"
python3 tests/test_bg_claude_rc.py "$@"
