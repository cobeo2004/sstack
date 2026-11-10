"""bin/sstack-gate: the deterministic gate (R1-R11).

Answer key for PR2 steps 2.2-2.4, written before `bin/sstack-gate` exists: every test below fails
while the script is missing and passes once it is built to the contract in
`.sstack/runs/gate-and-runs-*/plan.md` (PR2 answer key, T2.a-T2.n). Fixture steps are asserted, so a
broken fixture fails as itself instead of looking like a gate bug.
"""
import hashlib, json, os, shlex, subprocess, sys
from pathlib import Path

from helpers import REPO, TempEnv

GATE = REPO / "bin" / "sstack-gate"


class GateTests(TempEnv):
    # -- fixture -------------------------------------------------------------------------------

    def setUp(self):
        super().setUp()
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "user.email", "gate@example.invalid")
        self.git("config", "user.name", "Gate Test")

    def sh(self, *cmd, cwd=None):
        r = subprocess.run([str(c) for c in cmd], cwd=str(cwd or self.root),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"{' '.join(map(str, cmd))} failed: {r.stderr}")
        return r.stdout

    def git(self, *args):
        return self.sh("git", *args)

    def commit(self, msg="change"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def config(self, **cfg):
        """`verify` (string or list) and `protected` as TOML; json strings are valid TOML."""
        return "".join(f"{k} = {json.dumps(v)}\n" for k, v in cfg.items())

    def base(self, toml=True, files=None, **cfg):
        """Commit `main` with `.sstack/project.toml` = `cfg` (or `toml` verbatim; False = no base
        config), push it to a bare `origin.git` beside the repo, then branch `feature` off it."""
        if toml is True:
            toml = self.config(**cfg)
        if toml:
            self.write(self.root, ".sstack/project.toml", toml)
        for rel, text in (files or {}).items():
            self.write(self.root, rel, text)
        self.commit("base")
        self.sh("git", "init", "-q", "--bare", str(self.root.parent / "origin.git"))
        self.git("remote", "add", "origin", str(self.root.parent / "origin.git"))
        self.git("push", "-q", "-u", "origin", "main")
        self.git("remote", "set-head", "origin", "main")
        self.git("switch", "-q", "-c", "feature")
        self.write(self.home, ".sstack/repos.txt", f"{self.root}\n")

    def run_dir(self):
        p = self.root.parent / "run"
        p.mkdir(exist_ok=True)
        return p

    def mark(self, name):
        """A marker outside the repo: proof a `verify` command ran, invisible to the diff."""
        return self.root.parent / name

    def touch_cmd(self, path):
        return f"touch {shlex.quote(str(path))}"

    def media(self, run, *names, text="placeholder\n"):
        d = run / "media"
        d.mkdir(exist_ok=True)
        for name in names:
            (d / name).write_text(text)
        return d

    def manifest(self, run, files):
        """What `work` Phase 1 writes: backups plus a shasum -a 256 style SHA256SUMS."""
        d = run / "protected"
        d.mkdir(parents=True, exist_ok=True)
        rows = []
        for rel, text in files.items():
            self.write(d, rel, text)
            rows.append(f"{hashlib.sha256(text.encode()).hexdigest()}  {rel}\n")
        (d / "SHA256SUMS").write_text("".join(rows))

    # -- helpers -------------------------------------------------------------------------------

    def gate(self, *args):
        self.assertTrue(GATE.is_file(), f"{GATE} is missing: bin/sstack-gate is not built yet")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("T3CODE", "SSTACK_"))}
        env["HOME"] = str(self.home)
        return subprocess.run([sys.executable, str(GATE), *args], cwd=str(self.root), env=env,
                              capture_output=True, text=True, timeout=180)

    def output(self, r):
        return (r.stdout + r.stderr)[-2000:]

    def passed(self, r):
        self.assertEqual(r.returncode, 0, self.output(r))
        return r

    def gated(self, r):
        self.assertEqual(r.returncode, 1, self.output(r))
        return r

    def usage(self, r):
        self.assertEqual(r.returncode, 2, self.output(r))
        return r

    def verdict(self, run, name="1.md"):
        p = run / "gate" / name
        self.assertTrue(p.is_file(), f"{p} was not written; gate/ holds "
                                     f"{sorted(x.name for x in (run / 'gate').glob('*'))}")
        return p.read_text()

    def expect(self, text, status, *needles):
        self.assertEqual(text.splitlines()[0], f"GATE: {status}", text[:800])
        self.assertIn("## Summary", text)
        for needle in needles:
            self.assertIn(needle, text)
        return text

    # -- T2.a ----------------------------------------------------------------------------------

    def test_t2a_pass_writes_verdict_and_full_log(self):
        self.base(verify=["echo alpha-one", "echo beta-two"])
        run = self.run_dir()
        self.passed(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "PASS")
        log = (run / "gate" / "1.log").read_text()
        self.assertIn("alpha-one", log)
        self.assertIn("beta-two", log)

    # -- T2.b (2 cases) ------------------------------------------------------------------------

    def test_t2b_1_verify_as_a_string_runs_and_writes_nothing(self):
        ran = self.mark("string-ran")
        self.base(verify=self.touch_cmd(ran))
        before = self.git("status", "--porcelain")
        r = self.gate()  # no --run: verdict on stdout, nothing written
        self.expect(self.passed(r).stdout, "PASS")
        self.assertTrue(ran.is_file(), "a string verify did not run through sh")
        self.assertEqual(self.git("status", "--porcelain"), before, "a gate without --run wrote files")

    def test_t2b_2_failing_command_fails_with_its_tail_and_stops(self):
        self.base(verify=["true", "echo fail-tail-marker && exit 3", "touch after-fail"])
        run = self.run_dir()
        self.gated(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "FAIL", "fail-tail-marker")
        self.assertFalse((self.root / "after-fail").exists(), "a later command ran after the failure")

    # -- T2.c, T2.c2 ---------------------------------------------------------------------------

    def test_t2c_branch_rewriting_project_toml_fails_on_the_base_config(self):
        base_ran, branch_ran = self.mark("base-ran"), self.mark("branch-ran")
        self.base(verify=self.touch_cmd(base_ran))
        self.write(self.root, ".sstack/project.toml",
                   self.config(verify=self.touch_cmd(branch_ran)))
        self.commit("rewrite the checks")
        run = self.run_dir()
        self.gated(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "FAIL", ".sstack/project.toml")
        self.assertTrue(base_ran.is_file(), "the base copy's verify is the one that must run")
        self.assertFalse(branch_ran.exists(), "the branch's own verify ran: the checks are not pinned")

    def test_t2c2_unrelated_change_passes_with_the_base_config(self):
        base_ran = self.mark("base-ran")
        self.base(verify=self.touch_cmd(base_ran), files={"lib/app.py": "x = 1\n"})
        self.write(self.root, "notes.txt", "unrelated\n")
        self.commit("unrelated change")
        run = self.run_dir()
        self.passed(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "PASS")
        self.assertTrue(base_ran.is_file(), "the base config's verify did not run")

    # -- T2.d (3 cases), T2.d2, T2.d3 ----------------------------------------------------------

    def test_t2d_1_protected_file_modified_fails(self):
        self.base(verify="true", protected=["lib/core/*"], files={"lib/core/a.py": "x = 1\n"})
        self.write(self.root, "lib/core/a.py", "x = 2\n")
        self.commit("edit a protected file")
        run = self.run_dir()
        self.gated(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "FAIL", "lib/core/a.py")

    def test_t2d_2_protected_file_deleted_fails(self):
        self.base(verify="true", protected=["lib/core/*"],
                  files={"lib/core/a.py": "x = 1\n", "lib/core/b.py": "y = 1\n"})
        self.git("rm", "-q", "lib/core/b.py")
        self.commit("delete a protected file")
        run = self.run_dir()
        self.gated(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "FAIL", "lib/core/b.py")

    def test_t2d_3_new_file_under_a_protected_glob_passes(self):
        self.base(verify="true", protected=["lib/core/*"], files={"lib/core/a.py": "x = 1\n"})
        self.write(self.root, "lib/core/new.py", "z = 1\n")
        self.commit("add under the glob")
        run = self.run_dir()
        self.passed(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "PASS")

    def test_t2d2_renamed_protected_file_fails(self):
        self.base(verify="true", protected=["lib/core/*"], files={"lib/core/a.py": "x = 1\n"})
        self.git("mv", "lib/core/a.py", "lib/moved.py")
        self.commit("rename a protected file")
        run = self.run_dir()
        self.gated(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "FAIL", "lib/core/a.py")

    def test_t2d3_uncommitted_project_toml_edit_fails(self):
        self.base(verify="true")
        self.write(self.root, ".sstack/project.toml", self.config(verify="true") + "# edited\n")
        run = self.run_dir()
        self.gated(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "FAIL", ".sstack/project.toml")

    # -- T2.e ----------------------------------------------------------------------------------

    def test_t2e_base_without_config_uses_the_working_tree_copy(self):
        wt, local = self.mark("working-tree-ran"), self.mark("local-layer-ran")
        self.base(toml=False, files={"lib/app.py": "x = 1\n"})
        self.write(self.root, ".sstack/project.toml", self.config(verify=self.touch_cmd(wt)))
        self.write(self.root, ".sstack/local/project.toml", self.config(verify=self.touch_cmd(local)))
        run = self.run_dir()
        self.passed(self.gate("--run", str(run)))
        text = self.expect(self.verdict(run), "PASS")
        self.assertIn("working tree", text.lower())
        self.assertTrue(wt.is_file(), "the working tree's verify did not run")
        self.assertFalse(local.exists(), ".sstack/local/project.toml must never be read")

    # -- T2.f ----------------------------------------------------------------------------------

    def test_t2f_unregistered_repo_exits_2_and_runs_nothing(self):
        ran = self.mark("verify-ran")
        self.base(verify=self.touch_cmd(ran))
        (self.home / ".sstack" / "repos.txt").unlink()
        run = self.run_dir()
        self.usage(self.gate("--run", str(run)))
        self.assertFalse(ran.exists(), "verify ran in an unregistered repo")
        self.assertFalse((run / "gate").exists(), "a setup error wrote a verdict")

    # -- T2.g (4 cases) ------------------------------------------------------------------------

    def test_t2g_1_repo_file_changed_behind_its_backup_fails(self):
        self.base(verify="true", files={"lib/core/a.py": "x = 1\n"})
        run = self.run_dir()
        self.manifest(run, {"lib/core/a.py": "x = 1\n"})
        self.write(self.root, "lib/core/a.py", "tampered\n")
        self.commit("edit after the manifest was written")
        self.gated(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "FAIL", "lib/core/a.py")

    def test_t2g_2_untouched_protected_file_passes(self):
        self.base(verify="true", files={"lib/core/a.py": "x = 1\n"})
        run = self.run_dir()
        self.manifest(run, {"lib/core/a.py": "x = 1\n"})
        self.passed(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "PASS")

    def test_t2g_3_backups_without_a_manifest_fail_with_the_command(self):
        self.base(verify="true", files={"lib/core/a.py": "x = 1\n"})
        run = self.run_dir()
        self.manifest(run, {"lib/core/a.py": "x = 1\n"})
        (run / "protected" / "SHA256SUMS").unlink()
        self.gated(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "FAIL", "SHA256SUMS")

    def test_t2g_4_no_protected_dir_checks_nothing(self):
        self.base(verify="true", files={"lib/core/a.py": "x = 1\n"})
        self.write(self.root, "lib/core/a.py", "tampered\n")
        self.commit("edit with no manifest in the run")
        run = self.run_dir()
        self.passed(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "PASS")

    # -- T2.h (2 cases) ------------------------------------------------------------------------

    def test_t2h_1_backend_change_without_an_mmd_owes_a_diagram(self):
        self.base(verify="true", files={"lib/app.py": "x = 1\n"})
        self.write(self.root, "lib/app.py", "x = 2\n")
        self.commit("backend change")
        run = self.run_dir()
        self.media(run)
        self.gated(self.gate("--run", str(run), "--pr"))
        self.expect(self.verdict(run, "1-pr.md"), "FAIL", "diagram")

    def test_t2h_2_an_archify_png_never_replaces_the_mmd(self):
        self.base(verify="true", files={"lib/app.py": "x = 1\n"})
        self.write(self.root, "lib/app.py", "x = 2\n")
        self.commit("backend change")
        run = self.run_dir()
        self.media(run, "before-flow.png", "after-flow.png")
        self.gated(self.gate("--run", str(run), "--pr"))
        self.expect(self.verdict(run, "1-pr.md"), "FAIL", "diagram")

    # -- T2.i ----------------------------------------------------------------------------------

    def test_t2i_frontend_change_without_an_image_owes_an_image(self):
        self.base(verify="true", files={"web/App.tsx": "export const A = 1\n"})
        self.write(self.root, "web/App.tsx", "export const A = 2\n")
        self.commit("frontend change")
        run = self.run_dir()
        self.media(run)
        self.gated(self.gate("--run", str(run), "--pr"))
        self.expect(self.verdict(run, "1-pr.md"), "FAIL", "image")

    # -- T2.j (2 cases) ------------------------------------------------------------------------

    def test_t2j_1_after_without_before_fails(self):
        self.base(verify="true", files={"lib/app.py": "x = 1\n"})
        self.write(self.root, "lib/app.py", "x = 2\n")
        self.commit("backend change")
        run = self.run_dir()
        self.media(run, "after-x.mmd")
        self.gated(self.gate("--run", str(run), "--pr"))
        self.expect(self.verdict(run, "1-pr.md"), "FAIL", "before")

    def test_t2j_2_no_before_reason_passes_and_is_quoted(self):
        reason = "the previous flow was deleted with the old screen"
        self.base(verify="true", files={"lib/app.py": "x = 1\n"})
        self.write(self.root, "lib/app.py", "x = 2\n")
        self.commit("backend change")
        run = self.run_dir()
        self.media(run, "after-x.mmd")  # no before-x.mmd on purpose
        (run / "media" / "no-before.md").write_text(f"{reason}\n")
        self.passed(self.gate("--run", str(run), "--pr"))
        self.expect(self.verdict(run, "1-pr.md"), "PASS", reason)

    # -- T2.k ----------------------------------------------------------------------------------

    def test_t2k_skip_waives_the_evidence_check(self):
        reason = "no UI touched here, waiver agreed in review"
        self.base(verify="true", files={"lib/app.py": "x = 1\n"})
        self.write(self.root, "lib/app.py", "x = 2\n")
        self.commit("backend change")
        run = self.run_dir()
        (self.media(run) / "skip.md").write_text(f"{reason}\n")
        self.passed(self.gate("--run", str(run), "--pr"))
        self.expect(self.verdict(run, "1-pr.md"), "PASS", "MEDIA WAIVED:", reason)

    # -- T2.l (2 cases) ------------------------------------------------------------------------

    def test_t2l_1_test_only_change_owes_no_evidence(self):
        self.base(verify="true", files={"tests/test_app.py": "def test_a():\n    pass\n"})
        self.write(self.root, "tests/test_app.py", "def test_a():\n    assert True\n")
        self.commit("test only")
        run = self.run_dir()
        self.media(run)
        self.passed(self.gate("--run", str(run), "--pr"))
        self.expect(self.verdict(run, "1-pr.md"), "PASS")

    def test_t2l_2_docs_and_config_only_owe_no_evidence(self):
        self.base(verify="true", files={"README.md": "# sstack\n", "config.toml": "a = 1\n"})
        self.write(self.root, "README.md", "# sstack\n\nmore prose\n")
        self.write(self.root, "config.toml", "a = 2\n")
        self.commit("docs and config only")
        run = self.run_dir()
        self.media(run)
        self.passed(self.gate("--run", str(run), "--pr"))
        self.expect(self.verdict(run, "1-pr.md"), "PASS")

    # -- T2.m ----------------------------------------------------------------------------------

    def test_t2m_verdicts_are_numbered_across_calls(self):
        self.base(verify="true")
        run = self.run_dir()
        self.passed(self.gate("--run", str(run)))
        self.passed(self.gate("--run", str(run)))
        self.passed(self.gate("--run", str(run), "--pr"))
        for name in ("1.md", "2.md", "3-pr.md"):
            self.expect(self.verdict(run, name), "PASS")
        self.assertFalse((run / "gate" / "3.md").exists(), "--pr must write <n>-pr.md")
        self.assertFalse((run / "gate" / "4.md").exists(), "the --pr call must share the numbering")

    # -- T2.n ----------------------------------------------------------------------------------

    def test_t2n_pr_without_run_is_a_usage_error(self):
        self.base(verify="true")
        before = self.git("status", "--porcelain")
        self.usage(self.gate("--pr"))
        self.assertEqual(self.git("status", "--porcelain"), before, "a usage error wrote files")
