import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest

# tests/ lives one level under the plugin root; go up two to reach it.
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(relpath, name):
    """Load a skill-dir entrypoint module by file path (it is not importable as a
    package). Module load runs only top-level `import json/os/sys` — safe, no DB."""
    path = os.path.join(PLUGIN_ROOT, "skills", relpath)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DECODE = load("aha/decode.py", "ep_decode")
GRAMMAR = load("debrief-grammar/grammar.py", "ep_grammar")
REPHRASING = load("debrief-rephrasing/rephrasing.py", "ep_rephrasing")
IDIOMS = load("debrief-idioms/idioms.py", "ep_idioms")
VERBS = load("debrief-verbs/verbs.py", "ep_verbs")
FRICTION = load("debrief-friction/friction.py", "ep_friction")


def run_main(mod, argv, stdin_text=""):
    """Call mod.main(argv) with stdin_text on the GLOBAL sys.stdin (which
    tagio.read_fields reads). Returns (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old = sys.stdin
    sys.stdin = io.StringIO(stdin_text)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mod.main(argv)
    finally:
        sys.stdin = old
    return code, out.getvalue(), err.getvalue()


def tags(**fields):
    return "".join(f"<{k}>{v}</{k}>" for k, v in fields.items())


def items(*pairs):
    body = "\n".join(f"{w}\t{t}" for w, t in pairs)
    return "<items>\n" + body + "\n</items>"


class EntrypointBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)


class DecodeTest(EntrypointBase):
    def test_record(self):
        code, out, _ = run_main(
            DECODE,
            ["record"],
            tags(
                slug="break-the-ice",
                type="fixed",
                expression="break the ice",
                meaning="m",
                takeaway="memorize",
                learner_wrote="lw",
                context="c",
            ),
        )
        self.assertEqual((code, out.strip()), (0, "inserted"))

    def test_type_lands_in_type_column_not_kind(self):
        run_main(
            DECODE,
            ["record"],
            tags(
                slug="s",
                type="method",
                expression="e",
                meaning="m",
                takeaway="t",
                learner_wrote="lw",
                context="c",
            ),
        )
        import appdb

        self.assertEqual(appdb.query("SELECT type FROM decode")[0]["type"], "method")

    def test_missing_tag_is_self_correcting_error(self):
        code, _, err = run_main(DECODE, ["record"], "<slug>only</slug>")
        self.assertEqual(code, 1)
        self.assertIn("missing required tag", err)
        self.assertIn("<type>", err)  # template shown


class GrammarTest(EntrypointBase):
    def test_record_then_select_roundtrip(self):
        code, out, _ = run_main(
            GRAMMAR,
            ["record"],
            tags(slug="s1", problem="p", original="a", fixed="b", rule="r"),
        )
        self.assertEqual((code, out.strip()), (0, "inserted"))
        code, out, _ = run_main(GRAMMAR, ["select", "s1"])
        self.assertEqual(code, 0)
        self.assertIn('"counter": 1', out)
        self.assertIn(
            '"last example": "a → b"', out
        )  # ensure_ascii=False: literal arrow

    def test_select_all_one_json_per_row(self):
        run_main(
            GRAMMAR,
            ["record"],
            tags(slug="s1", problem="p", original="a", fixed="b", rule="r"),
        )
        run_main(
            GRAMMAR,
            ["record"],
            tags(slug="s2", problem="p", original="c", fixed="d", rule="r"),
        )
        code, out, _ = run_main(GRAMMAR, ["select"])
        self.assertEqual(len(out.strip().splitlines()), 2)

    def test_messages_empty_when_none(self):
        code, out, _ = run_main(GRAMMAR, ["messages", "--session", "x", "--lang", "en"])
        self.assertEqual((code, out.strip()), (0, "<messages></messages>"))


class RephrasingTest(EntrypointBase):
    def test_record_then_select(self):
        code, out, _ = run_main(
            REPHRASING,
            ["record"],
            tags(
                slug="word-choice",
                problem="p",
                learner_wrote="lw",
                native_phrase="np",
                why="w",
            ),
        )
        self.assertEqual((code, out.strip()), (0, "inserted"))
        self.assertTrue(run_main(REPHRASING, ["select", "word-choice"])[1].strip())


class IdiomsTest(EntrypointBase):
    def test_record_then_select(self):
        code, out, _ = run_main(
            IDIOMS,
            ["record"],
            tags(idiom="break the ice", meaning="m", context="c", learner_wrote="lw"),
        )
        self.assertEqual((code, out.strip()), (0, "inserted"))
        self.assertTrue(run_main(IDIOMS, ["select", "break the ice"])[1].strip())


class VerbsTest(EntrypointBase):
    def test_record_then_select(self):
        code, out, _ = run_main(
            VERBS,
            ["record"],
            tags(
                verb="go",
                past="went",
                participle="gone",
                used_form="goed",
                correction="went",
                context="c",
            ),
        )
        self.assertEqual((code, out.strip()), (0, "inserted"))
        self.assertTrue(run_main(VERBS, ["select", "go"])[1].strip())


class FrictionTest(EntrypointBase):
    def test_record_then_select(self):
        code, out, _ = run_main(
            FRICTION,
            ["record"],
            tags(
                slug="small-talk",
                type="lexical",
                zone="z",
                learner_wrote="lw",
                native_phrase="np",
                context="c",
            ),
        )
        self.assertEqual((code, out.strip()), (0, "inserted"))
        self.assertTrue(run_main(FRICTION, ["select", "small-talk"])[1].strip())

    def test_grammar_select_reads_grammar(self):
        run_main(
            GRAMMAR,
            ["record"],
            tags(slug="art", problem="p", original="a", fixed="b", rule="r"),
        )
        code, out, _ = run_main(FRICTION, ["grammar-select"])
        self.assertEqual(code, 0)
        self.assertIn('"slug": "art"', out)

    def test_loot_adds_vocab(self):
        code, out, _ = run_main(FRICTION, ["loot"], items(("hello", "привіт")))
        self.assertEqual(code, 0)
        self.assertIn("add: hello", out)
        import appdb

        self.assertEqual(
            appdb.query("SELECT translation FROM vocab WHERE word='hello'")[0][
                "translation"
            ],
            "привіт",
        )

    def test_messages_session_slice(self):
        code, out, _ = run_main(FRICTION, ["messages", "--session", "x"])
        self.assertEqual((code, out.strip()), (0, "<messages></messages>"))


LOOT = load("loot/loot.py", "ep_loot")
DROP = load("drop/drop.py", "ep_drop")


class LootTest(EntrypointBase):
    def test_add_multiple_pairs(self):
        code, out, _ = run_main(
            LOOT,
            ["add"],
            items(("hello", "привіт"), ("machine learning", "машинне навчання")),
        )
        self.assertEqual(code, 0)
        import appdb

        rows = {r["word"]: r for r in appdb.query("SELECT * FROM vocab")}
        self.assertEqual(rows["hello"]["translation"], "привіт")
        self.assertEqual(rows["machine learning"]["translation"], "машинне навчання")
        self.assertEqual(out.count("\n"), 2)

    def test_add_comma_in_translation_survives(self):
        code, _, _ = run_main(LOOT, ["add"], items(("however", "однак, проте")))
        import appdb

        self.assertEqual(
            appdb.query("SELECT translation FROM vocab WHERE word='however'")[0][
                "translation"
            ],
            "однак, проте",
        )

    def test_add_empty_items_is_error(self):
        code, _, _ = run_main(LOOT, ["add"], "<items>\n</items>")
        self.assertEqual(code, 1)


class DropTest(EntrypointBase):
    def test_remove_multiple(self):
        run_main(LOOT, ["add"], items(("alpha", "а"), ("beta", "б")))
        code, out, _ = run_main(DROP, ["remove", "alpha", "beta"])
        self.assertEqual(code, 0)
        self.assertIn("alpha: removed", out)
        self.assertIn("beta: removed", out)

    def test_remove_reports_unknown(self):
        run_main(LOOT, ["add"], items(("alpha", "а")))
        code, out, _ = run_main(DROP, ["remove", "alpha", "ghost"])
        self.assertIn("alpha: removed", out)
        self.assertIn("ghost: not found", out)


TUTOR = load("tutor/tutor.py", "ep_tutor")


class TutorEntrypointTest(EntrypointBase):
    def setUp(self):
        super().setUp()
        os.environ["CLAUDE_CODE_SESSION_ID"] = "sess-E"

    def tearDown(self):
        os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        super().tearDown()

    def _seed_grammar(self):
        import appdb

        con = appdb.connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO grammar(created_at, slug, problem, original,"
                    " fixed, rule) VALUES ('2026-06-12','art','p','a','b','r')"
                )
        finally:
            con.close()

    def test_record_reads_answer_tag_and_records(self):
        self._seed_grammar()
        code, out, _ = run_main(
            TUTOR,
            ["record", "grammar", "art", "fix", "pass"],
            "<answer>\nI fixed it\n</answer>",
        )
        self.assertEqual(code, 0)
        self.assertIn("box 2", out)
        import appdb

        self.assertEqual(
            appdb.query("SELECT answer FROM attempts")[0]["answer"], "I fixed it"
        )

    def test_record_missing_answer_tag_is_error(self):
        self._seed_grammar()
        code, _, err = run_main(
            TUTOR, ["record", "grammar", "art", "fix", "pass"], "bare answer"
        )
        self.assertEqual(code, 1)
        self.assertIn("<answer>", err)

    def test_deck_empty_prints_nothing(self):
        code, out, _ = run_main(TUTOR, ["deck"])
        self.assertEqual((code, out.strip()), (0, ""))

    def test_stats_json(self):
        code, out, _ = run_main(TUTOR, ["stats"])
        self.assertEqual(code, 0)
        import json

        self.assertEqual(json.loads(out)["tracked"], 0)


TRIAGE = load("debrief-triage/triage.py", "ep_triage")
DEBRIEF = load("debrief/debrief.py", "ep_debrief")


class TriageEntrypointTest(EntrypointBase):
    def _capture(self, text, session="s"):
        import appdb

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

    def test_messages_untagged_slice(self):
        self._capture("First normal english sentence here please")
        code, out, _ = run_main(TRIAGE, ["messages", "--untagged", "--limit", "200"])
        self.assertEqual(code, 0)
        self.assertIn('<m id="1"', out)

    def test_tag_writes_langs(self):
        self._capture("First normal english sentence here please")
        code, out, _ = run_main(TRIAGE, ["tag", "1=en"])
        self.assertEqual(code, 0)
        self.assertIn("tagged 1", out)
        import appdb

        self.assertEqual(
            appdb.query("SELECT langs FROM messages")[0]["langs"], '["en"]'
        )

    def test_tag_unknown_id_exit_1(self):
        code, _, _ = run_main(TRIAGE, ["tag", "999=en"])
        self.assertEqual(code, 1)


class DebriefEntrypointTest(EntrypointBase):
    def _capture(self, text, session="s"):
        import appdb

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

    def test_sessions_lists_pending(self):
        self._capture("First normal english sentence here please", "sess-A")
        code, out, _ = run_main(DEBRIEF, ["sessions"])
        self.assertEqual(code, 0)
        self.assertIn('"session": "sess-A"', out)

    def test_mark_drills_runs(self):
        code, out, _ = run_main(DEBRIEF, ["mark-drills"])
        self.assertEqual(code, 0)
        self.assertIn("marked 0", out)

    def test_pending_count(self):
        self._capture("First normal english sentence here please", "sess-A")
        code, out, _ = run_main(DEBRIEF, ["pending-count"])
        self.assertEqual((code, out.strip()), (0, "1"))

    def test_mark_processed_session(self):
        self._capture("First normal english sentence here please", "sess-A")
        run_main(TRIAGE, ["tag", "1=en"])
        code, out, _ = run_main(DEBRIEF, ["mark-processed", "--session", "sess-A"])
        self.assertEqual(code, 0)
        self.assertIn("processed 1", out)


if __name__ == "__main__":
    unittest.main()
