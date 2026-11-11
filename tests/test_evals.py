"""The eval suite's scaffolds (evals/, run by `claude plugin eval`): each builds its fixture without a model."""
import json, os, re, subprocess, sys, tempfile, unittest
from pathlib import Path

from helpers import REPO

EVALS = REPO / "evals"
CASES = sorted(p.parent for p in EVALS.glob("*/case.yaml"))
NEXT = {"review": "review"}  # the step each scaffold leaves the run at; the rest stop at implement


class EvalScaffoldTests(unittest.TestCase):
    def test_there_are_cases(self):
        self.assertGreaterEqual(len(CASES), 5)

    def test_each_scaffold_builds_its_fixture(self):
        for case in CASES:
            with self.subTest(case.name), tempfile.TemporaryDirectory() as home:
                cwd = Path(home) / "cwd"
                cwd.mkdir()
                env = {"PATH": os.environ["PATH"], "HOME": home}
                r = subprocess.run(["bash", str(case / "fixture.sh")], cwd=cwd, env=env, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                run = cwd / ".sstack" / "runs" / "subtract-1"
                st = json.loads((run / "workflow.json").read_text())
                step = next((v for k, v in NEXT.items() if k in case.name), "implement")
                self.assertEqual(st["current"], step)
                self.assertNotIn("no dispatch", (run / "progress.md").read_text())  # it would teach the shortcut
                if "worktree" in case.name:
                    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=cwd, env=env,
                                            capture_output=True, text=True).stdout.strip()
                    self.assertNotEqual(common, ".git")

    def test_each_case_has_graders_and_a_quoted_description(self):
        for case in CASES:
            with self.subTest(case.name):
                self.assertTrue(list((case / "graders").glob("*.md")))
                self.assertRegex((case / "prompt.md").read_text(), re.compile(r'^description: ".*"$', re.M))


TRACES = EVALS / "_fixture" / "traces"


def _value(v: str):
    v = v.strip()
    if v.startswith("{"):  # tool_order's {tool: Bash, input_match: '...'}
        tool, _, rest = v[1:-1].partition(",")
        return {"tool": tool.split(":", 1)[1].strip(), "input_match": _value(rest.split(":", 1)[1])}
    return v[1:-1] if v[:1] == "'" == v[-1:] else v


def grader(path: Path) -> dict:
    """One graders/*.md frontmatter: flat `key: value` lines (what these cases use)."""
    fm = path.read_text().split("---")[1]
    return {k.strip(): _value(v) for k, v in (l.split(":", 1) for l in fm.strip().splitlines())}


def replay(g: dict, calls: list[dict]) -> bool | None:
    """The grader's verdict on a recorded run: `claude plugin eval` semantics for tool_used and
    tool_order (a regex over the JSON-encoded input). None: needs the run's workspace."""
    def hits(spec):
        spec = spec if isinstance(spec, dict) else {"tool": spec}
        rx = re.compile(spec.get("input_match") or "")
        return [i for i, c in enumerate(calls) if c["name"] == spec["tool"] and rx.search(json.dumps(c["input"]))]
    if g["type"] == "tool_used":
        n = len(hits(g))
        return int(g.get("min", 1)) <= n and (g.get("max") is None or n <= int(g["max"]))
    if g["type"] == "tool_order":
        b, a = hits(g["before"]), hits(g["after"])
        return bool(b and a and b[0] < a[0])
    return None


class GraderReplayTests(unittest.TestCase):
    """Static evals: the graders re-scored against recorded real runs, no model. A run that followed
    the workflow passes every grader; the run that skipped with --no-dispatch fails the right ones."""

    def verdicts(self, case: str, trace: str) -> dict:
        calls = [json.loads(l) for l in (TRACES / trace).read_text().splitlines() if l]
        return {p.stem: replay(grader(p), calls) for p in sorted((EVALS / case / "graders").glob("*.md"))}

    def test_every_case_has_a_passing_trace(self):
        self.assertEqual(sorted(p.name.split(".")[0] for p in TRACES.glob("*.pass.jsonl")), [c.name for c in CASES])

    def test_a_run_that_followed_the_workflow_passes_every_grader(self):
        for case in CASES:
            with self.subTest(case.name):
                v = self.verdicts(case.name, f"{case.name}.pass.jsonl")
                self.assertEqual([k for k, ok in v.items() if ok is False], [], v)

    def test_the_run_that_skipped_the_dispatch_fails(self):
        v = self.verdicts("implement-shell-pi", "implement-shell-pi.skip.jsonl")
        self.assertEqual(sorted(k for k, ok in v.items() if ok is False),
                         ["dispatched", "no-skip", "recorded", "shell-child"])


if __name__ == "__main__":
    unittest.main()
