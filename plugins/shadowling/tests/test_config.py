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
        self._write_config(
            {
                "first_language": "Ukrainian",
                "explanation_language": "English",
                "learning_language": "English",
            }
        )


class GetTest(ConfigCliTestBase):
    def test_get_fails_when_no_config(self):
        code, out = run_main(["get", "first_language"])
        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "")

    def test_get_fails_when_partially_configured(self):
        # whole-plugin gate: ANY missing key means not configured
        self._write_config({"first_language": "Ukrainian"})
        code, _ = run_main(["get", "explanation_language"])
        self.assertEqual(code, 1)

    def test_get_failure_emits_notice_naming_missing_key(self):
        self._write_config(
            {"first_language": "Ukrainian", "explanation_language": "English"}
        )
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = config.main(["get", "learning_language"])
        self.assertEqual(code, 1)
        self.assertIn("not fully configured", err.getvalue())
        self.assertIn("learning_language", err.getvalue())  # names the gap

    def test_show_emits_all_keys_as_tags_when_ready(self):
        self._configure()
        code, out = run_main(["show"])
        self.assertEqual(code, 0)
        self.assertIn("<config>", out)
        self.assertIn("<first_language>Ukrainian</first_language>", out)
        self.assertIn("<learning_language>English</learning_language>", out)
        self.assertIn("<explanation_language>English</explanation_language>", out)

    def test_show_fails_with_notice_when_unconfigured(self):
        self._write_config({"first_language": "Ukrainian"})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = config.main(["show"])
        self.assertEqual(code, 1)
        self.assertIn("not fully configured", err.getvalue())
        self.assertIn("learning_language", err.getvalue())

    def test_get_prints_each_configured_key(self):
        self._configure()
        self.assertIn(
            "<first_language>Ukrainian</first_language>",
            run_main(["get", "first_language"])[1],
        )
        self.assertIn(
            "<explanation_language>English</explanation_language>",
            run_main(["get", "explanation_language"])[1],
        )

    def test_get_unknown_key_is_error(self):
        self._configure()
        self.assertEqual(run_main(["get", "bogus_language"])[0], 1)


class SetTest(ConfigCliTestBase):
    def test_set_persists_and_get_reads_it(self):
        self.assertEqual(run_main(["set", "first_language", "Spanish"])[0], 0)
        self.assertEqual(run_main(["set", "explanation_language", "German"])[0], 0)
        self.assertEqual(run_main(["set", "learning_language", "French"])[0], 0)
        self.assertIn(
            "<first_language>Spanish</first_language>",
            run_main(["get", "first_language"])[1],
        )
        self.assertIn(
            "<explanation_language>German</explanation_language>",
            run_main(["get", "explanation_language"])[1],
        )
        self.assertIn(
            "<learning_language>French</learning_language>",
            run_main(["get", "learning_language"])[1],
        )

    def test_set_preserves_unknown_keys_in_file(self):
        self._write_config(
            {
                "first_language": "Ukrainian",
                "explanation_language": "English",
                "future_key": "kept",
            }
        )
        run_main(["set", "first_language", "Spanish"])
        raw = core.raw_config()
        self.assertEqual(raw["future_key"], "kept")
        self.assertEqual(raw["explanation_language"], "English")
        self.assertEqual(raw["first_language"], "Spanish")

    def test_set_unknown_key_is_error(self):
        self.assertEqual(run_main(["set", "bogus_language", "German"])[0], 1)

    def test_set_empty_value_is_error(self):
        self.assertEqual(run_main(["set", "first_language", "   "])[0], 1)


class ReadyTest(ConfigCliTestBase):
    def test_not_ready_on_missing_or_partial(self):
        self.assertFalse(core.config_ready())
        self._write_config({"first_language": "Ukrainian"})
        self.assertFalse(core.config_ready())

    def test_ready_when_all_set(self):
        self._configure()
        self.assertTrue(core.config_ready())

    def test_not_ready_when_learning_language_missing(self):
        # the new third key is part of the whole-plugin gate
        self._write_config(
            {"first_language": "Ukrainian", "explanation_language": "English"}
        )
        self.assertFalse(core.config_ready())

    def test_load_config_exposes_known_keys_and_drops_stale(self):
        self._write_config(
            {
                "first_language": "Ukrainian",
                "explanation_language": "English",
                "learning_language": "Spanish",
                "future_key": "stale",
            }
        )
        cfg = core.load_config()
        self.assertEqual(
            set(cfg),
            {
                "first_language",
                "explanation_language",
                "learning_language",
                "missing",  # derived gate state
                "notice",
            },
        )
        self.assertNotIn("future_key", cfg)  # unknown keys dropped
        self.assertEqual(cfg["missing"], [])  # fully configured
        self.assertEqual(cfg["notice"], "")
        self.assertTrue(core.config_ready())

    def test_load_config_missing_lists_unset_required_keys(self):
        self._write_config(
            {"first_language": "Ukrainian", "explanation_language": "English"}
        )
        cfg = core.load_config()
        self.assertEqual(cfg["missing"], ["learning_language"])
        self.assertIn("learning_language", cfg["notice"])  # notice names the gap
        self.assertFalse(core.config_ready())

    def test_load_config_unconfigured_notices_every_key(self):
        self._write_config({})
        cfg = core.load_config()
        self.assertEqual(cfg["missing"], list(core.CONFIG_KEYS))
        self.assertIn("not fully configured", cfg["notice"])

    def test_load_config_blank_for_malformed_values(self):
        self._write_config({"first_language": 7})
        self.assertEqual(core.load_config()["first_language"], "")


class UnknownCommandTest(ConfigCliTestBase):
    def test_no_args_is_error(self):
        self.assertEqual(run_main([])[0], 1)

    def test_unknown_command_is_error(self):
        self.assertEqual(run_main(["bogus", "first_language"])[0], 1)


if __name__ == "__main__":
    unittest.main()
