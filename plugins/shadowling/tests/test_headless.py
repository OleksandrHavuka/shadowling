import json
import os
import subprocess
import unittest
from unittest import mock

import headless

TRIVIAL_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {}}


def _event_array(structured_output, subtype="success", is_error=False):
    """A claude `--output-format json` stdout: a JSON array ending in a result event."""
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


class ParseResultTest(unittest.TestCase):
    def test_success_returns_structured_output(self):
        self.assertEqual(
            headless.parse_result(_event_array({"code": "en"})), {"code": "en"}
        )

    def test_error_subtype_raises(self):
        with self.assertRaises(headless.HeadlessError):
            headless.parse_result(
                _event_array({}, subtype="error_max_turns", is_error=True)
            )

    def test_is_error_true_raises_even_if_success_subtype(self):
        with self.assertRaises(headless.HeadlessError):
            headless.parse_result(_event_array({"code": "en"}, is_error=True))

    def test_non_json_raises(self):
        with self.assertRaises(headless.HeadlessError):
            headless.parse_result("not json")

    def test_no_result_event_raises(self):
        with self.assertRaises(headless.HeadlessError):
            headless.parse_result(json.dumps([{"type": "system"}]))

    def test_missing_structured_output_raises(self):
        with self.assertRaises(headless.HeadlessError):
            headless.parse_result(
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
        self.assertEqual(headless.parse_result(events), {"code": "en"})


class RunClaudeTest(unittest.TestCase):
    def test_builds_expected_argv_and_returns_output(self):
        seen = {}

        def runner(argv, data):
            seen["argv"], seen["data"] = argv, data
            return _event_array({"code": "en"})

        out = headless.run_claude(
            "the role", "the data", TRIVIAL_SCHEMA, headless.HAIKU, runner=runner
        )
        self.assertEqual(out, {"code": "en"})
        self.assertEqual(seen["data"], "the data")
        argv = seen["argv"]
        self.assertEqual(argv[0], "claude")
        self.assertIn("--safe-mode", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        disallowed = argv[argv.index("--disallowed-tools") + 1]
        self.assertEqual(disallowed, "mcp__*")
        # a bare "*" token must NEVER appear: it also removes the implicit
        # StructuredOutput tool that --json-schema needs to emit the result, so the
        # model can never finish and the call dies with error_max_turns.
        self.assertNotIn("*", disallowed.split())
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(argv[argv.index("--max-turns") + 1], "4")
        self.assertEqual(argv[argv.index("--model") + 1], headless.HAIKU)
        self.assertEqual(argv[argv.index("--system-prompt") + 1], "the role")
        self.assertEqual(
            json.loads(argv[argv.index("--json-schema") + 1]), TRIVIAL_SCHEMA
        )

    def test_missing_claude_binary_raises(self):
        with mock.patch("headless.resolve_claude", return_value=None):
            with self.assertRaises(headless.HeadlessError):
                headless.run_claude("r", "d", TRIVIAL_SCHEMA, headless.HAIKU)

    def test_timeout_maps_to_headless_error(self):
        def boom(argv, data):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

        with self.assertRaises(headless.HeadlessError):
            headless.run_claude("r", "d", TRIVIAL_SCHEMA, headless.HAIKU, runner=boom)

    def test_effort_flag_included_when_passed(self):
        seen = {}

        def runner(argv, data):
            seen["argv"] = argv
            return _event_array({"code": "en"})

        headless.run_claude(
            "r", "d", TRIVIAL_SCHEMA, headless.SONNET, runner=runner, effort="medium"
        )
        self.assertEqual(seen["argv"][seen["argv"].index("--effort") + 1], "medium")

    def test_effort_flag_absent_by_default(self):
        seen = {}

        def runner(argv, data):
            seen["argv"] = argv
            return _event_array({"code": "en"})

        headless.run_claude("r", "d", TRIVIAL_SCHEMA, headless.HAIKU, runner=runner)
        self.assertNotIn("--effort", seen["argv"])


class ResolveClaudeTest(unittest.TestCase):
    def test_prefers_claude_on_path(self):
        with mock.patch("headless.shutil.which", return_value="/usr/bin/claude"):
            self.assertEqual(headless.resolve_claude(), "/usr/bin/claude")

    def test_falls_back_to_local_install(self):
        with (
            mock.patch("headless.shutil.which", return_value=None),
            mock.patch("headless.os.path.isfile", return_value=True),
            mock.patch("headless.os.access", return_value=True),
        ):
            got = headless.resolve_claude()
        self.assertEqual(
            got, os.path.join(os.path.expanduser("~"), ".claude", "local", "claude")
        )

    def test_returns_none_when_nothing_found(self):
        with (
            mock.patch("headless.shutil.which", return_value=None),
            mock.patch("headless.os.path.isfile", return_value=False),
        ):
            self.assertIsNone(headless.resolve_claude())


class FindingsSchemaTest(unittest.TestCase):
    def test_generates_all_required_string_props(self):
        s = headless.findings_schema("a", "b")
        item = s["properties"]["findings"]["items"]
        self.assertEqual(item["required"], ["a", "b"])
        self.assertEqual(set(item["properties"]), {"a", "b"})
        self.assertFalse(item["additionalProperties"])

    def test_enum_and_extra_applied(self):
        s = headless.findings_schema(
            "t", enums={"t": ["x", "y"]}, extra={"loot": {"type": "array"}}
        )
        item = s["properties"]["findings"]["items"]
        self.assertEqual(item["properties"]["t"]["enum"], ["x", "y"])
        self.assertIn("loot", s["properties"])
        self.assertIn("loot", s["required"])


if __name__ == "__main__":
    unittest.main()
