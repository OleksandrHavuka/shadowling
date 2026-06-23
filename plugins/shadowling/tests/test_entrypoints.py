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


def run_main(mod, argv, stdin_text=""):
    """Call mod.main(argv) with stdin_text on the GLOBAL sys.stdin (which
    skillio.read_fields reads). Returns (code, stdout, stderr)."""
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
        # /aha → decode.record stamps the ambient session via core.session_id()
        os.environ["CLAUDE_CODE_SESSION_ID"] = "sess-E"

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
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
        self.assertEqual(code, 0)
        self.assertIn("<status>inserted</status>", out)

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


DROP = load("drop/drop.py", "ep_drop")


class DropTest(EntrypointBase):
    def _seed(self, *pairs):
        from models.vocab import Vocab

        for word, tr in pairs:
            Vocab.add(word, tr, examples=[f"a line with {word}"])

    def test_remove_multiple(self):
        self._seed(("alpha", "а"), ("beta", "б"))
        code, out, _ = run_main(DROP, ["remove", "alpha", "beta"])
        self.assertEqual(code, 0)
        self.assertIn("<word>alpha</word>", out)
        self.assertIn("<word>beta</word>", out)
        self.assertEqual(out.count("<outcome>removed</outcome>"), 2)

    def test_remove_reports_unknown(self):
        self._seed(("alpha", "а"))
        code, out, _ = run_main(DROP, ["remove", "alpha", "ghost"])
        self.assertIn("<word>alpha</word>", out)
        self.assertIn("<outcome>removed</outcome>", out)
        self.assertIn("<word>ghost</word>", out)
        self.assertIn("<outcome>not found</outcome>", out)


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
        self.assertIn("<box>2</box>", out)
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

    def test_deck_empty_renders_empty_block(self):
        code, out, _ = run_main(TUTOR, ["deck"])
        self.assertEqual((code, out.strip()), (0, "<deck></deck>"))

    def test_stats_renders_tags(self):
        code, out, _ = run_main(TUTOR, ["stats"])
        self.assertEqual(code, 0)
        self.assertIn("<stats>", out)
        self.assertIn("<tracked>0</tracked>", out)


if __name__ == "__main__":
    unittest.main()
