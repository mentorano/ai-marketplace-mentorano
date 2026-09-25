#!/usr/bin/env bash
# Run every test suite in this marketplace.
#
# BB_COLLECT=<path> runs the branch-board suite against another copy of the
# collector. That is how those tests were shown to be red before the fixes landed.
set -euo pipefail
cd "$(dirname "$0")"
python3 tests/test_collect.py "$@"
python3 tests/test_pipeline.py "$@"
python3 tests/test_measure.py "$@"
python3 tests/test_boundaries.py "$@"
python3 tests/test_revisions.py "$@"
python3 tests/test_skills.py "$@"
python3 tests/test_bg_claude_rc.py "$@"
