import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

import config
import core


def run_main(argv):
    """Run config.main(argv), returning (exit_code, stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = config.main(argv)
    return code, buf.getvalue()


class ConfigCliTestBase(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SHADOWLING_CONFIG", None)  # use data_dir()/config.json
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        os.environ.pop("SHADOWLING_CONFIG", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _write_config(self, data):
        with open(os.path.join(self.home, "config.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)


class LangTest(ConfigCliTestBase):
    def test_lang_empty_when_no_config(self):
        code, out = run_main(["lang"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_lang_prints_configured_language(self):
        self._write_config({"native_language": "Spanish"})
        code, out = run_main(["lang"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "Spanish")

    def test_lang_empty_when_config_lacks_native_language(self):
        # malformed/empty config must NOT mask first-run (no default echoed)
        self._write_config({"learning_language": "English"})
        code, out = run_main(["lang"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")


class SetLangTest(ConfigCliTestBase):
    def test_set_lang_persists_and_load_reads_it(self):
        code, _ = run_main(["set-lang", "Spanish"])
        self.assertEqual(code, 0)
        self.assertEqual(core.load_config()["native_language"], "Spanish")

    def test_set_lang_preserves_existing_learning_language(self):
        self._write_config({"native_language": "Ukrainian",
                            "learning_language": "German"})
        run_main(["set-lang", "Spanish"])
        loaded = core.load_config()
        self.assertEqual(loaded["native_language"], "Spanish")
        self.assertEqual(loaded["learning_language"], "German")

    def test_set_lang_empty_is_error(self):
        code, _ = run_main(["set-lang", "   "])
        self.assertEqual(code, 1)


class UnknownCommandTest(ConfigCliTestBase):
    def test_no_args_is_error(self):
        code, _ = run_main([])
        self.assertEqual(code, 1)

    def test_unknown_command_is_error(self):
        code, _ = run_main(["bogus"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
