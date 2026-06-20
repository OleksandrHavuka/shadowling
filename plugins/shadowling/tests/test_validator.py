import unittest

from validator import TEXT, SchemaError, validate


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
