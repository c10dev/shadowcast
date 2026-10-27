"""Runner tests without a model: gold and baseline, the cache, and the backends with a fake client."""

import importlib.util
import io
import json
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from shadowcast import __main__ as cli
from shadowcast import backends, prompts, runner


def has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:  # the parent package is missing
        return False


def run(*argv):
    with redirect_stdout(io.StringIO()):
        return cli.main(["run", *argv])


def last_report(folder):
    return json.loads(sorted(Path(folder).glob("run-v2-*.json"))[-1].read_text(encoding="utf-8"))


class GoldAndBaseline(unittest.TestCase):
    def test_gold_scores_one(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run("--backend", "gold", "--results", d), 0)
            for cond, res in last_report(d)["conditions"].items():
                m = res["metrics"]
                self.assertEqual((m["accuracy"], m["localization"], m["rule_accuracy"]), (1.0, 1.0, 1.0), cond)
            self.assertTrue(all(v == 1.0 for v in last_report(d)["conditions"]["C"]["metrics"]["extraction"].values()))

    def test_baseline_finds_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            run("--backend", "baseline", "--results", d, "--conditions", "A")
            m = last_report(d)["conditions"]["A"]["metrics"]
            self.assertEqual((m["recall"], m["false_alarm_rate"]), (0.0, 0.0))
            self.assertAlmostEqual(m["accuracy"], m["always_no_error_accuracy"])

    def test_limit_and_cache(self):
        with tempfile.TemporaryDirectory() as d:
            run("--backend", "gold", "--results", d, "--limit", "1")
            first = sorted(p.name for p in (Path(d) / "cache").iterdir())
            self.assertEqual(last_report(d)["conditions"]["A"]["metrics"]["n"], 3)  # p01: clean + 2 errors
            run("--backend", "gold", "--results", d, "--limit", "1")
            self.assertEqual(sorted(p.name for p in (Path(d) / "cache").iterdir()), first)  # read from the cache


class ExtractionScoring(unittest.TestCase):
    def test_a_malformed_event_is_not_a_found_error(self):
        from shadowcast import scenes
        item = scenes.expand(scenes.load(runner.DEFAULT_DATA[0])[0])[0]  # p01-clean
        out = {"sentences": [{"index": i, "events": []} for i in range(len(item["sentences"]))]}
        out["sentences"][0]["events"] = [prompts.flatten({"type": "turn", "character": "서윤"})]
        fake = types.SimpleNamespace(call=lambda *a: (out, {}))
        args = types.SimpleNamespace(backend="fake", model="m", effort="medium")
        with tempfile.TemporaryDirectory() as d:
            pred = runner.predict(args, fake, item, "C", Path(d))
        self.assertFalse(pred["has_error"])
        self.assertEqual(len(pred["bad_events"]), 1)


class FakeBackends(unittest.TestCase):
    """call() on each backend with a fake client: no network."""

    @unittest.skipUnless(has_module("google.genai"), "google-genai is not installed")
    def test_gemini_call(self):
        sent = {}

        class Models:
            def generate_content(self, model, contents, config):
                sent["schema"] = config.response_json_schema
                u = types.SimpleNamespace(prompt_token_count=10, candidates_token_count=2, thoughts_token_count=None)
                return types.SimpleNamespace(text='{"has_error": false, "sentences": [], "rule": "none", "reason": ""}',
                                             candidates=[], usage_metadata=u, model_version="gemini-fake")

        import os
        old = {k: os.environ.pop(k, None) for k in ("GOOGLE_APPLICATION_CREDENTIALS",)}
        os.environ["GEMINI_API_KEY"] = os.environ.get("GEMINI_API_KEY") or "dummy"
        try:
            b = backends.GeminiBackend(None)
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v
        b.client = types.SimpleNamespace(models=Models())
        out, meta = b.call(prompts.JUDGE_SYSTEM, "x", prompts.EXTRACT_SCHEMA)
        self.assertEqual(out["rule"], "none")
        self.assertEqual(meta["usage"], {"input": 10, "output": 2, "thinking": None})
        self.assertNotIn("additionalProperties", json.dumps(sent["schema"]))

    @unittest.skipUnless(has_module("anthropic"), "anthropic is not installed")
    def test_anthropic_call_records_usage(self):
        class Messages:
            def create(self, **kw):
                return types.SimpleNamespace(
                    stop_reason="end_turn", stop_details=None, model=kw["model"], _request_id="req_x",
                    content=[types.SimpleNamespace(type="text", text='{"sentences": []}')],
                    usage=types.SimpleNamespace(input_tokens=7, output_tokens=3))

        b = backends.AnthropicBackend.__new__(backends.AnthropicBackend)
        b.model, b.effort = "claude-haiku-5-5", "medium"
        b.client = types.SimpleNamespace(messages=Messages())
        out, meta = b.call("s", "u", prompts.EXTRACT_SCHEMA)
        self.assertEqual((out, meta["usage"]), ({"sentences": []}, {"input": 7, "output": 3}))


class Env(unittest.TestCase):
    def test_shell_wins_over_file(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / ".env"
            f.write_text("SC_TEST_A=file\nexport SC_TEST_B='quoted'\n# comment\n", encoding="utf-8")
            os.environ["SC_TEST_A"] = "shell"
            try:
                self.assertEqual(runner.load_env([f]), ["SC_TEST_B"])
                self.assertEqual((os.environ["SC_TEST_A"], os.environ["SC_TEST_B"]), ("shell", "quoted"))
            finally:
                os.environ.pop("SC_TEST_A", None)
                os.environ.pop("SC_TEST_B", None)


if __name__ == "__main__":
    unittest.main()
