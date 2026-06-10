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
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _write_config(self, data):
        with open(os.path.join(self.home, "config.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _configure(self):
        self._write_config({"native_language": "Ukrainian",
                            "explanation_language": "English"})


class GetTest(ConfigCliTestBase):
    def test_get_fails_when_no_config(self):
        code, out = run_main(["get", "native_language"])
        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "")

    def test_get_fails_when_partially_configured(self):
        # whole-plugin gate: ANY missing key means not configured
        self._write_config({"native_language": "Ukrainian"})
        code, _ = run_main(["get", "explanation_language"])
        self.assertEqual(code, 1)

    def test_get_prints_each_configured_key(self):
        self._configure()
        self.assertEqual(run_main(["get", "native_language"])[1].strip(),
                         "Ukrainian")
        self.assertEqual(run_main(["get", "explanation_language"])[1].strip(),
                         "English")

    def test_get_unknown_key_is_error(self):
        self._configure()
        self.assertEqual(run_main(["get", "learning_language"])[0], 1)


class SetTest(ConfigCliTestBase):
    def test_set_persists_and_get_reads_it(self):
        self.assertEqual(run_main(["set", "native_language", "Spanish"])[0], 0)
        self.assertEqual(run_main(["set", "explanation_language", "German"])[0], 0)
        self.assertEqual(run_main(["get", "native_language"])[1].strip(), "Spanish")
        self.assertEqual(run_main(["get", "explanation_language"])[1].strip(),
                         "German")

    def test_set_preserves_unknown_keys_in_file(self):
        self._write_config({"native_language": "Ukrainian",
                            "explanation_language": "English",
                            "future_key": "kept"})
        run_main(["set", "native_language", "Spanish"])
        raw = core.raw_config()
        self.assertEqual(raw["future_key"], "kept")
        self.assertEqual(raw["explanation_language"], "English")
        self.assertEqual(raw["native_language"], "Spanish")

    def test_set_unknown_key_is_error(self):
        self.assertEqual(run_main(["set", "learning_language", "German"])[0], 1)

    def test_set_empty_value_is_error(self):
        self.assertEqual(run_main(["set", "native_language", "   "])[0], 1)


class ReadyTest(ConfigCliTestBase):
    def test_not_ready_on_missing_or_partial(self):
        self.assertFalse(core.config_ready())
        self._write_config({"native_language": "Ukrainian"})
        self.assertFalse(core.config_ready())

    def test_ready_when_both_set(self):
        self._configure()
        self.assertTrue(core.config_ready())

    def test_load_config_exposes_exactly_the_known_keys(self):
        self._write_config({"native_language": "Ukrainian",
                            "explanation_language": "English",
                            "learning_language": "stale"})
        cfg = core.load_config()
        self.assertEqual(set(cfg), {"native_language", "explanation_language"})
        self.assertTrue(core.config_ready())

    def test_load_config_blank_for_malformed_values(self):
        self._write_config({"native_language": 7})
        self.assertEqual(core.load_config()["native_language"], "")


class UnknownCommandTest(ConfigCliTestBase):
    def test_no_args_is_error(self):
        self.assertEqual(run_main([])[0], 1)

    def test_unknown_command_is_error(self):
        self.assertEqual(run_main(["bogus", "native_language"])[0], 1)


if __name__ == "__main__":
    unittest.main()
