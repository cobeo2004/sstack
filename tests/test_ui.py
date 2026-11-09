import contextlib, io, json, os, threading, urllib.request, urllib.error
from unittest import mock

from helpers import TempEnv, REPO
import sstack_ui as U
import sstack_dispatch as D

TOML = """# my config
[transport]
mode = "auto"  # keep this comment

[role.scout]
harness = "claude"
model = "haiku"

[role.implement]
harness = "pi"
model = "old"
effort = "low"

[rules]
max_parallel = 2
"""


class RoleTableTests(TempEnv):
    def test_replace_role_table_preserves_rest(self):
        out = U.replace_role_table(TOML, "implement", {"harness": "codex", "model": 'g"x', "effort": None})
        want = TOML.replace('[role.implement]\nharness = "pi"\nmodel = "old"\neffort = "low"\n',
                            '[role.implement]\nharness = "codex"\nmodel = "g\\"x"\n')
        self.assertEqual(out, want)

    def test_replace_role_table_appends(self):
        out = U.replace_role_table(TOML, "plan", {"harness": "claude", "model": "opus", "effort": "high"})
        self.assertTrue(out.startswith(TOML))
        self.assertTrue(out.endswith('\n[role.plan]\nharness = "claude"\nmodel = "opus"\neffort = "high"\n'))
        self.assertEqual(U.replace_role_table("", "plan", {"harness": "pi"}), '[role.plan]\nharness = "pi"\n')


class ServerTests(TempEnv):
    def setUp(self):
        super().setUp()
        self.example()
        (self.home / ".sstack/repos.txt").write_text(f"{self.root}\n/nonexistent/repo\n")
        self.token = "tok"
        self.srv = U.make_server(0, self.token)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()
        super().tearDown()

    def get(self, path, token=True):
        sep = "&" if "?" in path else "?"
        url = self.base + path + (f"{sep}t={self.token}" if token else "")
        with urllib.request.urlopen(url) as r:
            return json.loads(r.read())

    def post(self, path, body):
        req = urllib.request.Request(f"{self.base}{path}?t={self.token}", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_token_required(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/api/repos", token=False)
        self.assertEqual(cm.exception.code, 403)
        self.assertEqual(self.get("/api/repos")["repos"], [str(self.root)])

    def test_lessons_accept_roundtrip(self):
        p = self.write(self.root, ".sstack/lessons.md", "# Lessons\n\n- [pending] seen=1 id=L1 | x\n")
        self.post("/api/lessons/accept", {"repo": str(self.root), "scope": "repo", "id": "L1"})
        self.assertIn("[accepted]", p.read_text())
        ls = self.get(f"/api/lessons?repo={self.root}")["lessons"]
        self.assertEqual([(l["id"], l["status"], l["scope"]) for l in ls], [("L1", "accepted", "repo")])

    def test_role_save_changes_dry_run(self):
        self.post("/api/roles", {"repo": str(self.root), "layer": "local", "role": "implement",
                                 "harness": "codex", "model": "gpt-6.1-sol", "effort": ""})
        out = io.StringIO()
        env = {k: v for k, v in os.environ.items() if not k.startswith("T3CODE")}
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out):
            old = os.getcwd(); os.chdir(self.root)
            try:
                D.main(["implement", "--brief", "/dev/null", "--report", "/dev/null", "--dry-run"])
            finally:
                os.chdir(old)
        self.assertIn("headless: codex exec --sandbox workspace-write -m gpt-6.1-sol -", out.getvalue())
        cfg = self.get(f"/api/config?repo={self.root}")
        impl = next(r for r in cfg["roles"] if r["role"] == "implement")
        self.assertEqual((impl["source"], impl["members"][0]["harness"]), ("local", "codex"))

    def test_cookie_alone_cannot_post(self):
        req = urllib.request.Request(f"{self.base}/api/lessons/forget", b'{}',
                                     {"Content-Type": "text/plain", "Cookie": f"sstack={self.token}"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 403)

    def test_bad_role_save_leaves_file(self):
        text = '[rules\n'  # a broken sibling file: the save must not stick
        p = self.write(self.root, ".sstack/local/config.toml", text)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/api/roles", {"repo": str(self.root), "layer": "local", "role": "implement",
                                     "harness": "codex", "model": "m"})
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(p.read_text(), text)
        self.assertFalse((self.root / ".sstack/local/roles/implement.toml").exists())

    def test_runs_newest_first(self):
        self.write(self.root, ".sstack/runs/index.jsonl",
                   json.dumps({"ts": "1", "role": "a"}) + "\n" + json.dumps({"ts": "2", "role": "b"}) + "\n")
        self.assertEqual([r["role"] for r in self.get(f"/api/runs?repo={self.root}")["runs"]], ["b", "a"])

    def test_overview_without_sstack_dir(self):
        ov = self.get(f"/api/overview?repo={self.root}")
        self.assertEqual((ov["lessons_pending"], ov["runs_week"]), (0, 0))
        self.assertEqual(self.get("/api/overview?repo=global")["lessons_pending"], 0)

    def test_graph_read_creates_nothing(self):
        self.get(f"/api/graph?repo={self.root}")
        self.assertFalse((self.root / ".code-review-graph").exists())

    def test_other_endpoints_ok(self):
        for p in ("/api/workflows", "/api/graph", "/api/config"):
            self.assertIsInstance(self.get(f"{p}?repo={self.root}"), dict)
        with urllib.request.urlopen(f"{self.base}/?t={self.token}") as r:
            self.assertIn(b"<title>", r.read())
