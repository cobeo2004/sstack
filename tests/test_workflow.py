"""Answer key for step folders and `sstack-workflow` (decisions R1–R7, R8, R20; docs/spec/workflow.md)."""
import json, os, subprocess, sys
from pathlib import Path

from helpers import TempEnv, REPO, FIXTURES
from test_dispatch import NO_T3
import sstack_config as C

WF = REPO / "bin" / "sstack-workflow"
DEFAULT_CHAIN = ["recon", "plan", "implement", "gate", "review", "pr"]


class WorkflowBase(TempEnv):
    def setUp(self):
        super().setUp()
        self.run_dir = self.root / ".sstack" / "runs" / "task-1"
        self.run_dir.mkdir(parents=True)

    def wf(self, *args, cwd=None):
        e = dict(NO_T3, HOME=str(self.home), USERPROFILE=str(self.home))
        r = subprocess.run([sys.executable, str(WF), *args], cwd=cwd or self.root, env=e,
                           capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def show(self) -> dict:
        code, out, err = self.wf("show", "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def step(self, layer: Path, name: str, toml: str = "", **files) -> Path:
        d = layer / "steps" / name
        d.mkdir(parents=True, exist_ok=True)
        if toml:
            (d / "step.toml").write_text(toml)
        for fname, text in files.items():
            p = d / fname.replace("_", ".")
            p.write_text(text)
            if p.suffix == ".sh":
                p.chmod(0o755)
        return d

    def repo(self):
        return self.root / ".sstack"

    auto_dispatch = True  # chain-logic tests: every step looks dispatched (DispatchCheckTests turns it off)

    def done(self, step, *extra):
        if self.auto_dispatch:
            self.record_dispatch(step)
        return self.wf("done", step, "--run", str(self.run_dir), *extra)

    def record_dispatch(self, step, role=None, flat=False, indexed=True, checkout=None):
        """What `sstack-dispatch <role> --step <step>` + `record` leave behind: run.json with the step
        and one index.jsonl line. flat: the run dir sits in `checkout`'s runs/ (report outside it)."""
        checkout = checkout or self.root
        runs = checkout / ".sstack" / "runs"
        d = runs / f"1000-{step}" if flat else self.run_dir / "dispatch" / f"1000-{step}"
        d.mkdir(parents=True, exist_ok=True)
        base = str(self.run_dir / step) if flat else f".sstack/runs/{self.run_dir.name}/{step}"
        (d / "run.json").write_text(json.dumps({"role": role or step, "step": step, "report_base": base}))
        if indexed:
            with (runs / "index.jsonl").open("a") as f:
                f.write(json.dumps({"role": role or step, "exit": 0,
                                    "run_dir": d.relative_to(checkout).as_posix()}) + "\n")

    def findings(self, rows) -> str:
        p = self.run_dir / "review" / "findings.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows))
        return str(p)


class ResolveTests(WorkflowBase):
    def test_default_chain_reproduces_the_phases(self):
        d = self.show()
        self.assertEqual(d["chain"], DEFAULT_CHAIN)
        s = d["steps"]
        self.assertEqual((s["recon"]["role"], s["recon"]["gate"], s["recon"]["max_agents"]), ("investigate", True, 3))
        self.assertEqual((s["plan"]["role"], s["plan"]["gate"], s["plan"]["max_agents"]), ("plan", True, 2))
        self.assertEqual((s["implement"]["role"], s["implement"]["gate"], s["implement"]["max_agents"]),
                         ("implement", False, 1))
        self.assertEqual((s["gate"]["kind"], s["gate"]["on_fail"], s["gate"]["max_agents"]), ("command", "implement", 0))
        self.assertTrue(s["gate"]["run"].endswith("defaults/steps/gate/run.sh"))
        self.assertEqual((s["review"]["role"], s["review"]["on_fail"], s["review"]["min_score"], s["review"]["gate"],
                          s["review"]["max_agents"]), ("review", "implement", 5, True, 2))
        self.assertEqual((s["pr"]["kind"], s["pr"]["gate"]), ("inline", True))

    def test_repo_override_merges_one_key(self):
        self.step(self.repo(), "review", "min_score = 7\n")
        r = self.show()["steps"]["review"]
        self.assertEqual((r["role"], r["on_fail"], r["min_score"]), ("review", "implement", 7))
        self.assertEqual(r["source"]["min_score"], "repo")
        self.assertEqual(r["source"]["role"], "home")

    def test_local_layer_beats_repo_per_key(self):
        self.step(self.repo(), "review", "min_score = 7\nmax_agents = 1\n")
        self.step(self.repo() / "local", "review", "min_score = 9\n")
        r = self.show()["steps"]["review"]
        self.assertEqual((r["min_score"], r["max_agents"]), (9, 1))
        self.assertEqual((r["source"]["min_score"], r["source"]["max_agents"]), ("local", "repo"))

    def test_custom_command_step_is_inserted_after_its_target(self):
        self.step(self.repo(), "dmm", 'after = "implement"\non_fail = "implement"\n', run_sh="#!/bin/sh\nexit 0\n")
        d = self.show()
        self.assertEqual(d["chain"], ["recon", "plan", "implement", "dmm", "gate", "review", "pr"])
        self.assertEqual(d["steps"]["dmm"]["kind"], "command")

    def test_custom_role_step_brief_nearest_layer_wins_whole(self):
        self.step(self.home / ".sstack", "dmm", 'after = "review"\nrole = "review"\n', brief_md="HOME BRIEF\n")
        self.step(self.repo(), "dmm", "", brief_md="REPO BRIEF\n")
        s = self.show()["steps"]["dmm"]
        self.assertEqual((s["kind"], s["role"]), ("role", "review"))
        self.assertEqual(Path(s["brief"]).read_text(), "REPO BRIEF\n")
        self.assertEqual(self.show()["chain"][-2:], ["dmm", "pr"])

    def test_disabled_custom_step_drops_out(self):
        self.step(self.repo(), "dmm", 'after = "implement"\nenabled = false\n', run_sh="#!/bin/sh\nexit 0\n")
        self.assertEqual(self.show()["chain"], DEFAULT_CHAIN)

    def test_disabled_middle_step_is_bypassed(self):
        self.step(self.repo(), "plan", "enabled = false\n")
        self.assertEqual(self.show()["chain"], ["recon", "implement", "gate", "review", "pr"])

    def test_two_customs_after_the_same_target_order_by_name(self):
        self.step(self.repo(), "zeta", 'after = "implement"\n', run_sh="#!/bin/sh\n")
        self.step(self.repo(), "alpha", 'after = "implement"\n', run_sh="#!/bin/sh\n")
        self.assertEqual(self.show()["chain"][2:6], ["implement", "alpha", "zeta", "gate"])

    def test_show_text_names_every_step(self):
        code, out, err = self.wf("show")
        self.assertEqual(code, 0, err)
        for name in DEFAULT_CHAIN:
            self.assertIn(name, out)

    def test_load_output_is_unchanged(self):
        """Step folders live outside load(); the frozen contract snapshot still holds."""
        want = json.loads((FIXTURES / "config" / "defaults-only" / "expected.json").read_text())
        self.step(self.repo(), "review", "min_score = 7\n")
        self.assertEqual(C.load(self.root), want)


class DoneTests(WorkflowBase):
    def test_profile_without_steps_points_at_sync(self):
        import shutil
        shutil.rmtree(self.home / ".sstack" / "steps")
        for args in (("done", "recon", "--run", str(self.run_dir)),
                     ("run", "gate", "--run", str(self.run_dir)),
                     ("status", "--run", str(self.run_dir))):
            code, _, err = self.wf(*args)
            self.assertEqual(code, 1, args)
            self.assertIn("sstack-config sync", err, args)

    def test_pass_moves_to_next(self):
        code, out, _ = self.done("implement")
        self.assertEqual(code, 0)
        self.assertIn("next: gate", out)
        self.assertNotIn("GATE", out)
        state = json.loads((self.run_dir / "workflow.json").read_text())
        self.assertEqual(state["steps"]["implement"]["status"], "pass")
        self.assertEqual(state["current"], "gate")

    def test_gate_true_step_prints_gate(self):
        code, out, _ = self.done("plan")
        self.assertEqual(code, 0)
        self.assertIn("GATE: wait for the user's yes", out)
        self.assertIn("next: implement", out)

    def test_gate_false_override_skips_the_gate_line(self):
        self.step(self.repo(), "plan", "gate = false\n")
        self.step(self.repo(), "review", "gate = false\n")
        _, out, _ = self.done("plan")
        self.assertNotIn("GATE", out)
        self.assertIn("next: implement", out)
        _, out, _ = self.done("review", "--findings", self.findings([{"reviewer": "a", "score": 9, "findings": []}]))
        self.assertNotIn("GATE", out)
        self.assertIn("next: pr", out)

    def test_last_step_reports_done(self):
        _, out, _ = self.done("pr")
        self.assertIn("next: done", out)

    def test_fail_routes_to_on_fail_then_stops_at_the_cap(self):
        self.step(self.repo(), "review", "max_loops = 2\n")
        code, out, _ = self.done("review", "--fail")
        self.assertEqual(code, 0)
        self.assertIn("next: implement", out)
        code, out, _ = self.done("review", "--fail")
        self.assertEqual(code, 2)
        self.assertIn("STOP: ask user", out)
        lines = [l for l in (self.run_dir / "progress.md").read_text().splitlines() if "review" in l]
        self.assertEqual(len(lines), 2)

    def test_max_loops_defaults_to_loop_guard(self):
        self.repo_cfg("[rules]\nloop_guard = 1\n")
        code, out, _ = self.done("gate", "--fail")
        self.assertEqual(code, 2)
        self.assertIn("STOP: ask user", out)

    def test_fail_without_on_fail_stops(self):
        code, out, _ = self.done("plan", "--fail")
        self.assertEqual(code, 2)
        self.assertIn("STOP: ask user", out)

    def test_status_reports_current_step_and_loop(self):
        self.done("review", "--fail")
        code, out, _ = self.wf("status", "--run", str(self.run_dir))
        self.assertEqual(code, 0)
        self.assertIn("at: implement", out)
        self.assertIn("review", out)


class ScoreTests(WorkflowBase):
    def check(self, rows, want_next):
        code, out, err = self.done("review", "--findings", self.findings(rows))
        self.assertIn(f"next: {want_next}", out, out + err)
        return code, out

    def test_low_score_with_verified_important_fails(self):
        self.check([{"reviewer": "a", "score": 4, "findings": [{"severity": "Important", "verified": True}]}],
                   "implement")

    def test_verified_important_caps_a_high_score(self):
        self.check([{"reviewer": "a", "score": 9, "findings": [{"severity": "Important", "verified": True}]}],
                   "implement")
        state = json.loads((self.run_dir / "workflow.json").read_text())
        self.assertEqual(state["steps"]["review"]["score"], 6)

    def test_dropped_important_raises_the_score(self):
        _, out = self.check([{"reviewer": "a", "score": 4, "findings": [
            {"severity": "Important", "verified": False}, {"severity": "Nit", "verified": True}]}], "pr")
        self.assertIn("GATE", out)
        self.assertEqual(json.loads((self.run_dir / "workflow.json").read_text())["steps"]["review"]["score"], 7)

    def test_nothing_verified_scores_ten(self):
        self.check([{"reviewer": "a", "score": 3, "findings": [{"severity": "Important", "verified": False}]}], "pr")
        self.assertEqual(json.loads((self.run_dir / "workflow.json").read_text())["steps"]["review"]["score"], 10)

    def test_final_is_the_minimum_across_reviewers(self):
        self.check([{"reviewer": "a", "score": 8, "findings": []},
                    {"reviewer": "b", "score": 4, "findings": [{"severity": "Important", "verified": True}]}],
                   "implement")
        self.assertEqual(json.loads((self.run_dir / "workflow.json").read_text())["steps"]["review"]["score"], 4)

    def test_repo_min_score_applies(self):
        self.step(self.repo(), "review", "min_score = 8\n")
        self.check([{"reviewer": "a", "score": 7, "findings": [{"severity": "Nit", "verified": True}]}], "implement")


class RunTests(WorkflowBase):
    def setUp(self):
        super().setUp()
        (self.home / ".sstack").mkdir(exist_ok=True)
        (self.home / ".sstack" / "repos.txt").write_text(f"{self.root}\n")

    def test_untrusted_checkout_refuses_a_repo_run_sh(self):
        (self.home / ".sstack" / "repos.txt").unlink()
        self.step(self.repo(), "gate", "", run_sh='#!/bin/sh\ntouch "$SSTACK_RUN/ran"\n')
        code, _, err = self.wf("run", "gate", "--run", str(self.run_dir))
        self.assertEqual(code, 1)
        self.assertIn("repos.txt", err)
        self.assertFalse((self.run_dir / "ran").exists())

    def test_failing_command_step_routes_to_on_fail(self):
        self.step(self.repo(), "dmm", 'after = "implement"\non_fail = "implement"\n', run_sh="#!/bin/sh\nexit 1\n")
        code, out, _ = self.wf("run", "dmm", "--run", str(self.run_dir))
        self.assertEqual(code, 0)
        self.assertIn("next: implement", out)
        self.assertEqual(json.loads((self.run_dir / "workflow.json").read_text())["steps"]["dmm"]["status"], "fail")

    def test_passing_command_step_moves_on(self):
        self.step(self.repo(), "dmm", 'after = "implement"\n', run_sh="#!/bin/sh\nexit 0\n")
        _, out, _ = self.wf("run", "dmm", "--run", str(self.run_dir))
        self.assertIn("next: gate", out)

    def test_command_runs_from_the_repo_root(self):
        self.step(self.repo(), "dmm", 'after = "implement"\n',
                  run_sh='#!/bin/sh\npwd > "$SSTACK_RUN/cwd.txt"\n')
        sub = self.root / "a" / "b"
        sub.mkdir(parents=True)
        code, _, err = self.wf("run", "dmm", "--run", str(self.run_dir), cwd=sub)
        self.assertEqual(code, 0, err)
        self.assertEqual(Path((self.run_dir / "cwd.txt").read_text().strip()).resolve(), self.root.resolve())


class DispatchCheckTests(WorkflowBase):
    """R1-R4 (workflow-adherence): a routed role step can't be recorded without its dispatch."""
    auto_dispatch = False

    def test_undispatched_role_step_is_refused_with_the_command(self):
        code, out, err = self.done("recon")
        self.assertEqual(code, 1, out)
        self.assertIn("sstack-dispatch investigate --step recon", err)
        self.assertFalse((self.run_dir / "workflow.json").exists())

    def test_nested_recorded_dispatch_passes(self):
        self.record_dispatch("recon", role="investigate")
        code, out, err = self.done("recon")
        self.assertEqual(code, 0, err)
        self.assertIn("next: plan", out)

    def test_flat_dispatch_from_another_checkout_counts(self):
        """Worktree case: the run folder lives in one checkout, dispatch ran in this one."""
        other = self.root.parent / "primary"
        self.run_dir = other / ".sstack" / "runs" / "task-1"
        self.run_dir.mkdir(parents=True)
        self.record_dispatch("plan", flat=True)
        code, _, err = self.done("plan")
        self.assertEqual(code, 0, err)

    def test_unrecorded_payload_does_not_count(self):
        self.record_dispatch("plan", indexed=False)
        code, _, err = self.done("plan")
        self.assertEqual(code, 1)
        self.assertIn("sstack-dispatch plan --step plan", err)

    def test_other_steps_dispatch_does_not_count(self):
        self.record_dispatch("recon", role="investigate")
        self.assertEqual(self.done("plan")[0], 1)

    def test_no_dispatch_reason_passes_and_is_logged(self):
        code, out, err = self.done("recon", "--no-dispatch", "swarm of 4 scouts")
        self.assertEqual(code, 0, err)
        self.assertIn("next: plan", out)
        self.assertIn("recon: no dispatch (swarm of 4 scouts)", (self.run_dir / "progress.md").read_text())

    def test_local_dispatch_config_skips_the_check(self):
        self.repo_cfg('[dispatch]\nvia = "local"\n')
        self.assertEqual(self.done("recon")[0], 0)

    def test_inline_max_agents_skips_the_check(self):
        self.step(self.repo(), "recon", "max_agents = 0\n")
        self.assertEqual(self.done("recon")[0], 0)

    def test_fail_is_never_refused(self):
        code, out, _ = self.done("review", "--fail")
        self.assertEqual(code, 0)
        self.assertIn("next: implement", out)

    def test_command_and_inline_steps_need_no_dispatch(self):
        self.assertEqual(self.done("gate")[0], 0)
        self.assertEqual(self.done("pr")[0], 0)

    def test_local_write_lock_holder_counts(self):
        """`sstack-dispatch implement --step implement --via local` (exit 3) holds the lock for this run."""
        lock = self.root / ".sstack" / "runs" / "implement.lock"
        import time
        lock.write_text(json.dumps({"holders": [{"owner": ".sstack/runs/task-1", "role": "implement",
                                                 "files": [], "started": time.time()}]}))
        code, _, err = self.done("implement")
        self.assertEqual(code, 0, err)

    def test_next_prints_how_to_do_it(self):
        self.record_dispatch("recon", role="investigate")
        _, out, _ = self.done("recon")
        self.assertIn("do: sstack-dispatch plan --step plan", out)
        self.record_dispatch("implement")
        _, out, _ = self.done("implement")
        self.assertIn(f"do: sstack-workflow run gate --run {self.run_dir}", out)
        _, out, _ = self.done("gate")
        self.assertIn("do: sstack-dispatch review --step review", out)


class ProposeTests(WorkflowBase):
    """`sstack-workflow propose`: a decider (or --json) proposal, kept only inside the bounds."""

    def propose(self, reply=None, payload=None):
        import contextlib, io
        from unittest import mock
        import sstack_workflow as W
        extra = []
        if payload is not None:
            p = self.run_dir / "proposal.json"
            p.write_text(json.dumps(payload))
            extra = ["--json", str(p)]
        out, err = io.StringIO(), io.StringIO()
        old = os.getcwd()
        os.chdir(self.root)
        try:
            with mock.patch("sstack_decider.propose", return_value=reply), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = W.main(["propose", "--run", str(self.run_dir), *extra])
        finally:
            os.chdir(old)
        return code, out.getvalue(), err.getvalue()

    def stored(self):
        p = self.run_dir / "workflow.json"
        return json.loads(p.read_text()).get("proposal") if p.exists() else None

    def test_decider_drop_pr_rejected(self):
        code, _, err = self.propose(reply={"skip": ["pr"]})
        self.assertEqual(code, 1)
        self.assertIn("pr", err)
        self.assertIsNone(self.stored())

    def test_drop_gate_rejected(self):
        code, _, err = self.propose(payload={"skip": ["gate"]})
        self.assertEqual(code, 1)
        self.assertIn("skip gate", err)
        self.assertIsNone(self.stored())

    def test_skip_review_on_security_rejected(self):
        self.write(self.root, "api/auth.py", "x = 1\n")
        code, _, err = self.propose(payload={"skip": ["review"]})
        self.assertEqual(code, 1)
        self.assertIn("security", err)
        self.assertIsNone(self.stored())

    def test_gate_answer_rejected(self):
        for p in ({"answer": "yes"}, {"approve": True}, {"gate": "pass"}, {"panel_size": 9}, {"repeat": {"pr": 1}}):
            code, _, _ = self.propose(payload=p)
            self.assertEqual(code, 1, p)
        self.assertIsNone(self.stored())

    def test_heuristic_proposes_nothing(self):
        code, out, _ = self.propose(reply=None)
        self.assertEqual(code, 0)
        self.assertIn("nothing proposed", out)
        self.assertIsNone(self.stored())

    def test_skip_applies(self):
        code, _, err = self.propose(payload={"skip": ["review"]})
        self.assertEqual(code, 0, err)
        self.assertEqual(self.stored(), {"skip": ["review"]})
        _, out, _ = self.done("gate")
        self.assertIn("next: pr", out)
        self.assertIn("proposal", (self.run_dir / "progress.md").read_text())

    def test_repeat_applies(self):
        self.assertEqual(self.propose(payload={"repeat": {"implement": 1}})[0], 0)
        _, out, _ = self.done("implement")
        self.assertIn("next: implement", out)
        _, out, _ = self.done("implement")
        self.assertIn("next: gate", out)

    def test_gate_still_asks_after_proposal(self):
        self.assertEqual(self.propose(reply={"skip": ["recon"], "panel_size": 2})[0], 0)
        _, out, _ = self.done("plan")
        self.assertIn("GATE: wait for the user's yes", out)

    def test_skip_review_rechecked_when_diff_turns_security(self):
        self.assertEqual(self.propose(payload={"skip": ["review"]})[0], 0)
        self.write(self.root, "api/auth.py", "x = 1\n")
        self.done("implement")
        _, out, err = self.done("gate")
        self.assertIn("next: review", out)
        self.assertIn("security change; review stays", err)

    def test_skip_implement_or_on_fail_target_rejected(self):
        code, _, err = self.propose(payload={"skip": ["implement"]})
        self.assertEqual(code, 1)
        self.assertIn("skip implement: implement", err)
        self.step(self.repo(), "lint", 'after = "plan"\non_fail = "recon"\n', run_sh="#!/bin/sh\n")
        code, _, err = self.propose(payload={"skip": ["recon"]})
        self.assertEqual(code, 1)
        self.assertIn("skip recon: the on_fail target of lint", err)
        self.assertIsNone(self.stored())

    def test_status_shows_proposal(self):
        self.assertEqual(self.propose(payload={"skip": ["review"], "repeat": {"implement": 1}})[0], 0)
        _, out, _ = self.wf("status", "--run", str(self.run_dir))
        self.assertIn('proposal: {"repeat": {"implement": 1}, "skip": ["review"]}', out)


class OutcomeTests(WorkflowBase):
    def test_done_appends_gate_and_score(self):
        self.done("implement", "--fail")
        self.done("review", "--findings", self.findings([{"reviewer": "a", "score": 9, "findings": []}]))
        rows = [json.loads(l) for l in (self.run_dir / "outcomes.jsonl").read_text().splitlines()]
        self.assertEqual([(r["step"], r["gate"], r["score"]) for r in rows],
                         [("implement", "fail", None), ("review", "pass", 9)])
        self.assertTrue(all(set(r) == {"ts", "step", "gate", "score"} for r in rows))
