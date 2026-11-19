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


JEV = {"via": "jev", "url": "http://jev.test/route"}
OR = {"via": "openrouter", "model": "typesafe/jev-router"}


def chat(content: str):
    """A fake urlopen() response holding one OpenRouter chat completion."""
    resp = mock.MagicMock()
    resp.__enter__.return_value.read.return_value = json.dumps(
        {"model": "some/routed-model", "choices": [{"message": {"role": "assistant", "content": content}}]}).encode()
    return resp


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

    def test_jev_needs_url(self):
        with self.assertRaises(C.ConfigError):
            C.decider(cfg({"via": "jev"}))
        self.assertEqual(C.decider(cfg(JEV))["url"], JEV["url"])

    def test_key_in_config_ignored(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b'{"choice": "standard/sonnet", "confidence": 0.9}'
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "envkey"}), \
                mock.patch("urllib.request.urlopen", return_value=resp) as u:
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
        self.assertEqual((s["url"], s["model"]), ("https://openrouter.ai/api/v1/chat/completions", "typesafe/jev-router"))

    def test_routes_names_openrouter_model(self):
        import sstack_route as R
        self.assertIn("decider: openrouter typesafe/jev-router (timeout 20s, min_confidence 0.5)",
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
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b'{"choice": "cheap/default", "confidence": 0.7}'
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "k"}), \
                mock.patch("urllib.request.urlopen", return_value=resp) as u:
            hit, _ = decide(cfg({**JEV, "timeout": 5}))
        req = u.call_args.args[0]
        self.assertEqual((req.full_url, req.get_method()), (JEV["url"], "POST"))
        self.assertEqual(req.get_header("Authorization"), "Bearer k")
        body = json.loads(req.data)
        self.assertEqual((body["task"], body["step"], body["plan"], body["files"]),
                         ("the task", "implement", "the plan", ["web/a.tsx"]))
        self.assertIn("cheap/default: small edits", body["choices"])
        self.assertEqual(u.call_args.kwargs["timeout"], 5.0)
        self.assertEqual(hit["id"], "default")

    def test_jev_no_key_none(self):
        env = {k: v for k, v in os.environ.items() if k != "JEV_API_KEY"}
        env["SSTACK_HOME"] = "/nonexistent-sstack-home"
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError) as u:
            hit, err = decide(cfg(JEV))
        self.assertIsNone(hit)
        self.assertFalse(u.called)
        self.assertIn("JEV_API_KEY", err)

    def test_openrouter_request_shape(self):
        reply = chat('{"choice": "standard/sonnet", "confidence": 0.8}')
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-key"}), \
                mock.patch("urllib.request.urlopen", return_value=reply) as u:
            hit, _ = decide(cfg({**OR, "timeout": 9}))
        req = u.call_args.args[0]
        self.assertEqual((req.full_url, req.get_method()), ("https://openrouter.ai/api/v1/chat/completions", "POST"))
        self.assertEqual(req.get_header("Authorization"), "Bearer or-key")
        body = json.loads(req.data)
        self.assertEqual(body["model"], "typesafe/jev-router")
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
