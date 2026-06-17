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
        cfg = core.load_config()  # learning_language == "English"
        self.assertEqual(debrief._resolve_learning_code(cfg), "en")

    def test_unknown_language_raises(self):
        cfg = core.load_config()
        cfg["learning_language"] = "Klingon"
        with self.assertRaises(debrief.DebriefError):
            debrief._resolve_learning_code(cfg)


class ValidateTriageTest(DebriefTestBase):
    def test_good_tags_reshaped_for_messages_tag(self):
        rows = [{"id": 1, "langs": ["en"]}, {"id": 2, "langs": ["en", "uk"]}]
        clean = debrief._validate_triage(rows, {1, 2})
        self.assertEqual(clean, [{"id": 1, "langs": "en"}, {"id": 2, "langs": "en,uk"}])

    def test_und_passes_through(self):
        clean = debrief._validate_triage([{"id": 1, "langs": ["und"]}], {1})
        self.assertEqual(clean, [{"id": 1, "langs": "und"}])

    def test_unknown_id_raises(self):
        with self.assertRaises(debrief.DebriefError):
            debrief._validate_triage([{"id": 999, "langs": ["en"]}], {1})

    def test_missing_id_raises(self):
        with self.assertRaises(debrief.DebriefError):
            debrief._validate_triage([{"id": 1, "langs": ["en"]}], {1, 2})


class TriageSchemaTest(DebriefTestBase):
    def test_langs_is_nonempty_enum_from_langcodes(self):
        import langcodes

        langs = debrief.TRIAGE_SCHEMA["properties"]["tags"]["items"]["properties"][
            "langs"
        ]
        self.assertEqual(langs["minItems"], 1)
        self.assertEqual(set(langs["items"]["enum"]), set(langcodes.CODES))


class SchemaContractTest(DebriefTestBase):
    def test_findings_keys_equal_insert_cols(self):
        from models.grammar import Grammar
        from models.idioms import Idioms
        from models.rephrasing import Rephrasing
        from models.verbs import Verbs

        cases = [
            (debrief.GRAMMAR_SCHEMA, Grammar),
            (debrief.REPHRASING_SCHEMA, Rephrasing),
            (debrief.IDIOMS_SCHEMA, Idioms),
            (debrief.VERBS_SCHEMA, Verbs),
        ]
        for schema, model in cases:
            item = schema["properties"]["findings"]["items"]
            self.assertEqual(item["required"], list(model.insert_cols))
            self.assertEqual(set(item["properties"]), set(model.insert_cols))

    def test_friction_keys_enum_and_loot(self):
        from models.friction import Friction

        item = debrief.FRICTION_SCHEMA["properties"]["findings"]["items"]
        self.assertEqual(item["required"], list(Friction.insert_cols))
        self.assertEqual(
            set(item["properties"]["type"]["enum"]), Friction.enums["type"]
        )
        self.assertIn("loot", debrief.FRICTION_SCHEMA["properties"])
        self.assertIn("loot", debrief.FRICTION_SCHEMA["required"])


class RunTriageTest(DebriefTestBase):
    def test_loop_tags_then_stops(self):
        from models.messages import Messages

        self._seed("First normal english sentence here please", "sess-A")
        self._seed("друге повідомлення суто українською мовою", "sess-A")
        cfg = core.load_config()
        runner = runner_from(
            {
                "triage": {
                    "tags": [{"id": 1, "langs": ["en"]}, {"id": 2, "langs": ["uk"]}]
                }
            }
        )
        debrief._run_triage("sess-A", cfg, runner=runner)
        rows = appdb.query("SELECT langs FROM messages ORDER BY id")
        self.assertEqual(rows[0]["langs"], '["en"]')
        self.assertEqual(rows[1]["langs"], '["uk"]')
        # second call would re-list nothing untagged -> no claude call needed
        self.assertEqual(Messages.list(session="sess-A", untagged=True), [])

    def test_failed_triage_call_raises_and_tags_nothing(self):
        self._seed("First normal english sentence here please", "sess-A")
        cfg = core.load_config()
        runner = runner_from({"triage": "error_result"})
        with self.assertRaises(debrief.DebriefError):
            debrief._run_triage("sess-A", cfg, runner=runner)
        self.assertIsNone(appdb.query("SELECT langs FROM messages")[0]["langs"])


class BuildJobsTest(DebriefTestBase):
    def _jobs(self):
        cfg = core.load_config()
        lang_slice = [{"id": 1, "text": "I has went", "langs": '["en"]'}]
        full_slice = [
            {"id": 1, "text": "I has went", "langs": '["en"]'},
            {"id": 2, "text": "ну таке", "langs": '["uk"]'},
        ]
        dedup = {
            k: [] for k in ("grammar", "rephrasing", "idioms", "verbs", "friction")
        }
        return debrief._build_jobs(cfg, "en", lang_slice, full_slice, dedup)

    def test_has_all_five_specialists(self):
        self.assertEqual(
            set(self._jobs()),
            {"grammar", "rephrasing", "idioms", "verbs", "friction"},
        )

    def test_grammar_job_carries_config_and_lang_slice_and_dedup(self):
        _sp, data, _schema, model = self._jobs()["grammar"]
        self.assertEqual(model, debrief.SONNET)
        self.assertIn("<config>", data)
        self.assertIn("I has went", data)
        self.assertIn("<grammar>", data)

    def test_friction_job_has_learning_code_and_full_timeline(self):
        _sp, data, _schema, _model = self._jobs()["friction"]
        self.assertIn("<learning_code>en</learning_code>", data)
        self.assertIn("ну таке", data)  # native-language row from the full timeline
        self.assertIn("<grammar>", data)  # cross-correlation dedup


class FanOutTest(DebriefTestBase):
    def _jobs(self):
        return {
            "grammar": ("sp", "d", debrief.GRAMMAR_SCHEMA, debrief.SONNET),
            "rephrasing": ("sp", "d", debrief.REPHRASING_SCHEMA, debrief.SONNET),
            "idioms": ("sp", "d", debrief.IDIOMS_SCHEMA, debrief.SONNET),
            "verbs": ("sp", "d", debrief.VERBS_SCHEMA, debrief.SONNET),
            "friction": ("sp", "d", debrief.FRICTION_SCHEMA, debrief.SONNET),
        }

    def test_all_succeed(self):
        runner = runner_from(
            {
                "grammar": {"findings": []},
                "rephrasing": {"findings": []},
                "idioms": {"findings": []},
                "verbs": {"findings": []},
                "friction": {"findings": [], "loot": []},
            }
        )
        findings, failed = debrief._fan_out(self._jobs(), runner=runner)
        self.assertEqual(failed, {})
        self.assertEqual(
            set(findings), {"grammar", "rephrasing", "idioms", "verbs", "friction"}
        )

    def test_one_failure_is_reported(self):
        runner = runner_from(
            {
                "grammar": "error_result",
                "rephrasing": {"findings": []},
                "idioms": {"findings": []},
                "verbs": {"findings": []},
                "friction": {"findings": [], "loot": []},
            }
        )
        findings, failed = debrief._fan_out(self._jobs(), runner=runner)
        self.assertIn("grammar", failed)
        self.assertTrue(failed["grammar"])  # carries a reason
        self.assertNotIn("grammar", findings)


def _findings(grammar=(), rephrasing=(), idioms=(), verbs=(), friction=()):
    return {
        "grammar": list(grammar),
        "rephrasing": list(rephrasing),
        "idioms": list(idioms),
        "verbs": list(verbs),
        "friction": list(friction),
    }


class PersistTest(DebriefTestBase):
    def setUp(self):
        super().setUp()
        self._seed("First normal english sentence here please", "sess-A")
        from models.messages import Messages

        Messages.tag([{"id": "1", "langs": "en"}])

    def test_persists_all_categories_loot_and_mark_in_one_tx(self):
        findings = _findings(
            grammar=[
                {
                    "slug": "art",
                    "problem": "p",
                    "original": "a",
                    "fixed": "b",
                    "rule": "r",
                }
            ],
            friction=[
                {
                    "slug": "z",
                    "type": "register",
                    "zone": "zn",
                    "learner_wrote": "lw",
                    "native_phrase": "np",
                    "context": "c",
                }
            ],
        )
        debrief._persist(
            "sess-A", findings, [{"word": "hello", "translation": "привіт"}]
        )
        self.assertEqual(len(appdb.query("SELECT * FROM grammar")), 1)
        self.assertEqual(len(appdb.query("SELECT * FROM friction")), 1)
        self.assertEqual(
            appdb.query("SELECT translation FROM vocab WHERE word='hello'")[0][
                "translation"
            ],
            "привіт",
        )
        self.assertIsNotNone(
            appdb.query("SELECT processed_at FROM messages WHERE id=1")[0][
                "processed_at"
            ]
        )

    def test_bad_finding_rolls_everything_back_and_leaves_session_pending(self):
        findings = _findings(
            grammar=[
                {
                    "slug": "art",
                    "problem": "p",
                    "original": "a",
                    "fixed": "b",
                    "rule": "r",
                }
            ],
            friction=[
                {
                    "slug": "z",
                    "type": "bogus",
                    "zone": "zn",
                    "learner_wrote": "lw",
                    "native_phrase": "np",
                    "context": "c",
                }
            ],
        )
        with self.assertRaises(ValueError):
            debrief._persist("sess-A", findings, [])
        self.assertEqual(appdb.query("SELECT * FROM grammar"), [])
        self.assertIsNone(
            appdb.query("SELECT processed_at FROM messages WHERE id=1")[0][
                "processed_at"
            ]
        )


class RunSessionTest(DebriefTestBase):
    def _all_success_runner(self):
        return runner_from(
            {
                "triage": {"tags": [{"id": 1, "langs": ["en"]}]},
                "grammar": {
                    "findings": [
                        {
                            "slug": "art",
                            "problem": "p",
                            "original": "a",
                            "fixed": "b",
                            "rule": "r",
                        }
                    ]
                },
                "rephrasing": {"findings": []},
                "idioms": {"findings": []},
                "verbs": {"findings": []},
                "friction": {"findings": [], "loot": []},
            }
        )

    def test_full_session_tags_persists_and_marks(self):
        from models.messages import Messages

        self._seed("First normal english sentence here please", "sess-A")
        cfg = core.load_config()
        result = debrief._run_session(
            "sess-A", cfg, "en", runner=self._all_success_runner()
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(appdb.query("SELECT * FROM grammar")), 1)
        self.assertEqual(Messages.pending_count(), 0)

    def test_empty_language_session_just_marks(self):
        from models.messages import Messages

        self._seed("суто українське повідомлення без англійської", "sess-A")
        cfg = core.load_config()
        runner = runner_from({"triage": {"tags": [{"id": 1, "langs": ["uk"]}]}})
        result = debrief._run_session("sess-A", cfg, "en", runner=runner)
        self.assertTrue(result["ok"])
        self.assertTrue(result["empty"])
        self.assertEqual(appdb.query("SELECT * FROM grammar"), [])
        self.assertEqual(Messages.pending_count(), 0)  # tagged row marked, not pending

    def test_specialist_failure_persists_nothing_and_leaves_pending(self):
        from models.messages import Messages

        self._seed("First normal english sentence here please", "sess-A")
        cfg = core.load_config()
        runner = runner_from(
            {
                "triage": {"tags": [{"id": 1, "langs": ["en"]}]},
                "grammar": "error_result",
                "rephrasing": {"findings": []},
                "idioms": {"findings": []},
                "verbs": {"findings": []},
                "friction": {"findings": [], "loot": []},
            }
        )
        result = debrief._run_session("sess-A", cfg, "en", runner=runner)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], ["grammar"])
        self.assertIn("grammar", result["errors"])
        self.assertEqual(appdb.query("SELECT * FROM grammar"), [])
        self.assertEqual(Messages.pending_count(), 1)  # tagged but unprocessed -> retry

    def test_triage_failure_leaves_session_pending(self):
        from models.messages import Messages

        self._seed("First normal english sentence here please", "sess-A")
        cfg = core.load_config()
        runner = runner_from({"triage": "error_result"})
        result = debrief._run_session("sess-A", cfg, "en", runner=runner)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], ["triage"])
        self.assertIn("triage", result["errors"])
        self.assertEqual(Messages.pending_count(), 1)


class MalformedResultTest(DebriefTestBase):
    def test_missing_findings_key_fails_one_session_not_the_run(self):
        from models.messages import Messages

        self._seed("First normal english sentence here please", "sess-A")
        cfg = core.load_config()
        # grammar returns a schema-shaped-but-missing-'findings' object
        runner = runner_from(
            {
                "triage": {"tags": [{"id": 1, "langs": ["en"]}]},
                "grammar": {},  # no "findings" key -> KeyError in extraction
                "rephrasing": {"findings": []},
                "idioms": {"findings": []},
                "verbs": {"findings": []},
                "friction": {"findings": [], "loot": []},
            }
        )
        result = debrief._run_session("sess-A", cfg, "en", runner=runner)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], ["persist"])
        self.assertEqual(Messages.pending_count(), 1)  # not crashed; still pending


class SummaryTest(DebriefTestBase):
    def test_error_line_includes_reason(self):
        import io
        from contextlib import redirect_stdout

        results = [
            debrief._result(
                "sess-A",
                ok=False,
                failed=["grammar"],
                errors={"grammar": "claude timed out after 180s"},
            )
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            debrief._print_summary(0, results)
        self.assertIn("grammar — claude timed out after 180s", buf.getvalue())


def _full_runner():
    return runner_from(
        {
            "triage": {"tags": [{"id": 1, "langs": ["en"]}]},
            "grammar": {
                "findings": [
                    {
                        "slug": "art",
                        "problem": "p",
                        "original": "a",
                        "fixed": "b",
                        "rule": "r",
                    }
                ]
            },
            "rephrasing": {"findings": []},
            "idioms": {"findings": []},
            "verbs": {"findings": []},
            "friction": {"findings": [], "loot": []},
        }
    )


class MainTest(DebriefTestBase):
    def test_no_sessions_exits_zero(self):
        runner = runner_from({})
        self.assertEqual(debrief.main(runner=runner), 0)

    def test_unconfigured_exits_one(self):
        os.remove(os.path.join(self.home, "config.json"))
        self.assertEqual(debrief.main(runner=runner_from({})), 1)

    def test_full_run_tags_persists_marks_and_exits_zero(self):
        from models.messages import Messages

        self._seed("First normal english sentence here please", "sess-A")
        code = debrief.main(runner=_full_runner())
        self.assertEqual(code, 0)
        self.assertEqual(len(appdb.query("SELECT * FROM grammar")), 1)
        self.assertEqual(Messages.pending_count(), 0)

    def test_failed_session_exits_one_and_leaves_pending(self):
        from models.messages import Messages

        self._seed("First normal english sentence here please", "sess-A")
        runner = runner_from({"triage": "error_result"})
        code = debrief.main(runner=runner)
        self.assertEqual(code, 1)
        self.assertEqual(Messages.pending_count(), 1)


if __name__ == "__main__":
    unittest.main()
