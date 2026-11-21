"""The decider (lib/sstack_decider.py): settings, flattened choices, and decide(). Never a real model
or network call: `_ask`, `urllib.request.urlopen` and `subprocess.run` are mocked."""
import contextlib, io, json, os, subprocess, sys, unittest
from unittest import mock

import helpers  # noqa: F401  (puts lib/ on sys.path)
import sstack_config as C
import sstack_decider as DC

FAKE = {"headless": [sys.executable, "agent"], "headless_readonly": [sys.executable, "agent", "{model}"]}


def cfg(decider=None):
    return {"harness": {"fake": FAKE, "ghost": {"headless": ["no-such-cli-xyz"]}},
            "rules": {"tier_order": ["cheap", "standard", "strong"]},
            "tier": {"cheap": {"harness": "fake", "model": "cheap", "when": "small edits"},
                     "strong": {"harness": "fake", "model": "strong"},
                     "standard": {"when": "everyday work", "models": [
                         {"id": "default", "harness": "fake", "model": "standard", "when": "most tasks"},
                         {"id": "sonnet", "harness": "fake", "model": "sonnet", "when": "frontend"},
                         {"id": "ghost", "harness": "ghost", "model": "g", "when": "never installed"}]}},
            **({"decider": decider} if decider is not None else {})}


JEV = {"via": "jev"}
OR = {"via": "openrouter", "model": "typesafe/jev-1.14"}


def chat(content: str):
    """A fake urlopen() response holding one OpenRouter chat completion."""
    resp = mock.MagicMock()
    resp.__enter__.return_value.read.return_value = json.dumps(
        {"model": "some/routed-model", "choices": [{"message": {"role": "assistant", "content": content}}]}).encode()
    return resp


def decision(answer=None):
    """A fake urlopen() response holding one Decisions API reply; answer None = no `tier` answer."""
    body = {"id": "d1", "model": "typesafe/jev-1.14-20261014", "provider": "TypeSafe",
            "answers": {} if answer is None else {"tier": answer},
            "usage": {"input_tokens": 381, "output_tokens": 44, "cost": 1.6e-05}}
    return resp(json.dumps(body).encode())


def resp(body: bytes):
    r = mock.MagicMock()
    r.__enter__.return_value.read.return_value = body
    return r


def decide(c, **kw):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        out = DC.decide(c, "the task", "implement", "the plan", ["web/a.tsx"], **kw)
    return out, err.getvalue()


class SettingsTests(unittest.TestCase):
    def test_defaults_heuristic(self):
        self.assertEqual(C.decider({}), {"via": "heuristic", "timeout": 20.0, "min_confidence": 0.5,
                                         "url": None, "model": None, "member": None})

    def test_bad_via_raises(self):
        for bad in ({"via": "rl"}, {"timeout": "x"}, {"timeout": 0}, {"min_confidence": 2},
                    {"via": "llm"}, {"via": "llm", "harness": "ghost"}):
            with self.assertRaises(C.ConfigError, msg=bad):
                C.decider(cfg(bad))

    def test_jev_defaults_to_decisions_api(self):
        s = C.decider(cfg(JEV))
        self.assertEqual((s["url"], s["model"]), ("https://openrouter.ai/api/alpha/decisions", "typesafe/jev-1.14"))
        s = C.decider(cfg({**JEV, "model": "typesafe/jev-2", "url": "https://proxy.test/d"}))
        self.assertEqual((s["url"], s["model"]), ("https://proxy.test/d", "typesafe/jev-2"))
        for bad in ({**JEV, "model": ""}, {**JEV, "model": 3}):
            with self.assertRaises(C.ConfigError, msg=bad):
                C.decider(cfg(bad))

    def test_url_must_be_https_or_localhost(self):
        for url in ("http://jev.test/route", "ftp://jev.test", "jev.test", "http://localhost.evil.test/x"):
            with self.assertRaises(C.ConfigError, msg=url):
                C.decider(cfg({"via": "jev", "url": url}))
        for url in ("https://jev.test/r", "http://localhost:8080/r", "http://127.0.0.1/r"):
            self.assertEqual(C.decider(cfg({"via": "jev", "url": url}))["url"], url)

    def test_key_in_config_ignored(self):
        reply = decision({"type": "choice", "choice": "standard/sonnet", "confidence": 0.9})
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "envkey"}), \
                mock.patch("urllib.request.urlopen", return_value=reply) as u:
            hit, _ = decide(cfg({**JEV, "key": "x"}))
        req = u.call_args.args[0]
        self.assertEqual(req.get_header("Authorization"), "Bearer envkey")
        self.assertNotIn('"x"', req.data.decode())
        self.assertEqual(hit["id"], "sonnet")


    def test_openrouter_needs_model(self):
        for bad in ({"via": "openrouter"}, {"via": "openrouter", "model": ""}, {"via": "openrouter", "model": 3}):
            with self.assertRaises(C.ConfigError, msg=bad):
                C.decider(cfg(bad))
        s = C.decider(cfg(OR))
        self.assertEqual((s["url"], s["model"]), ("https://openrouter.ai/api/v1/chat/completions", "typesafe/jev-1.14"))

    def test_routes_names_jev_model(self):
        import sstack_route as R
        self.assertIn("decider: jev typesafe/jev-1.14 (timeout 20s, min_confidence 0.5)",
                      R.routes_text(cfg(JEV)).splitlines())

    def test_routes_names_openrouter_model(self):
        import sstack_route as R
        self.assertIn("decider: openrouter typesafe/jev-1.14 (timeout 20s, min_confidence 0.5)",
                      R.routes_text(cfg(OR)).splitlines())


class ChoiceTests(unittest.TestCase):
    def test_flattened_lines(self):
        self.assertEqual(DC.lines(DC.choices(cfg())), [
            "cheap/default: small edits",
            "standard/default: most tasks (standard: everyday work)",
            "standard/sonnet: frontend (standard: everyday work)",
            "strong/default:"])

    def test_uninstalled_excluded(self):
        self.assertNotIn("ghost", [e["id"] for e in DC.choices(cfg())])

    def test_tiers_filter(self):
        self.assertEqual([(e["tier"], e["id"]) for e in DC.choices(cfg(), tiers=["standard"])],
                         [("standard", "default"), ("standard", "sonnet")])


class DecideTests(unittest.TestCase):
    def test_heuristic_never_asks(self):
        with mock.patch("sstack_decider._ask", side_effect=AssertionError):
            self.assertIsNone(decide(cfg())[0])
            self.assertIsNone(decide(cfg({"via": "heuristic"}))[0])

    def test_choice_returned(self):
        with mock.patch("sstack_decider._ask", return_value={"choice": "standard/sonnet", "confidence": 0.8}) as ask:
            hit, _ = decide(cfg(JEV))
        self.assertEqual((hit["tier"], hit["id"], hit["model"], hit["confidence"]), ("standard", "sonnet", "sonnet", 0.8))
        payload = ask.call_args.args[-1]
        self.assertEqual(payload["choices"][2], "standard/sonnet: frontend (standard: everyday work)")

    def test_low_confidence_none(self):
        with mock.patch("sstack_decider._ask", return_value={"choice": "standard/sonnet", "confidence": 0.2}):
            hit, err = decide(cfg(JEV))
        self.assertIsNone(hit)
        self.assertIn("heuristic route", err)

    def test_unknown_choice_none(self):
        for choice in ("standard/ghost", "x/y", None):
            with mock.patch("sstack_decider._ask", return_value={"choice": choice, "confidence": 0.99}):
                self.assertIsNone(decide(cfg(JEV))[0], choice)

    def test_timeout_none(self):
        with mock.patch("sstack_decider._ask", side_effect=TimeoutError("timed out")):
            hit, err = decide(cfg(JEV))
        self.assertIsNone(hit)
        self.assertIn("decider jev: timed out; heuristic route", err)

    def test_jev_request_shape(self):
        """The Decisions API wire contract (verified live 2026-11-19 with typesafe/jev-1.14)."""
        reply = decision({"type": "choice", "choice": "cheap/default",
                          "probabilities": {"cheap/default": 0.7, "standard/sonnet": 0.3}, "confidence": 0.7})
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), \
                mock.patch("urllib.request.urlopen", return_value=reply) as u:
            hit, _ = decide(cfg({**JEV, "timeout": 5}))
        req = u.call_args.args[0]
        self.assertEqual((req.full_url, req.get_method()), ("https://openrouter.ai/api/alpha/decisions", "POST"))
        self.assertEqual(req.get_header("Authorization"), "Bearer k")
        self.assertEqual(req.get_header("Content-type"), "application/json")
        body = json.loads(req.data)
        self.assertEqual(set(body), {"model", "state", "questions"})
        self.assertEqual(body["model"], "typesafe/jev-1.14")
        self.assertEqual(body["state"], {"task": "the task", "step": "implement", "files": ["web/a.tsx"],
                                         "plan": "the plan"})
        q = body["questions"]["tier"]
        self.assertEqual((q["type"], q["instructions"]), ("choice", "Which model tier should do this task?"))
        self.assertEqual(q["criteria"]["cheap/default"], "small edits")
        self.assertEqual(q["criteria"]["standard/sonnet"], "frontend (standard: everyday work)")
        self.assertNotIn("standard/ghost", q["criteria"])
        self.assertEqual(u.call_args.kwargs["timeout"], 5.0)
        self.assertEqual((hit["id"], hit["confidence"]), ("default", 0.7))

    def test_jev_confidence_from_probabilities(self):
        reply = decision({"type": "choice", "choice": "strong/default",
                          "probabilities": {"cheap/default": 0.1, "strong/default": 0.9}})
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), \
                mock.patch("urllib.request.urlopen", return_value=reply):
            hit, _ = decide(cfg(JEV))
        self.assertEqual((hit["tier"], hit["confidence"]), ("strong", 0.9))

    def test_jev_failures_fall_back(self):
        import urllib.error
        err_body = io.BytesIO(b'{"error": {"code": 400, "message": "bad model"}}')
        bad = (decision({"type": "refusal"}), decision(None),
               decision({"type": "choice", "choice": "x/y", "confidence": 1}),
               resp(b'{"error": {"code": 500, "message": "boom"}}'), resp(b"not json"),
               urllib.error.HTTPError("u", 400, "Bad Request", {}, err_body), TimeoutError("timed out"))
        for b in bad:
            kw = {"side_effect": b} if isinstance(b, Exception) else {"return_value": b}
            with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), \
                    mock.patch("urllib.request.urlopen", **kw):
                hit, err = decide(cfg(JEV))
            self.assertIsNone(hit, b)
            self.assertIn("decider jev:", err)

    def test_jev_state_stays_compact(self):
        """A long brief and plan are cut so the request stays under Jev's long-context threshold."""
        big = "é" * 40000  # escapes to 6 bytes a character in JSON
        reply = decision({"type": "choice", "choice": "cheap/default", "confidence": 1})
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), \
                mock.patch("urllib.request.urlopen", return_value=reply) as u, \
                contextlib.redirect_stderr(io.StringIO()):
            hit = DC.decide(cfg(JEV), big, "implement", big, ["a.py"])
        data = u.call_args.args[0].data
        self.assertLessEqual(len(data), DC.JEV_MAX_BYTES)
        self.assertTrue(json.loads(data)["state"]["task"].startswith("é"))
        self.assertEqual(hit["id"], "default")

    def test_jev_colon_in_entry_id(self):
        """Criteria keys come from the entries, not from splitting display lines: an id may hold a colon."""
        c = cfg(JEV)
        c["tier"]["standard"]["models"][1]["id"] = "sonnet:fast"
        reply = decision({"type": "choice", "choice": "standard/sonnet:fast", "confidence": 0.9})
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), \
                mock.patch("urllib.request.urlopen", return_value=reply) as u:
            hit, err = decide(c)
        crit = json.loads(u.call_args.args[0].data)["questions"]["tier"]["criteria"]
        self.assertEqual(crit["standard/sonnet:fast"], "frontend (standard: everyday work)")
        self.assertEqual(hit["id"], "sonnet:fast", err)

    def test_jev_cap_keeps_task_and_bounds_files(self):
        """Many files: the task survives, files are cut with a count, and the request fits the cap."""
        files = ["src/" + "x" * 90 + str(i) + ".py" for i in range(350)]
        reply = decision({"type": "choice", "choice": "cheap/default", "confidence": 1})
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), \
                mock.patch("urllib.request.urlopen", return_value=reply) as u, \
                contextlib.redirect_stderr(io.StringIO()):
            hit = DC.decide(cfg(JEV), "Review auth security", "review", "check correctness", files)
        data = u.call_args.args[0].data
        state = json.loads(data)["state"]
        self.assertLessEqual(len(data), DC.JEV_MAX_BYTES)
        self.assertEqual((state["task"], state["plan"]), ("Review auth security", "check correctness"))
        self.assertLess(len(state["files"]), 350)
        self.assertTrue(state["files"][-1].startswith("... "), state["files"][-1])
        self.assertEqual(hit["id"], "default")

    def test_jev_cap_unfittable_falls_back(self):
        """A request that cannot fit even with no files and a short task is not sent."""
        c = cfg(JEV)
        c["tier"]["cheap"]["when"] = "w" * (DC.JEV_MAX_BYTES + 10)
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError) as u:
            hit, err = decide(c)
        self.assertIsNone(hit)
        self.assertFalse(u.called)
        self.assertIn("decider jev:", err)

    def test_jev_propose_none(self):
        """Jev answers the tier question only; a workflow proposal is not asked of it."""
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError) as u, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(DC.propose(cfg(JEV), "plan", ["implement"]))
        self.assertFalse(u.called)

    def test_jev_no_key_none(self):
        env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        env["SSTACK_HOME"] = "/nonexistent-sstack-home"
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError) as u:
            hit, err = decide(cfg(JEV))
        self.assertIsNone(hit)
        self.assertFalse(u.called)
        self.assertIn("OPENROUTER_API_KEY", err)

    def test_confidence_out_of_range_none(self):
        for conf in (float("nan"), 1.5, -0.1, "nan"):
            with mock.patch("sstack_decider._ask", return_value={"choice": "standard/sonnet", "confidence": conf}):
                hit, err = decide(cfg(JEV))
            self.assertIsNone(hit, conf)
            self.assertIn("heuristic route", err)

    def test_openrouter_request_shape(self):
        reply = chat('{"choice": "standard/sonnet", "confidence": 0.8}')
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-key"}), \
                mock.patch("urllib.request.urlopen", return_value=reply) as u:
            hit, _ = decide(cfg({**OR, "timeout": 9}))
        req = u.call_args.args[0]
        self.assertEqual((req.full_url, req.get_method()), ("https://openrouter.ai/api/v1/chat/completions", "POST"))
        self.assertEqual(req.get_header("Authorization"), "Bearer or-key")
        body = json.loads(req.data)
        self.assertEqual(body["model"], "typesafe/jev-1.14")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        user = body["messages"][-1]["content"]
        self.assertIn("standard/sonnet: frontend (standard: everyday work)", user)
        self.assertIn("the task", user)
        self.assertEqual(u.call_args.kwargs["timeout"], 9.0)
        self.assertEqual((hit["id"], hit["confidence"]), ("sonnet", 0.8))

    def test_openrouter_fenced_reply(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), mock.patch(
                "urllib.request.urlopen", return_value=chat('Sure:\n```json\n{"choice": "cheap/default", "confidence": 0.9}\n```')):
            self.assertEqual(decide(cfg(OR))[0]["id"], "default")

    def test_openrouter_no_key_none(self):
        env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        env["SSTACK_HOME"] = "/nonexistent-sstack-home"
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError) as u:
            hit, err = decide(cfg(OR))
        self.assertIsNone(hit)
        self.assertFalse(u.called)
        self.assertIn("OPENROUTER_API_KEY", err)

    def test_key_from_profile_env_file(self):
        """No OPENROUTER_API_KEY in the environment: read it from $SSTACK_HOME/.env (never a repo file)."""
        import tempfile
        with tempfile.TemporaryDirectory() as home:
            with open(os.path.join(home, ".env"), "w") as f:
                f.write('# keys\nOTHER=1\nexport OPENROUTER_API_KEY="file-key"\n')
            env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
            env["SSTACK_HOME"] = home
            with mock.patch.dict(os.environ, env, clear=True), mock.patch(
                    "urllib.request.urlopen", return_value=chat('{"choice": "cheap/default", "confidence": 0.9}')) as u:
                hit, _ = decide(cfg(OR))
            self.assertEqual(u.call_args.args[0].get_header("Authorization"), "Bearer file-key")
            self.assertEqual(hit["id"], "default")
            with mock.patch.dict(os.environ, {**env, "OPENROUTER_API_KEY": "env-key"}, clear=True), mock.patch(
                    "urllib.request.urlopen", return_value=chat('{"choice": "cheap/default", "confidence": 0.9}')) as u:
                decide(cfg(OR))
            self.assertEqual(u.call_args.args[0].get_header("Authorization"), "Bearer env-key")  # env wins

    def test_openrouter_failures_fall_back(self):
        import urllib.error
        bad = (urllib.error.HTTPError("u", 500, "boom", {}, None), TimeoutError("timed out"),
               resp(b"not json"), resp(b'{"choices": []}'), resp(b'{"choices": [{"message": {"content": "no"}}]}'))
        for b in bad:
            kw = {"side_effect": b} if isinstance(b, Exception) else {"return_value": b}
            with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), \
                    mock.patch("urllib.request.urlopen", **kw):
                hit, err = decide(cfg(OR))
            self.assertIsNone(hit, b)
            self.assertIn("decider openrouter:", err)

    def test_llm_parses_last_json_line(self):
        out = ('thinking...\n{"choice": "cheap/default", "confidence": 0.1}\n'
               '{"choice": "standard/sonnet", "confidence": 0.9}\n')
        done = subprocess.CompletedProcess([], 0, stdout=out, stderr="")
        with mock.patch("subprocess.run", return_value=done) as run:
            hit, _ = decide(cfg({"via": "llm", "harness": "fake", "model": "judge", "timeout": 7}))
        self.assertEqual(hit["id"], "sonnet")
        self.assertEqual(run.call_args.args[0], [sys.executable, "agent", "judge"])
        self.assertEqual(run.call_args.kwargs["timeout"], 7.0)
        self.assertIn("standard/sonnet: frontend", run.call_args.kwargs["input"])


if __name__ == "__main__":
    unittest.main()
