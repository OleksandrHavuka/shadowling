import contextlib
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

import appdb
import tutor


def run_main(argv, stdin_text="", wrap=True):
    # `record` now reads the answer from an <answer> tag; wrap the raw answer in
    # the envelope the tutor skill produces. wrap=False feeds stdin as-is (to
    # exercise the parser's own error path).
    if wrap and argv[:1] == ["record"]:
        stdin_text = "<answer>\n" + stdin_text + "\n</answer>"
    out, err = io.StringIO(), io.StringIO()
    old = tutor.sys.stdin
    tutor.sys.stdin = io.StringIO(stdin_text)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tutor.main(argv)
    finally:
        tutor.sys.stdin = old
    return code, out.getvalue(), err.getvalue()


class TutorTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home
        os.environ["CLAUDE_CODE_SESSION_ID"] = "sess-T"

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def seed_grammar(self, slug="article-omission", n=1):
        con = appdb.connect()
        try:
            with con:
                for _ in range(n):
                    con.execute(
                        "INSERT INTO grammar(created_at, slug, problem, original,"
                        " fixed, rule) VALUES ('2026-06-12', ?, 'p',"
                        " 'I went to store', 'I went to the store', 'use the')",
                        (slug,),
                    )
        finally:
            con.close()

    def mastery(self, kind, key):
        rows = appdb.query(
            f"SELECT * FROM mastery WHERE item_kind='{kind}' AND item_key='{key}'"
        )
        return rows[0] if rows else None


class RecordTest(TutorTestBase):
    def test_attempt_created_at_full_ts_and_mastery_stamps(self):
        self.seed_grammar()
        with (
            mock.patch("models.tutor._today", return_value="2026-06-12"),
            mock.patch("models.tutor._now", return_value="2026-06-12T09:00:00"),
        ):
            run_main(
                ["record", "grammar", "article-omission", "fix", "pass"], stdin_text="x"
            )
        a = appdb.query("SELECT * FROM attempts")[0]
        self.assertEqual(a["created_at"], "2026-06-12T09:00:00")  # full ISO ts
        m = self.mastery("grammar", "article-omission")
        self.assertEqual(m["created_at"], "2026-06-12T09:00:00")
        self.assertEqual(m["updated_at"], "2026-06-12T09:00:00")  # equal on insert
        with (
            mock.patch("models.tutor._today", return_value="2026-06-12"),
            mock.patch("models.tutor._now", return_value="2026-06-12T10:30:00"),
        ):
            run_main(
                ["record", "grammar", "article-omission", "fix", "pass"], stdin_text="y"
            )
        m2 = self.mastery("grammar", "article-omission")
        self.assertEqual(m2["created_at"], "2026-06-12T09:00:00")  # pinned
        self.assertEqual(m2["updated_at"], "2026-06-12T10:30:00")  # bumped

    def test_box_caps_at_5(self):
        self.seed_grammar()
        for _ in range(7):
            with mock.patch("models.tutor._today", return_value="2026-06-12"):
                run_main(
                    ["record", "grammar", "article-omission", "fix", "pass"],
                    stdin_text="x",
                )
        m = self.mastery("grammar", "article-omission")
        self.assertEqual(m["box"], 5)
        self.assertEqual(m["due_date"], "2026-07-17")  # +35 days

    def test_answer_verbatim_with_quotes_and_newlines(self):
        self.seed_grammar()
        tricky = 'he said "it\'s done" — `rm -rf` & $HOME\nsecond line'
        run_main(
            ["record", "grammar", "article-omission", "fix", "pass"], stdin_text=tricky
        )
        self.assertEqual(
            appdb.query("SELECT answer FROM attempts")[0]["answer"], tricky
        )

    def test_missing_answer_tag_is_error_with_guidance(self):
        self.seed_grammar()
        code, _, err = run_main(
            ["record", "grammar", "article-omission", "fix", "pass"],
            stdin_text="bare answer, no tag",
            wrap=False,
        )
        self.assertEqual(code, 1)
        self.assertIn("<answer>", err)  # self-correcting message names the tag


if __name__ == "__main__":
    unittest.main()
