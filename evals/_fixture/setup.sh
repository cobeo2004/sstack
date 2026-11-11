#!/bin/bash
# Shared scaffold: a synced sstack profile in the eval's temp HOME, a tiny repo in the cwd, and a
# work run already past the plan gate. Usage: setup.sh <plain|worktree> <claude|pi> <step>
#   plain|worktree  the cwd is a normal checkout, or a linked worktree of $HOME/main
#   claude|pi       the harness `implement` routes to (claude → Agent tool, pi → background Bash)
#   step            the run's next step: implement | review | inline (implement with max_agents = 0)
set -euo pipefail
layout=$1 harness=$2 step=$3
SSTACK=$(cd "$(dirname "$0")/../.." && pwd)
# The eval sandbox can't read a Python under /Users (e.g. miniconda): put a 3.11+ one from elsewhere
# first on PATH. The Bash tool sources these rc files from the temp HOME.
py=$(for c in $(which -a python3.13 python3.12 python3.11 python3 2>/dev/null); do
  [[ $c == /Users/* ]] && continue
  "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null && { echo "$c"; break; }; done)
mkdir -p "$HOME/bin" && ln -sf "${py:?no python3 >= 3.11 outside /Users}" "$HOME/bin/python3"
for rc in .zshrc .bashrc .zshenv .profile; do echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/$rc"; done
export PATH="$HOME/bin:$PATH"
git config --global user.name eval && git config --global user.email eval@example.invalid
git config --global init.defaultBranch main

"$SSTACK/bin/sstack-config" sync >/dev/null
if [ "$harness" = claude ]; then
  printf 'harness = "claude"\nmodel = "haiku"\n' > "$HOME/.sstack/roles/implement.toml"
fi
printf 'harness = "claude"\nmodel = "haiku"\n' > "$HOME/.sstack/roles/investigate.toml"
# sonnet, not haiku: review_not_implementer drops a reviewer equal to implement
printf 'mode = "single"\npanel = [{ harness = "claude", model = "sonnet" }]\n' > "$HOME/.sstack/roles/review.toml"

repo() {  # $1: dir to init
  git -C "$1" init -q
  mkdir -p "$1/.sstack"
  printf 'def add(a, b):\n    return a + b\n' > "$1/calc.py"
  printf 'import unittest\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n' > "$1/test_calc.py"
  printf '# calc\nA one-file Python calculator. Verify: `python3 -m unittest`.\n' > "$1/.sstack/product.md"
  printf '.sstack/runs/\n' > "$1/.gitignore"
  git -C "$1" add -A && git -C "$1" commit -qm init
}
if [ "$layout" = worktree ]; then
  mkdir -p "$HOME/main" && repo "$HOME/main"
  git -C "$HOME/main" worktree add -q "$PWD" -b feature/subtract
else
  repo "$PWD"
fi
echo "$PWD" >> "$HOME/.sstack/repos.txt"

if [ "$step" = inline ]; then
  mkdir -p .sstack/steps/implement && printf 'max_agents = 0\n' > .sstack/steps/implement/step.toml
fi

R=.sstack/runs/subtract-1
mkdir -p "$R"
cat > "$R/plan.md" <<'PLAN'
# plan: add subtract
R1: `calc.subtract(a, b)` returns a - b.
R2: `test_calc.py` has a test for subtract; `python3 -m unittest` passes.
Steps: 1. add subtract to calc.py (R1). 2. add its test (R2).
PLAN
printf '# recon\ncalc.py has add(); no subtract.\n' > "$R/recon.md"
W="$SSTACK/bin/sstack-workflow"
"$W" done recon --run "$PWD/$R" --no-dispatch "eval fixture" >/dev/null
"$W" done plan --run "$PWD/$R" --no-dispatch "eval fixture" >/dev/null
# what a real run leaves: the fixture's --no-dispatch lines would teach the agent that shortcut
printf -- '- recon: investigate dispatched, recon.md written\n- plan: plan.md approved at the plan gate; the user said yes, go ahead with implement\n' > "$R/progress.md"
if [ "$step" = review ]; then
  printf 'def add(a, b):\n    return a + b\n\n\ndef subtract(a, b):\n    return a - b\n' > calc.py
  "$W" done implement --run "$PWD/$R" --no-dispatch "eval fixture" >/dev/null
  "$W" run gate --run "$PWD/$R" >/dev/null || true
  sed -i.bak '/no dispatch/d' "$R/progress.md" && rm "$R/progress.md.bak"
  printf -- '- implement: done (subtract added)\n- gate: done\n' >> "$R/progress.md"
fi
