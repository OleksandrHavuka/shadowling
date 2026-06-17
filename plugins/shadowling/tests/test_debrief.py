import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import appdb
import core
import debrief


def _event_array(structured_output, subtype="success", is_error=False):
    """Build a claude `--output-format json` stdout: a JSON array of event
    objects ending in a `result` event (the only one the parser reads)."""
    return json.dumps(
        [
            {"type": "system", "subtype": "init", "session_id": "x"},
            {
                "type": "result",
                "subtype": subtype,
                "is_error": is_error,
                "result": "",
                "structured_output": structured_output,
            },
        ]
    )


def _schema_kind(argv):
    """Classify a built claude argv by its --json-schema so a fake runner can
    return the right canned output. Each specialist's schema has a unique marker."""
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    props = schema["properties"]
    if "code" in props:
        return "lang_code"
    if "tags" in props:
        return "triage"
    if "loot" in props:
        return "friction"
    item = props["findings"]["items"]["properties"]
    for kind, marker in (
        ("idioms", "idiom"),
        ("verbs", "verb"),
        ("grammar", "rule"),
        ("rephrasing", "why"),
    ):
        if marker in item:
            return kind
    raise AssertionError("unrecognized schema in argv")


def runner_from(by_kind):
    """Thread-safe fake runner. by_kind maps a kind -> structured_output dict, OR
    the literal "error_result" to emit an is_error result (-> DebriefError)."""

    def runner(argv, data):
        kind = _schema_kind(argv)
        val = by_kind[kind]
        if val == "error_result":
            return _event_array({}, subtype="error_max_turns", is_error=True)
        return _event_array(val)

    return runner


class DebriefTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home
        core.save_config(
            {
                "first_language": "Ukrainian",
                "learning_language": "English",
                "explanation_language": "English",
            }
        )

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _seed(self, text, session="sess-A"):
        con = appdb.connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO messages(created_at, text, session_id)"
                    " VALUES ('t', ?, ?)",
                    (text, session),
                )
        finally:
            con.close()


TRIVIAL_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {}}


class ParseResultTest(DebriefTestBase):
    def test_success_returns_structured_output(self):
        out = debrief._parse_result(_event_array({"code": "en"}))
        self.assertEqual(out, {"code": "en"})

    def test_error_max_turns_raises(self):
        with self.assertRaises(debrief.DebriefError):
            debrief._parse_result(
                _event_array({}, subtype="error_max_turns", is_error=True)
            )

    def test_is_error_true_raises_even_if_success_subtype(self):
        with self.assertRaises(debrief.DebriefError):
            debrief._parse_result(_event_array({"code": "en"}, is_error=True))

    def test_non_json_raises(self):
        with self.assertRaises(debrief.DebriefError):
            debrief._parse_result("not json at all")

    def test_no_result_event_raises(self):
        with self.assertRaises(debrief.DebriefError):
            debrief._parse_result(json.dumps([{"type": "system"}]))

    def test_missing_structured_output_raises(self):
        with self.assertRaises(debrief.DebriefError):
            debrief._parse_result(
                json.dumps(
                    [{"type": "result", "subtype": "success", "is_error": False}]
                )
            )

    def test_takes_last_result_event(self):
        events = json.dumps(
            [
                {"type": "result", "subtype": "error", "is_error": True},
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "structured_output": {"code": "en"},
                },
            ]
        )
        self.assertEqual(debrief._parse_result(events), {"code": "en"})


class RunClaudeTest(DebriefTestBase):
    def test_builds_expected_argv_and_returns_output(self):
        seen = {}

        def runner(argv, data):
            seen["argv"] = argv
            seen["data"] = data
            return _event_array({"code": "en"})

        out = debrief._run_claude(
            "the role", "the data", TRIVIAL_SCHEMA, "claude-haiku-4-5", runner=runner
        )
        self.assertEqual(out, {"code": "en"})
        self.assertEqual(seen["data"], "the data")
        argv = seen["argv"]
        self.assertEqual(argv[0], "claude")
        self.assertIn("--safe-mode", argv)
        self.assertIn("--tools", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(argv[argv.index("--max-turns") + 1], "4")
        self.assertEqual(argv[argv.index("--model") + 1], "claude-haiku-4-5")
        self.assertEqual(argv[argv.index("--system-prompt") + 1], "the role")
        self.assertEqual(
            json.loads(argv[argv.index("--json-schema") + 1]), TRIVIAL_SCHEMA
        )

    def test_missing_claude_binary_raises(self):
        with mock.patch("debrief.shutil.which", return_value=None):
            with self.assertRaises(debrief.DebriefError):
                debrief._run_claude("r", "d", TRIVIAL_SCHEMA, "claude-haiku-4-5")

    def test_timeout_maps_to_debrief_error(self):
        def boom(argv, data):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

        with self.assertRaises(debrief.DebriefError):
            debrief._run_claude(
                "r", "d", TRIVIAL_SCHEMA, "claude-haiku-4-5", runner=boom
            )


class PromptFilesTest(DebriefTestBase):
    def test_every_prompt_file_loads_and_is_nonempty(self):
        for name in ("triage", "grammar", "rephrasing", "idioms", "verbs", "friction"):
            self.assertTrue(debrief._prompt(name).strip(), name)


class ResolveLearningCodeTest(DebriefTestBase):
    def test_resolves_name_to_code(self):
        cfg = core.load_config()
        runner = runner_from({"lang_code": {"code": "EN"}})
        self.assertEqual(debrief._resolve_learning_code(cfg, runner=runner), "en")

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def runner(argv, data):
            calls["n"] += 1
            if calls["n"] == 1:
                return _event_array({"code": "not-a-code-123"})
            return _event_array({"code": "en"})

        cfg = core.load_config()
        self.assertEqual(debrief._resolve_learning_code(cfg, runner=runner), "en")
        self.assertEqual(calls["n"], 2)

    def test_gives_up_after_attempts(self):
        cfg = core.load_config()
        runner = runner_from({"lang_code": {"code": "garbage value"}})
        with self.assertRaises(debrief.DebriefError):
            debrief._resolve_learning_code(cfg, runner=runner)


if __name__ == "__main__":
    unittest.main()
