"""Answer key for the overnight skill (.sstack/runs/overnight-skill-*/decisions.md R3-R5):
`sstack-gate --merge` and the doctor's [overnight] check. Written before either exists."""
import json, os, subprocess, sys
from pathlib import Path

import test_doctor
from helpers import REPO, TempEnv

GATE = REPO / "bin" / "sstack-gate"
WORKFLOW = REPO / "bin" / "sstack-workflow"

GREEN = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"},
         {"__typename": "StatusContext", "state": "SUCCESS"}]
PR = {"isDraft": False, "mergeable": "MERGEABLE", "baseRefName": "main", "statusCheckRollup": GREEN,
      "additions": 10, "deletions": 2, "files": [{"path": "lib/a.py"}]}
POLICY = '[overnight]\nmerge = "policy"\n'


class MergeTests(TempEnv):
    """R5: MERGE only when every condition holds; each failing one is a HOLD with its reason."""

    def setUp(self):
        super().setUp()
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "user.email", "gate@example.invalid")
        self.git("config", "user.name", "Gate Test")
        self.bin = self.root.parent / "fakebin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text('#!/bin/sh\necho "$*" >> "$FAKE_GH_LOG"\ncat "$FAKE_GH_JSON"\n')
        gh.chmod(0o755)
        self.run = self.root.parent / "run"
        self.run.mkdir()

    def git(self, *args):
        r = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"git {' '.join(args)}: {r.stderr}")
        return r.stdout

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def base(self, files):
        """`main` with a passing verify and `files`, pushed to a bare origin; then branch `feature`."""
        self.write(self.root, ".sstack/project.toml", 'verify = "true"\n')
        for rel, text in files.items():
            self.write(self.root, rel, text)
        self.commit("base")
        origin = self.root.parent / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        self.git("remote", "add", "origin", str(origin))
        self.git("push", "-q", "-u", "origin", "main")
        self.git("remote", "set-head", "origin", "main")
        self.git("switch", "-q", "-c", "feature")
        self.write(self.home, ".sstack/repos.txt", f"{self.root}\n")

    def setup_branch(self, policy=POLICY, pr=None, score=9, review="pass", gate="GATE: PASS",
                     assumptions=None):
        files = {".sstack/config.toml": policy} if policy is not None else {}
        self.base(files)
        self.write(self.root, "lib/a.py", "x = 1\n")
        self.review(score, review)
        self.commit("feature")
        self.head = self.git("rev-parse", "HEAD").strip()
        if gate is not None:
            self.gate_verdict(gate)
        if assumptions is not None:
            self.write(self.run, "assumptions.md", assumptions)
        self.pr(**(pr or {}))

    def review(self, score=9, review="pass"):
        """Record the review the real way, on the uncommitted change, as `work` does."""
        found = [] if review == "pass" else [{"severity": "Important", "verified": True}]
        self.write(self.root.parent, "findings.json", json.dumps(
            [{"reviewer": "t/x", "score": score, "findings": found}]))
        subprocess.run([sys.executable, str(WORKFLOW), "done", "review", "--run", str(self.run),
                        "--findings", str(self.root.parent / "findings.json")],
                       cwd=self.root, capture_output=True, text=True)
        state = json.loads((self.run / "workflow.json").read_text())
        self.assertEqual(state["steps"]["review"]["status"], review)

    def gate_verdict(self, gate="GATE: PASS", n=1):
        self.head = self.git("rev-parse", "HEAD").strip()
        self.write(self.run, f"gate/{n}-pr.md", f"{gate}\n\n## Summary\n\n- Head: {self.head}\n")
        self.pr()

    def pr(self, **over):
        self.write(self.root.parent, "pr.json", json.dumps({**PR, "headRefOid": self.head, **over}))

    def merge(self, *extra):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                   FAKE_GH_JSON=str(self.root.parent / "pr.json"),
                   FAKE_GH_LOG=str(self.root.parent / "gh.log"))
        r = subprocess.run([sys.executable, str(GATE), "--merge", "7", "--run", str(self.run), *extra],
                           cwd=self.root, env=env, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def assertMerge(self):
        code, out, err = self.merge()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(out.splitlines()[0], "MERGE", out)

    def assertHold(self, reason):
        code, out, err = self.merge()
        self.assertEqual(code, 1, out + err)
        first = out.splitlines()[0]
        self.assertTrue(first.startswith("HOLD: "), out)
        self.assertIn(reason, first.lower(), out)

    # -- MERGE --------------------------------------------------------------------------------

    def test_all_green_merges(self):
        self.setup_branch()
        self.assertMerge()
        self.assertIn("pr view 7", (self.root.parent / "gh.log").read_text())

    def test_verdict_file_shares_gate_numbering(self):
        self.setup_branch()
        self.assertMerge()
        self.assertTrue((self.run / "gate" / "2-merge.md").read_text().startswith("MERGE"))

    def test_no_ci_configured_merges(self):
        self.setup_branch(pr={"statusCheckRollup": []})
        self.assertMerge()

    def test_assumptions_allowed_by_policy(self):
        self.setup_branch(policy=POLICY + "merge_with_assumptions = true\n", assumptions="- Q: x? chose y\n")
        self.assertMerge()

    def test_empty_assumptions_file_merges(self):
        self.setup_branch(assumptions="  \n")
        self.assertMerge()

    # -- HOLD, one per condition --------------------------------------------------------------

    def test_default_policy_is_never(self):
        self.setup_branch(policy=None)
        self.assertHold("never")

    def test_branch_cannot_loosen_base_policy(self):
        self.setup_branch(policy='[overnight]\nmerge = "never"\n')
        self.write(self.root, ".sstack/config.toml", POLICY)
        self.commit("loosen")
        self.assertHold("never")

    def test_gate_pr_verdict_missing(self):
        self.setup_branch(gate=None)
        self.assertHold("gate")

    def test_gate_pr_verdict_failed(self):
        self.setup_branch(gate="GATE: FAIL")
        self.assertHold("gate")

    def test_review_not_passed(self):
        self.setup_branch(review="fail")
        self.assertHold("review")

    def test_score_below_merge_min_score(self):
        self.setup_branch(score=7)
        self.assertHold("score")

    def test_draft(self):
        self.setup_branch(pr={"isDraft": True})
        self.assertHold("draft")

    def test_conflicts(self):
        self.setup_branch(pr={"mergeable": "CONFLICTING"})
        self.assertHold("conflict")

    def test_ci_pending(self):
        self.setup_branch(pr={"statusCheckRollup": [
            {"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]})
        self.assertHold("ci: pending")

    def test_ci_failed_status_context(self):
        self.setup_branch(pr={"statusCheckRollup": [{"__typename": "StatusContext", "state": "FAILURE"}]})
        self.assertHold("ci: failed")

    def test_ci_failed_wins_over_pending(self):
        self.setup_branch(pr={"statusCheckRollup": [
            {"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None},
            {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]})
        self.assertHold("ci: failed")

    def test_diff_too_large(self):
        self.setup_branch(pr={"additions": 399, "deletions": 2})
        self.assertHold("diff")

    def test_never_merge_glob(self):
        self.setup_branch(policy=POLICY + 'never_merge = ["migrations/**"]\n',
                          pr={"files": [{"path": "lib/a.py"}, {"path": "migrations/001.sql"}]})
        self.assertHold("never_merge")

    def test_assumptions_hold_by_default(self):
        self.setup_branch(assumptions="- Q: x? chose y\n")
        self.assertHold("assumption")

    def test_not_into_default_branch(self):
        self.setup_branch(pr={"baseRefName": "develop"})
        self.assertHold("base")

    def test_gate_verdict_for_another_head(self):
        self.setup_branch(pr={"headRefOid": "0" * 40})
        self.assertHold("head")

    def test_gate_verdict_on_a_dirty_tree(self):
        self.setup_branch()
        self.write(self.run, "gate/1-pr.md", f"GATE: PASS\n\n- Head: {self.head} (dirty)\n")
        self.assertHold("head")

    def test_gate_verdict_without_head(self):
        self.setup_branch()
        self.write(self.run, "gate/1-pr.md", "GATE: PASS\n")
        self.assertHold("head")

    def test_gate_records_head(self):
        self.setup_branch()
        r = subprocess.run([sys.executable, str(GATE), "--run", str(self.run), "--pr"], cwd=self.root,
                           capture_output=True, text=True)
        verdict = (self.run / "gate" / "2-pr.md").read_text()
        self.assertIn(f"- Head: {self.head}\n", verdict, r.stdout + r.stderr)

    def test_every_reason_listed(self):
        self.setup_branch(pr={"isDraft": True, "mergeable": "CONFLICTING"})
        code, out, _ = self.merge()
        self.assertEqual(code, 1)
        self.assertIn("draft", out.splitlines()[0].lower())
        self.assertIn("conflict", out.splitlines()[0].lower())

    # -- layers -------------------------------------------------------------------------------

    def test_home_layer_sets_bar(self):
        self.setup_branch(score=9)
        self.write(self.home, ".sstack/config.toml", "[overnight]\nmerge_min_score = 10\n")
        self.assertHold("score")

    def test_local_layer_tightens(self):
        self.setup_branch(score=9)
        self.write(self.root, ".sstack/local/config.toml", "[overnight]\nmerge_min_score = 10\n")
        self.assertHold("score")

    def test_code_changed_after_review(self):
        self.setup_branch()
        self.write(self.root, "lib/a.py", "x = 2\n")
        self.commit("unreviewed")
        self.gate_verdict(n=2)
        self.assertHold("review")

    def test_whitespace_change_after_review(self):
        self.setup_branch()
        self.write(self.root, "lib/a.py", "x =  1\n")
        self.commit("whitespace only, unreviewed")
        self.gate_verdict(n=2)
        self.assertHold("review")

    def test_review_checked_against_pr_head_not_local(self):
        self.setup_branch()
        reviewed = self.head
        self.write(self.root, "lib/a.py", "x = 2\n")
        self.commit("unreviewed")
        self.gate_verdict(n=2)  # the PR head is the unreviewed commit
        self.git("checkout", "-q", reviewed)
        self.assertHold("review")

    def test_rebase_after_review_keeps_it(self):
        self.setup_branch()
        self.git("switch", "-q", "main")
        self.write(self.root, "other.txt", "o\n")
        self.commit("main moves")
        self.git("push", "-q", "origin", "main")
        self.git("switch", "-q", "feature")
        self.git("rebase", "-q", "main")
        self.gate_verdict(n=2)
        self.assertMerge()

    def test_branch_tracked_local_symlink_ignored(self):
        self.setup_branch(policy='[overnight]\nmerge = "never"\n')
        self.write(self.root, "bp/config.toml", POLICY)
        os.symlink("../bp", self.root / ".sstack" / "local")
        self.commit("loosen via symlink")
        self.gate_verdict(n=2)
        self.assertHold("never")

    def test_branch_tracked_local_layer_ignored(self):
        self.setup_branch(policy='[overnight]\nmerge = "never"\n')
        self.write(self.root, ".sstack/local/config.toml", POLICY)
        self.commit("loosen via local")
        self.assertHold("never")

    # -- setup errors -------------------------------------------------------------------------

    def test_merge_needs_run(self):
        self.setup_branch()
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}")
        r = subprocess.run([sys.executable, str(GATE), "--merge", "7"], cwd=self.root, env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


class OvernightDoctorTests(test_doctor.DoctorBase):
    """R4: doctor FAILs each invalid [overnight] value; the defaults PASS."""

    def check(self, toml):
        self.glob_cfg(test_doctor.roles())
        if toml:
            self.repo_cfg("[overnight]\n" + toml)
        code, out, _ = self.doctor()
        return code, out

    def test_defaults_pass(self):
        code, out = self.check("")
        self.assertIn("PASS overnight", out)

    def test_valid_values_pass(self):
        code, out = self.check('merge = "policy"\nmethod = "squash"\nmerge_min_score = 10\n'
                               'max_diff_lines = 1\non_question = "park"\non_stuck = "park"\n'
                               'stop_at = "07:00"\nnever_merge = ["a/**"]\nmerge_with_assumptions = true\n')
        self.assertIn("PASS overnight", out)

    def test_invalid_values_fail(self):
        for toml in ('merge = "sometimes"\n', 'method = "fast"\n', "merge_min_score = 0\n",
                     "merge_min_score = 11\n", "max_diff_lines = 0\n", 'on_question = "ask"\n',
                     'on_stuck = "retry"\n', 'stop_at = "7am"\n', 'stop_at = "25:00"\n',
                     'never_merge = "a/**"\n', 'merge_with_assumptions = "yes"\n'):
            with self.subTest(toml=toml):
                code, out = self.check(toml)
                self.assertIn("FAIL overnight", out)
                self.assertEqual(code, 1)
