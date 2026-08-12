#!/usr/bin/env bash
# Run everything. No pytest dependency -- each file is executable on its own so
# the benchmark stays runnable by a reviewer with a bare Python install.
set -uo pipefail
cd "$(dirname "$0")/.."

total=0
failed=0
for f in tests/test_*.py; do
  echo "=== $f"
  if out=$(python3 "$f" 2>&1); then
    echo "$out" | tail -1
  else
    failed=$((failed + 1))
    echo "$out"
  fi
  n=$(echo "$out" | grep -c '^  PASS' || true)
  total=$((total + n))
done

echo "=== scripts/e2e.py (pipeline check on reference specs)"
if e2e=$(python3 scripts/e2e.py 2>&1); then
  echo "$e2e" | tail -2
else
  failed=$((failed + 1)); echo "$e2e"
fi

echo
echo "-------------------------------------------"
if [ "$failed" -eq 0 ]; then
  echo "all suites green — $total assertions passed"
else
  echo "$failed suite(s) FAILED"
fi
exit "$failed"
