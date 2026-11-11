#!/bin/bash
# Run the eval suite against a clean copy of this checkout (tracked + new, non-ignored files only),
# so local state (.sstack/runs, .omc, results) never loads as part of the plugin. Each run's
# trace is copied to evals/results/<stamp>/traces/<case>-<arm>-<n>.jsonl.
# Usage: evals/run.sh [claude plugin eval options...]   e.g. evals/run.sh --case 'implement-*' --runs 3
set -euo pipefail
src=$(cd "$(dirname "$0")/.." && pwd)
out="$src/evals/results/$(date +%Y%m%d-%H%M%S)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
(cd "$src" && git ls-files -co --exclude-standard -z | grep -zv '^evals/results/' | xargs -0 tar cf -) | tar xf - -C "$tmp"
mkdir -p "$out/traces"
code=0
(cd "$tmp" && claude plugin eval . --scaffold --trust-plugin --ablation none --no-publish --keep-temp \
  --allow-tools Bash Write Edit --output-dir "$out" --json "$out/result.json" "$@" < /dev/null) || code=$?
python3 - "$out" <<'PY'
import json, os, shutil, subprocess, sys
out = sys.argv[1]
for c in json.load(open(f"{out}/result.json"))["cases"]:
    for arm, runs in c["arms"].items():
        for i, r in enumerate(runs):
            t = r.get("tracePath")
            if not t:
                continue
            kept = os.path.dirname(os.path.dirname(t))
            subprocess.run(["chmod", "-R", "u+rwx", kept], stderr=subprocess.DEVNULL)
            if os.path.exists(t):
                shutil.copy(t, f"{out}/traces/{c['name']}-{arm}-{i + 1}.jsonl")
            shutil.rmtree(kept, ignore_errors=True)
PY
echo "results: $out"
exit $code
