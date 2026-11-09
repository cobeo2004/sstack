import json, os, shutil, threading, urllib.error, urllib.parse, urllib.request
from unittest import mock

from helpers import FIXTURES, TempEnv
import sstack_ui as U

REVIEW = 'mode = "single"\nharness = "codex"\nmodel = "gpt-6.1-sol"\n'


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

    def request(self, method, path, body=None, content_type="application/json", token=True, headers=None):
        sep = "&" if "?" in path else "?"
        url = self.base + path + (f"{sep}t={self.token}" if token else "")
        data = json.dumps(body).encode() if body is not None else None
        headers = dict(headers or {})
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def get(self, path, token=True):
        return self.request("GET", path, content_type=None, token=token)

    def put(self, path, text, repo=True):
        q = f"?repo={urllib.parse.quote(str(self.root))}" if repo and "?" not in path else ""
        return self.request("PUT", path + q, {"text": text})

    def delete(self, path):
        q = f"?repo={urllib.parse.quote(str(self.root))}"
        return self.request("DELETE", path + q)

    def test_symlinked_repo_layer_root_refused(self):
        outside = self.home / "outside"
        outside.mkdir()
        (self.root / ".sstack/local").mkdir(parents=True, exist_ok=True)
        shutil.rmtree(self.root / ".sstack/local")
        (self.root / ".sstack/local").symlink_to(outside)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.put("/api/config/local/roles/review", REVIEW)
        self.assertEqual(e.exception.code, 400)
        self.assertEqual(list(outside.iterdir()), [])

    def test_worktree_reset_validates_the_fallback_layer(self):
        import subprocess
        g = lambda *a: subprocess.run(["git", "-C", str(self.root), *a], check=True, capture_output=True)
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i")
        wt = (self.root.parent / "wt").resolve()
        g("worktree", "add", "-q", str(wt))
        (self.root / ".sstack/local/roles").mkdir(parents=True, exist_ok=True)
        (self.root / ".sstack/local/roles/review.toml").write_text('harness = "nope"\nmodel = "x"\n')
        (wt / ".sstack/local").mkdir(parents=True)
        (wt / ".sstack/local/config.toml").write_text('[dispatch]\nvia = "auto"\n')
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.request("DELETE", f"/api/config/local/config?repo={urllib.parse.quote(str(wt))}")
        self.assertEqual(e.exception.code, 400)
        self.assertTrue((wt / ".sstack/local/config.toml").is_file())

    def test_token_required(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/api/repos", token=False)
        self.assertEqual(cm.exception.code, 403)
        self.assertEqual(self.get("/api/repos")["repos"], [str(self.root)])

    def test_full_page_and_modules_need_the_token(self):
        with urllib.request.urlopen(f"{self.base}/?t={self.token}") as r:
            html = r.read().decode()
        self.assertIn("<title>sstack cockpit</title>", html)
        self.assertIn(self.token, html)
        for path in ("/ui/tokens.css", "/ui/app.js", "/ui/pages/config.js"):
            with urllib.request.urlopen(f"{self.base}{path}?t={self.token}") as r:
                self.assertEqual(r.status, 200)
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(f"{self.base}{path}")
            self.assertEqual(cm.exception.code, 403)

    def test_layer_file_read(self):
        got = self.get(f"/api/config/home/roles/review?repo={self.root}")
        self.assertTrue(got["exists"])
        self.assertEqual(got["layer"], "home")
        self.assertIn('harness = "codex"', got["text"])
        self.assertEqual(got["path"], str(self.home / ".sstack/roles/review.toml"))
        missing = self.get(f"/api/config/local/roles/review?repo={self.root}")
        self.assertFalse(missing["exists"])
        self.assertEqual(missing["text"], "")

    def test_put_writes_only_the_chosen_layer(self):
        self.put("/api/config/local/roles/review", REVIEW)
        self.assertEqual((self.root / ".sstack/local/roles/review.toml").read_text(), REVIEW)
        self.assertFalse((self.root / ".sstack/roles/review.toml").exists())
        cfg = self.get(f"/api/config?repo={self.root}")
        review = next(t for t in cfg["things"] if t["kind"] == "roles" and t["name"] == "review")
        self.assertEqual(review["source"], "local")
        self.assertEqual(review["value"]["mode"], "single")

    def test_put_refuses_defaults_hooks_notes_and_escapes(self):
        for path, text in (
            ("/api/config/defaults/roles/review", REVIEW),
            ("/api/config/local/ades/t3.hook", "#!/bin/sh\n"),
            ("/api/config/local/ades/t3.md", "note\n"),
            ("/api/config/local/roles/%2E%2E%2Fescape", REVIEW),
        ):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.put(path, text)
            self.assertEqual(cm.exception.code, 400, path)
        self.assertFalse((self.root / ".sstack/local/roles").exists())

    def test_invalid_toml_returns_400_and_leaves_the_file_alone(self):
        p = self.write(self.root, ".sstack/local/config.toml", "[rules]\nmax_parallel = 2\n")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.put("/api/config/local/config", "[rules\n")
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(p.read_text(), "[rules]\nmax_parallel = 2\n")

    def test_load_failure_restores_the_new_file(self):
        # A broken sibling makes the layered load fail after the write. The write must disappear.
        self.write(self.root, ".sstack/local/config.toml", "[rules\n")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.put("/api/config/local/roles/review", REVIEW)
        self.assertEqual(cm.exception.code, 400)
        self.assertFalse((self.root / ".sstack/local/roles/review.toml").exists())

    def test_delete_resets_to_inherited(self):
        self.put("/api/config/local/roles/review", REVIEW)
        out = self.delete("/api/config/local/roles/review")
        self.assertTrue(out["removed"])
        self.assertFalse((self.root / ".sstack/local/roles/review.toml").exists())
        cfg = self.get(f"/api/config?repo={self.root}")
        review = next(t for t in cfg["things"] if t["kind"] == "roles" and t["name"] == "review")
        self.assertEqual(review["source"], "home")

    def test_writes_require_json_content_type(self):
        req = urllib.request.Request(
            f"{self.base}/api/config/local/roles/review?repo={self.root}&t={self.token}",
            REVIEW.encode(), {"Content-Type": "text/plain"}, method="PUT")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)
        self.assertFalse((self.root / ".sstack/local/roles/review.toml").exists())

    def test_api_ade_follows_the_detection_contract(self):
        with mock.patch.dict(os.environ, {"T3CODE_THREAD_ID": "x"}):
            ade = self.get(f"/api/ade?repo={self.root}")
        self.assertEqual((ade["name"], ade["why"], ade["layer"]), ("t3", "env T3CODE_THREAD_ID", "defaults"))
        self.assertEqual(ade["delegate"], "tool delegate_task")
        self.assertEqual(ade["readonly"], "instructed")
        self.assertIn("tool:", ade["browser"])
        self.assertTrue(ade["note"].endswith("defaults/ades/t3.md"))
        with mock.patch.dict(os.environ, {"T3CODE_THREAD_ID": "x", "SSTACK_ADE": "none"}):
            self.assertIsNone(self.get(f"/api/ade?repo={self.root}")["name"])

    def test_runs_are_grouped_newest_first_with_readonly_warning(self):
        shutil.copytree(FIXTURES / "runs", self.root / ".sstack/runs")
        runs = self.get(f"/api/runs?repo={self.root}")["runs"]
        self.assertEqual([r["run_dir"] for r in runs],
                         [".sstack/runs/20261109-1210-implement", ".sstack/runs/20261109-1200-review"])
        self.assertEqual(runs[1]["run"]["members"], ["codex/gpt-6.1-sol", "claude/opus"])
        self.assertEqual(runs[1]["readonly_warning"], ["lib/sstack_config.py", "scratch.txt"])
        self.assertEqual([line["harness"] for line in runs[1]["lines"]], ["codex", "claude"])

    def test_lessons_accept_and_forget(self):
        p = self.write(self.root, ".sstack/lessons.md",
                       "# Lessons\n\n- [pending] seen=1 id=L1 | x\n")
        self.request("POST", "/api/lessons/accept",
                     {"repo": str(self.root), "scope": "repo", "id": "L1"})
        self.assertIn("[accepted]", p.read_text())
        ls = self.get(f"/api/lessons?repo={self.root}")["lessons"]
        self.assertEqual([(l["id"], l["status"], l["scope"]) for l in ls], [("L1", "accepted", "repo")])
        self.request("POST", "/api/lessons/forget",
                     {"repo": str(self.root), "scope": "repo", "id": "L1"})
        self.assertEqual(self.get(f"/api/lessons?repo={self.root}")["lessons"], [])

    def test_config_summary_exposes_effective_values_and_sources(self):
        cfg = self.get(f"/api/config?repo={self.root}")
        self.assertEqual([l["name"] for l in cfg["layers"]], ["defaults", "home", "repo", "local"])
        self.assertEqual(cfg["effective"]["dispatch"]["via"], "auto")
        review = next(t for t in cfg["things"] if t["kind"] == "roles" and t["name"] == "review")
        self.assertEqual(review["source"], "home")
        self.assertEqual(review["label"], "roles/review")

    def test_graph_read_creates_nothing(self):
        self.get(f"/api/graph?repo={self.root}")
        self.assertFalse((self.root / ".code-review-graph").exists())

    # --- round 1 review fixes -------------------------------------------------

    def test_stale_tmp_symlink_cannot_redirect_a_save(self):
        # A planted `<file>.tmp` symlink used to be followed and then renamed into place,
        # which wrote the payload outside the repo and made the config a symlink.
        outside = self.root.parent / "outside.toml"
        outside.write_text("keep me\n")
        d = self.root / ".sstack/local/roles"
        d.mkdir(parents=True)
        (d / "review.toml.tmp").symlink_to(outside)
        self.put("/api/config/local/roles/review", REVIEW)
        self.assertEqual(outside.read_text(), "keep me\n")
        self.assertEqual((d / "review.toml").read_text(), REVIEW)
        self.assertFalse((d / "review.toml").is_symlink())

    def test_a_symlinked_target_is_refused(self):
        outside = self.root.parent / "outside.toml"
        outside.write_text("keep me\n")
        d = self.root / ".sstack/local/roles"
        d.mkdir(parents=True)
        (d / "review.toml").symlink_to(outside)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.put("/api/config/local/roles/review", REVIEW)
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(outside.read_text(), "keep me\n")

    def test_validation_runs_on_a_copy_so_the_live_tree_is_untouched(self):
        # Validation failure must never publish, so no rollback can erase another save.
        self.write(self.root, ".sstack/local/config.toml", "[rules\n")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.put("/api/config/local/roles/review", REVIEW)
        self.assertEqual(cm.exception.code, 400)
        left = sorted(p.relative_to(self.root).as_posix()
                      for p in (self.root / ".sstack/local").rglob("*"))
        self.assertEqual(left, [".sstack/local/config.toml"])

    def test_a_save_leaves_no_temp_files_behind(self):
        self.put("/api/config/local/roles/review", REVIEW)
        names = sorted(p.name for p in (self.root / ".sstack/local/roles").iterdir())
        self.assertEqual(names, ["review.toml"])

    def test_roles_must_resolve_before_they_are_published(self):
        text = 'mode = "single"\nharness = "nope"\nmodel = "x"\n'
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.put("/api/config/local/roles/review", text)
        self.assertEqual(cm.exception.code, 400)
        self.assertIn("unknown harness", cm.exception.read().decode())
        self.assertFalse((self.root / ".sstack/local/roles/review.toml").exists())

    def test_ade_detect_and_delegate_must_be_tables(self):
        for text in ('auto = true\ndetect = "bad"\n', 'delegate = "delegate_task"\n'):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.put("/api/config/local/ades/t3", text)
            self.assertEqual(cm.exception.code, 400, text)
        self.assertFalse((self.root / ".sstack/local/ades/t3.toml").exists())
        self.put("/api/config/local/ades/t3", 'auto = true\n[detect]\nenv = ["MARKER"]\n')
        self.assertTrue((self.root / ".sstack/local/ades/t3.toml").is_file())

    def test_repo_must_be_a_git_root(self):
        sub = self.root / "sub"
        sub.mkdir()
        for repo in (str(sub), str(self.root.parent / "notgit"), str(self.root / "missing")):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get(f"/api/config?repo={urllib.parse.quote(repo)}")
            self.assertEqual(cm.exception.code, 400, repo)

    def test_config_effective_value_excludes_the_thing_tables(self):
        cfg = self.get(f"/api/config?repo={self.root}")
        for table in ("harness", "role", "tier", "project"):
            self.assertNotIn(table, cfg["effective"])
        self.assertIn("dispatch", cfg["effective"])
        thing = next(t for t in cfg["things"] if t["kind"] == "config")
        self.assertNotIn("role", thing["value"])

    def test_a_foreign_host_header_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.request("GET", "/api/repos", content_type=None,
                         headers={"Host": "evil.example"})
        self.assertEqual(cm.exception.code, 403)
        self.assertEqual(self.get("/api/repos")["repos"], [str(self.root)])

    def test_api_ade_carries_the_note_and_the_note_route_is_gone(self):
        with mock.patch.dict(os.environ, {"T3CODE_THREAD_ID": "x"}):
            ade = self.get(f"/api/ade?repo={self.root}")
        self.assertTrue(ade["note"].endswith("defaults/ades/t3.md"))
        self.assertTrue(ade["note_text"].startswith("# t3"))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get(f"/api/ade/note?repo={self.root}")
        self.assertEqual(cm.exception.code, 404)

    def test_overview_and_workflows_routes_are_gone(self):
        for path in ("/api/overview", "/api/workflows"):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get(f"{path}?repo={self.root}")
            self.assertEqual(cm.exception.code, 404, path)
