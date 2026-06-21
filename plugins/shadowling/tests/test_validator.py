import unittest

from validator import OPTIONAL, TEXT, SchemaError, validate


class TextLeafTest(unittest.TestCase):
    def test_str_ok(self):
        self.assertEqual(validate("hi", TEXT), "hi")

    def test_empty_str_ok(self):
        self.assertEqual(validate("", TEXT), "")

    def test_non_str_raises(self):
        with self.assertRaises(SchemaError):
            validate(["x"], TEXT)


class ObjectTest(unittest.TestCase):
    def test_all_keys_present(self):
        got = validate({"a": "1", "b": "2"}, {"a": TEXT, "b": TEXT})
        self.assertEqual(got, {"a": "1", "b": "2"})

    def test_missing_key_raises_naming_it(self):
        with self.assertRaises(SchemaError) as cm:
            validate({"a": "1"}, {"a": TEXT, "b": TEXT})
        self.assertIn("b", str(cm.exception))

    def test_extra_keys_dropped(self):
        self.assertEqual(validate({"a": "1", "junk": "z"}, {"a": TEXT}), {"a": "1"})

    def test_non_dict_raises(self):
        with self.assertRaises(SchemaError):
            validate("x", {"a": TEXT})


class ListTest(unittest.TestCase):
    def test_many_elements(self):
        self.assertEqual(
            validate([{"w": "a"}, {"w": "b"}], [{"w": TEXT}]),
            [{"w": "a"}, {"w": "b"}],
        )

    def test_single_element(self):
        self.assertEqual(validate([{"w": "a"}], [{"w": TEXT}]), [{"w": "a"}])

    def test_empty_list(self):
        self.assertEqual(validate([], [{"w": TEXT}]), [])

    def test_empty_string_coerced_to_empty_list(self):
        # an empty element parses to "" (skillio); a list schema takes it as []
        self.assertEqual(validate("", [{"w": TEXT}]), [])

    def test_non_list_raises(self):
        with self.assertRaises(SchemaError):
            validate({"w": "a"}, [{"w": TEXT}])


class NestedTest(unittest.TestCase):
    def test_loot_shape(self):
        data = {
            "items": [
                {"word": "throughput", "ctx": "We boosted throughput."},
                {"word": "idempotent", "ctx": ""},
            ]
        }
        schema = {"items": [{"word": TEXT, "ctx": TEXT}]}
        self.assertEqual(validate(data, schema), data)


class OptionalTest(unittest.TestCase):
    SCHEMA = {"word": TEXT, "ctx": OPTIONAL(TEXT)}

    def test_present_optional_is_validated(self):
        self.assertEqual(
            validate({"word": "w", "ctx": "c"}, self.SCHEMA),
            {"word": "w", "ctx": "c"},
        )

    def test_absent_optional_is_omitted_not_defaulted(self):
        # the key is simply absent from the shaped output (no synthetic default)
        self.assertEqual(validate({"word": "w"}, self.SCHEMA), {"word": "w"})

    def test_present_but_empty_optional_is_kept(self):
        self.assertEqual(
            validate({"word": "w", "ctx": ""}, self.SCHEMA),
            {"word": "w", "ctx": ""},
        )

    def test_present_optional_with_wrong_type_still_raises(self):
        with self.assertRaises(SchemaError):
            validate({"word": "w", "ctx": ["x"]}, self.SCHEMA)

    def test_required_sibling_is_still_enforced(self):
        with self.assertRaises(SchemaError) as cm:
            validate({"ctx": "c"}, self.SCHEMA)
        self.assertIn("word", str(cm.exception))

    def test_optional_list_absent_is_omitted(self):
        self.assertEqual(validate({}, {"items": OPTIONAL([TEXT])}), {})

    def test_optional_list_present_is_validated(self):
        self.assertEqual(
            validate({"items": ["a", "b"]}, {"items": OPTIONAL([TEXT])}),
            {"items": ["a", "b"]},
        )

    def test_template_marks_optional_key_with_question_mark(self):
        with self.assertRaises(SchemaError) as cm:
            validate({"ctx": "c"}, self.SCHEMA)  # missing required 'word'
        self.assertIn("ctx?", str(cm.exception))  # optional rendered as `ctx?`


class ErrorMessageTest(unittest.TestCase):
    def test_message_shows_path_and_template(self):
        with self.assertRaises(SchemaError) as cm:
            validate(
                {"items": [{"word": "x"}]}, {"items": [{"word": TEXT, "ctx": TEXT}]}
            )
        msg = str(cm.exception)
        self.assertIn("ctx", msg)  # names the missing key
        self.assertIn("items", msg)  # path context
        self.assertIn("<text>", msg)  # the expected-shape template fragment


if __name__ == "__main__":
    unittest.main()
