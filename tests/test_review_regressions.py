"""Regressions from the workflow-adherence review (codex/gpt-6.1-sol, both reproduced)."""
import json
import shlex
import time

from test_workflow import WorkflowBase
from test_dispatch import DispatchBase, FakeCliBase, T3
from test_session_harness import CLAUDE


class StaleLockTests(WorkflowBase):
    auto_dispatch = False

    def test_expired_lock_holder_is_not_a_dispatch(self):
        lock = self.root / ".sstack" / "runs" / "implement.lock"
        lock.write_text(json.dumps({"holders": [{"owner": ".sstack/runs/task-1", "role": "implement",
                                                 "files": [], "started": time.time() - 86400}]}))
        code, _, err = self.done("implement")
        self.assertEqual(code, 1)
        self.assertIn("sstack-dispatch implement --step implement", err)


class PendingPayloadTests(WorkflowBase):
    """Review 3: a write payload nobody launched holds the lock, but is not a dispatch until `record`."""
    auto_dispatch = False

    def dispatch(self, *extra, env=None):
        p = self.root / "b.md"
        p.write_text("do it")
        return DispatchBase.run_main(self, "implement", "--step", "implement", "--brief", str(p),
                                     "--report", str(self.run_dir / "implement.md"), *extra, env=env)[0]

    def test_unstarted_write_payload_is_refused(self):
        self.assertEqual(self.dispatch(env=T3), 4)
        code, _, err = self.done("implement")
        self.assertEqual(code, 1, err)

    def test_local_dispatch_still_counts(self):
        self.assertEqual(self.dispatch("--via", "local"), 3)
        code, _, err = self.done("implement")
        self.assertEqual(code, 0, err)


class EscalationLockTests(FakeCliBase):
    def setUp(self):
        super().setUp()
        self.example()

    def test_escalating_to_a_shell_writer_waits_for_other_writers(self):
        """B (Agent, own worktree) fails and would escalate to a Bash child in this tree while
        A's Bash child still edits it: no escalation, the failure stands."""
        d = self.root / ".sstack" / "steps" / "implement"
        d.mkdir(parents=True, exist_ok=True)
        (d / "step.toml").write_text("max_agents = 2\n")
        tiers = self.home / ".sstack" / "tiers"
        (tiers / "strong.toml").write_text('harness = "pi"\nmodel = "big"\n')  # standard → strong is a shell member

        def go(task, f):
            p = self.root / ".sstack" / "runs" / task / "r.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            return self.run_main("implement", "--step", "implement", "--brief", self.brief(), "--report", str(p),
                                 "--files", f, env=CLAUDE)

        code_a, out_a, _ = go("a", "README.md")
        code_b, out_b, _ = go("b", "x.py")
        self.assertEqual((code_a, json.loads(out_a)["calls"][0]["tool"]), (4, "Bash"))
        self.assertEqual((code_b, json.loads(out_b)["calls"][0]["tool"]), (4, "Agent"))
        rec = shlex.split(json.loads(out_b)["calls"][0]["record"].replace("{exit}", "1").replace("'<CHILD_THREAD_ID>'", "thread-1"))[1:]
        code, out, err = self.run_main(*rec, env=CLAUDE)
        self.assertNotEqual(code, 4, out)
        self.assertIn("not escalated", err)
        # re-review: B finished and nothing replaced it, so only A still holds the checkout
        lock = json.loads((self.root / ".sstack" / "runs" / "implement.lock").read_text())
        self.assertEqual([h["owner"] for h in lock["holders"]], [".sstack/runs/a"])
