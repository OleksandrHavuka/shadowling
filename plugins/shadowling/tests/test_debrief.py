import json
import os
import shutil
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
    if "tags" in props:
        return "triage"
    if "loot" in props:
        return "friction"
    if "words" in props:  # loot.run's LOOT_SCHEMA (enrichment call)
        return "loot"
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

    def _dedup(self):
        # the {category: existing rows} snapshot main reads once and passes in;
        # empty for a fresh test DB, and the fake runner ignores its content anyway
        return {c: [] for c in debrief.CATEGORIES}


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
            (debrief.SPECS["grammar"].schema, Grammar),
            (debrief.SPECS["rephrasing"].schema, Rephrasing),
            (debrief.SPECS["idioms"].schema, Idioms),
            (debrief.SPECS["verbs"].schema, Verbs),
        ]
        for schema, model in cases:
            item = schema["properties"]["findings"]["items"]
            self.assertEqual(item["required"], list(model.insert_cols))
            self.assertEqual(set(item["properties"]), set(model.insert_cols))

    def test_friction_keys_enum_and_loot(self):
        from models.friction import Friction

        friction_schema = debrief.SPECS["friction"].schema
        item = friction_schema["properties"]["findings"]["items"]
        self.assertEqual(item["required"], list(Friction.insert_cols))
        self.assertEqual(
            set(item["properties"]["type"]["enum"]), Friction.enums["type"]
        )
        self.assertIn("loot", friction_schema["properties"])
        self.assertIn("loot", friction_schema["required"])


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

    def test_triage_call_omits_effort(self):
        # triage runs on haiku, which rejects --effort; the flag must not be sent
        self._seed("First normal english sentence here please", "sess-A")
        cfg = core.load_config()
        seen = {}

        def runner(argv, data):
            seen["argv"] = argv
            return _event_array({"tags": [{"id": 1, "langs": ["en"]}]})

        debrief._run_triage("sess-A", cfg, runner=runner)
        self.assertNotIn("--effort", seen["argv"])

    def test_logs_triage_completion_to_stderr(self):
        import io
        from contextlib import redirect_stderr

        self._seed("First normal english sentence here please", "sess-A")
        cfg = core.load_config()
        runner = runner_from({"triage": {"tags": [{"id": 1, "langs": ["en"]}]}})
        buf = io.StringIO()
        with redirect_stderr(buf):
            debrief._run_triage("sess-A", cfg, runner=runner)
        err = buf.getvalue()
        self.assertIn("triage", err)
        self.assertIn("OK", err)  # completion, not just the start line

    def test_logs_triage_error_to_stderr(self):
        import io
        from contextlib import redirect_stderr

        self._seed("First normal english sentence here please", "sess-A")
        cfg = core.load_config()
        runner = runner_from({"triage": "error_result"})
        buf = io.StringIO()
        with redirect_stderr(buf), self.assertRaises(debrief.DebriefError):
            debrief._run_triage("sess-A", cfg, runner=runner)
        self.assertIn("ERROR", buf.getvalue())


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
            name: ("sp", "d", spec.schema, debrief.SONNET)
            for name, spec in debrief.SPECS.items()
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

    def test_specialists_run_at_specialist_effort(self):
        # every specialist call carries --effort SPECIALIST_EFFORT (all are sonnet)
        seen = []

        def runner(argv, data):
            seen.append(argv)
            kind = _schema_kind(argv)
            val = (
                {"findings": [], "loot": []} if kind == "friction" else {"findings": []}
            )
            return _event_array(val)

        debrief._fan_out(self._jobs(), runner=runner)
        self.assertEqual(len(seen), 5)
        for argv in seen:
            self.assertEqual(
                argv[argv.index("--effort") + 1], debrief.SPECIALIST_EFFORT
            )

    def test_streams_per_specialist_progress_to_stderr(self):
        import io
        from contextlib import redirect_stderr

        runner = runner_from(
            {
                "grammar": "error_result",
                "rephrasing": {"findings": []},
                "idioms": {"findings": []},
                "verbs": {"findings": []},
                "friction": {"findings": [], "loot": []},
            }
        )
        buf = io.StringIO()
        with redirect_stderr(buf):
            debrief._fan_out(self._jobs(), runner=runner)
        err = buf.getvalue()
        self.assertIn("grammar", err)
        self.assertIn("ERROR", err)  # grammar failed -> surfaced live
        self.assertIn("rephrasing", err)  # a succeeding specialist is logged too


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

    def test_persists_all_categories_and_mark_in_one_tx(self):
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
        debrief._persist("sess-A", findings)
        self.assertEqual(len(appdb.query("SELECT * FROM grammar")), 1)
        self.assertEqual(len(appdb.query("SELECT * FROM friction")), 1)
        # every persisted finding carries the run's session as provenance
        self.assertEqual(
            appdb.query("SELECT session_id FROM grammar")[0]["session_id"], "sess-A"
        )
        self.assertEqual(
            appdb.query("SELECT session_id FROM friction")[0]["session_id"], "sess-A"
        )
        # _persist no longer writes vocab — enrichment is loot.run's job now
        self.assertEqual(appdb.query("SELECT * FROM vocab"), [])
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
            debrief._persist("sess-A", findings)
        self.assertEqual(appdb.query("SELECT * FROM grammar"), [])
        self.assertIsNone(
            appdb.query("SELECT processed_at FROM messages WHERE id=1")[0][
                "processed_at"
            ]
        )


class EnrichLootTest(DebriefTestBase):
    _GOOD = {
        "word": "deadline",
        "translation": "дедлайн",
        "alt_translations": [],
        "forms": [],
        "lemma": "deadline",
        "examples": ["The deadline is tomorrow."],
        "synonyms": [],
        "definition": "a time limit",
        "ctx": "",
    }

    def test_enrich_loot_writes_vocab_with_examples(self):
        cfg = core.load_config()
        runner = runner_from({"loot": {"words": [self._GOOD]}})
        debrief._enrich_loot(["deadline"], cfg, runner=runner)
        row = appdb.query(
            "SELECT translation, examples FROM vocab WHERE word='deadline'"
        )
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0]["translation"], "дедлайн")
        self.assertEqual(json.loads(row[0]["examples"]), ["The deadline is tomorrow."])

    def test_failed_enrichment_leaves_word_out_of_vocab_and_reports(self):
        import io
        from contextlib import redirect_stdout

        cfg = core.load_config()
        # example has no clozable match -> loot._valid fails -> word stays pending
        bad = {**self._GOOD, "examples": ["no match in this sentence"]}
        runner = runner_from({"loot": {"words": [bad]}})
        buf = io.StringIO()
        with redirect_stdout(buf):
            debrief._enrich_loot(["deadline"], cfg, runner=runner)
        self.assertEqual(appdb.query("SELECT * FROM vocab"), [])  # not written
        out = buf.getvalue()
        self.assertIn("pending", out)
        self.assertIn("deadline", out)

    def test_loot_run_exception_is_caught_and_reported(self):
        import io
        from contextlib import redirect_stdout

        cfg = core.load_config()
        buf = io.StringIO()
        with mock.patch.object(debrief.loot, "run", side_effect=RuntimeError("boom")):
            with redirect_stdout(buf):
                debrief._enrich_loot(["deadline"], cfg, runner=None)
        self.assertIn("failed", buf.getvalue())  # net caught it, did not raise
        self.assertEqual(appdb.query("SELECT * FROM vocab"), [])


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
            "sess-A", cfg, "en", self._dedup(), runner=self._all_success_runner()
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(appdb.query("SELECT * FROM grammar")), 1)
        self.assertEqual(Messages.pending_count(), 0)

    def test_empty_language_session_just_marks(self):
        from models.messages import Messages

        self._seed("суто українське повідомлення без англійської", "sess-A")
        cfg = core.load_config()
        runner = runner_from({"triage": {"tags": [{"id": 1, "langs": ["uk"]}]}})
        result = debrief._run_session("sess-A", cfg, "en", self._dedup(), runner=runner)
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
        result = debrief._run_session("sess-A", cfg, "en", self._dedup(), runner=runner)
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
        result = debrief._run_session("sess-A", cfg, "en", self._dedup(), runner=runner)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], ["triage"])
        self.assertIn("triage", result["errors"])
        self.assertEqual(Messages.pending_count(), 1)

    def test_run_session_returns_loot_words_without_writing_vocab(self):
        self._seed("First normal english sentence here please", "sess-A")
        cfg = core.load_config()
        runner = runner_from(
            {
                "triage": {"tags": [{"id": 1, "langs": ["en"]}]},
                "grammar": {"findings": []},
                "rephrasing": {"findings": []},
                "idioms": {"findings": []},
                "verbs": {"findings": []},
                "friction": {
                    "findings": [],
                    "loot": [{"word": "Deadline", "translation": "дедлайн"}],
                },
            }
        )
        result = debrief._run_session("sess-A", cfg, "en", self._dedup(), runner=runner)
        self.assertTrue(result["ok"])
        self.assertEqual(result["loot"], ["deadline"])  # lowercased + de-duped
        # enrich-only: _run_session does NOT write vocab (main does, via loot.run)
        self.assertEqual(appdb.query("SELECT * FROM vocab"), [])


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
        result = debrief._run_session("sess-A", cfg, "en", self._dedup(), runner=runner)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], ["persist"])
        self.assertEqual(Messages.pending_count(), 1)  # not crashed; still pending


class SummaryTest(DebriefTestBase):
    def test_status_ok_and_empty(self):
        self.assertEqual(
            debrief._session_status(debrief._result("sess-A", ok=True)), "OK"
        )
        self.assertEqual(
            debrief._session_status(debrief._result("sess-A", ok=True, empty=True)),
            "OK (empty)",
        )

    def test_status_error_includes_reason(self):
        r = debrief._result(
            "sess-A",
            ok=False,
            failed=["grammar"],
            errors={"grammar": "claude timed out after 600s"},
        )
        self.assertEqual(
            debrief._session_status(r), "ERROR grammar — claude timed out after 600s"
        )

    def test_totals_line_with_and_without_failures(self):
        ok = [debrief._result("a", ok=True), debrief._result("b", ok=True)]
        self.assertEqual(debrief._totals_line(ok), "2/2 session(s) OK")
        mixed = ok + [debrief._result("c", ok=False, failed=["triage"])]
        self.assertEqual(
            debrief._totals_line(mixed),
            "2/3 session(s) OK; re-run /debrief to retry the 1 failed",
        )


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

    def test_streams_per_session_progress_and_totals(self):
        import io
        from contextlib import redirect_stdout

        self._seed("First normal english sentence here please", "sess-A")
        buf = io.StringIO()
        with redirect_stdout(buf):
            debrief.main(runner=_full_runner())
        out = buf.getvalue()
        self.assertIn("reviewing 1 session(s)", out)
        self.assertRegex(out, r"\[1/1\] sess-A … OK")  # live per-session line
        self.assertIn("1/1 session(s) OK", out)  # closing tally

    def test_streams_error_reason_live(self):
        import io
        from contextlib import redirect_stdout

        self._seed("First normal english sentence here please", "sess-A")
        buf = io.StringIO()
        with redirect_stdout(buf):
            debrief.main(runner=runner_from({"triage": "error_result"}))
        out = buf.getvalue()
        self.assertRegex(out, r"\[1/1\] sess-A … ERROR triage — ")

    def test_friction_loot_words_are_enriched_into_vocab(self):
        from models.messages import Messages

        self._seed("First normal english sentence here please", "sess-A")
        item = {
            "word": "deadline",
            "translation": "дедлайн",
            "alt_translations": [],
            "forms": [],
            "lemma": "deadline",
            "examples": ["The deadline is tomorrow."],
            "synonyms": [],
            "definition": "a time limit",
            "ctx": "",
        }
        runner = runner_from(
            {
                "triage": {"tags": [{"id": 1, "langs": ["en"]}]},
                "grammar": {"findings": []},
                "rephrasing": {"findings": []},
                "idioms": {"findings": []},
                "verbs": {"findings": []},
                "friction": {
                    "findings": [],
                    "loot": [{"word": "deadline", "translation": "дедлайн"}],
                },
                "loot": {"words": [item]},
            }
        )
        code = debrief.main(runner=runner)
        self.assertEqual(code, 0)
        row = appdb.query("SELECT examples FROM vocab WHERE word='deadline'")
        self.assertEqual(json.loads(row[0]["examples"]), ["The deadline is tomorrow."])
        self.assertEqual(Messages.pending_count(), 0)

    def test_no_friction_loot_skips_loot_run(self):
        self._seed("First normal english sentence here please", "sess-A")
        with mock.patch.object(debrief.loot, "run") as m:
            code = debrief.main(runner=_full_runner())  # _full_runner's loot is []
        self.assertEqual(code, 0)
        m.assert_not_called()


class SessionIsolationTest(DebriefTestBase):
    def test_unexpected_error_becomes_one_failed_session(self):
        def boom(argv, data):
            raise RuntimeError("kaboom")  # NOT a DebriefError

        self._seed("First normal english sentence here please", "sess-A")
        cfg = core.load_config()
        result = debrief._run_session_safe(
            "sess-A", cfg, "en", self._dedup(), runner=boom
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], ["unexpected"])
        self.assertIn("RuntimeError", result["errors"]["unexpected"])

    def test_main_survives_unexpected_error_across_sessions(self):
        # a non-DebriefError in every session must not abort the whole run
        def boom(argv, data):
            raise RuntimeError("kaboom")

        self._seed("First normal english sentence here please", "sess-A")
        self._seed("Second perfectly fine english sentence now", "sess-B")
        code = debrief.main(runner=boom)
        self.assertEqual(code, 1)  # failures -> exit 1, but main completed


class DedupSnapshotTest(DebriefTestBase):
    def test_snapshot_read_once_across_nonwriting_sessions(self):
        from models.grammar import Grammar

        self._seed("a first fine english sentence here please", "sess-A")
        self._seed("a second fine english sentence here please", "sess-B")
        runner = runner_from({"triage": "error_result"})  # neither session persists
        with mock.patch.object(Grammar, "select", wraps=Grammar.select) as spy:
            debrief.main(runner=runner)
        self.assertEqual(
            spy.call_count, 1
        )  # snapshot read ONCE, reused across sessions


class ConfigBlockTest(DebriefTestBase):
    def test_debrief_uses_shared_config_block(self):
        import config

        cfg = core.load_config()
        expected = config.config_block(cfg)
        self.assertTrue(expected.startswith("<config>"))
        self.assertEqual(debrief._config_block(cfg), expected)


class MessagesBlockTest(DebriefTestBase):
    def test_wraps_render_in_messages_tag(self):
        rows = [{"id": 1, "text": "hi there friend", "langs": '["en"]'}]
        block = debrief._messages_block(rows, ["id", "text"])
        self.assertTrue(block.startswith("<messages>"))
        self.assertTrue(block.endswith("</messages>"))
        self.assertIn("hi there friend", block)


if __name__ == "__main__":
    unittest.main()
