import json
import unittest
import urllib.error
from unittest import mock

import anki


class _FakeResp:
    """Minimal context-manager stand-in for urlopen()'s return value."""

    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeAnki:
    """Records calls; returns canned results keyed by action. A result that is an
    Exception is raised; a callable is called with the params dict."""

    def __init__(self, results=None):
        self.calls = []
        self.results = results or {}

    def __call__(self, action, **params):
        self.calls.append((action, params))
        r = self.results.get(action)
        if isinstance(r, Exception):
            raise r
        return r(params) if callable(r) else r

    def actions(self):
        return [a for a, _ in self.calls]

    def params_for(self, action):
        return [p for a, p in self.calls if a == action]


class InvokeTest(unittest.TestCase):
    def test_returns_result_field(self):
        with mock.patch(
            "anki.urllib.request.urlopen",
            return_value=_FakeResp({"result": 6, "error": None}),
        ):
            self.assertEqual(anki._invoke("version"), 6)

    def test_anki_error_field_raises(self):
        with mock.patch(
            "anki.urllib.request.urlopen",
            return_value=_FakeResp({"result": None, "error": "boom"}),
        ):
            with self.assertRaises(anki.AnkiError):
                anki._invoke("addNote", note={})

    def test_transport_failure_raises(self):
        with mock.patch(
            "anki.urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaises(anki.AnkiError):
                anki._invoke("version")


class WrapClozeTest(unittest.TestCase):
    def test_wraps_case_insensitively_preserving_casing(self):
        self.assertEqual(
            anki._wrap_cloze(
                "Throughput rose as throughput improved.", "throughput", []
            ),
            "{{c1::Throughput}} rose as {{c1::throughput}} improved.",
        )

    def test_wraps_a_listed_form(self):
        self.assertEqual(
            anki._wrap_cloze(
                "The wind scattered the leaves.", "scatter", ["scattered"]
            ),
            "The wind {{c1::scattered}} the leaves.",
        )

    def test_word_and_form_both_share_c1(self):
        self.assertEqual(
            anki._wrap_cloze("scatter then scattered", "scatter", ["scattered"]),
            "{{c1::scatter}} then {{c1::scattered}}",
        )

    def test_no_coverage_returns_none(self):
        self.assertIsNone(anki._wrap_cloze("nothing here", "absent", []))


class BuildFieldsTest(unittest.TestCase):
    def test_full_row_maps_every_field(self):
        row = {
            "word": "throughput",
            "translation": "пропускна здатність",
            "examples": json.dumps(["We boosted throughput today."]),
            "alt_translations": json.dumps(["продуктивність"]),
            "synonyms": json.dumps(["bandwidth"]),
            "definition": "amount processed per unit time",
            "ctx": "We boosted throughput today.",
        }
        f = anki._build_fields(row)
        self.assertEqual(f["Word"], "throughput")
        self.assertEqual(f["Examples"], "We boosted {{c1::throughput}} today.")
        self.assertEqual(f["Translation"], "пропускна здатність")
        self.assertEqual(f["AltTranslations"], "продуктивність")
        self.assertEqual(f["Synonyms"], "bandwidth")
        self.assertEqual(f["Definition"], "amount processed per unit time")
        self.assertEqual(f["Context"], "We boosted throughput today.")

    def test_empty_enrichment_renders_blank_not_null(self):
        row = {
            "word": "w",
            "translation": "т",
            "examples": json.dumps(["a w here"]),
            "alt_translations": None,
            "synonyms": None,
            "definition": None,
            "ctx": None,
        }
        f = anki._build_fields(row)
        self.assertEqual(f["AltTranslations"], "")
        self.assertEqual(f["Synonyms"], "")
        self.assertEqual(f["Definition"], "")
        self.assertEqual(f["Context"], "")

    def test_multiple_examples_joined_with_pipe(self):
        row = {
            "word": "w",
            "translation": "т",
            "examples": json.dumps(["one w", "two w"]),
            "alt_translations": None,
            "synonyms": None,
            "definition": None,
            "ctx": None,
        }
        self.assertEqual(
            anki._build_fields(row)["Examples"], "one {{c1::w}}|two {{c1::w}}"
        )

    def test_form_in_example_is_clozed(self):
        row = {
            "word": "scatter",
            "translation": "розкидати",
            "examples": json.dumps(["The wind scattered the leaves."]),
            "forms": json.dumps(["scattered"]),
            "alt_translations": None,
            "synonyms": None,
            "definition": None,
            "ctx": None,
        }
        self.assertEqual(
            anki._build_fields(row)["Examples"],
            "The wind {{c1::scattered}} the leaves.",
        )

    def test_zero_coverage_row_returns_none(self):
        # examples present but no form covers the inflection -> uncovered -> None
        row = {
            "word": "scatter",
            "translation": "розкидати",
            "examples": json.dumps(["The wind scattered the leaves."]),
            "forms": None,  # un-re-looted: forms backfilled NULL
            "alt_translations": None,
            "synonyms": None,
            "definition": None,
            "ctx": None,
        }
        self.assertIsNone(anki._build_fields(row))

    def test_partial_coverage_drops_uncovered_segment(self):
        # one example clozes (base form), one doesn't -> covered one survives, row kept
        row = {
            "word": "scatter",
            "translation": "розкидати",
            "examples": json.dumps(
                ["Particles scatter widely.", "The wind scattered the leaves."]
            ),
            "forms": None,
            "alt_translations": None,
            "synonyms": None,
            "definition": None,
            "ctx": None,
        }
        self.assertEqual(
            anki._build_fields(row)["Examples"], "Particles {{c1::scatter}} widely."
        )


class EnsureModelTest(unittest.TestCase):
    def test_creates_model_when_absent(self):
        fake = FakeAnki({"modelNames": ["Basic"], "createModel": None})
        anki.ensure_model(invoke=fake)
        self.assertIn("createModel", fake.actions())
        params = fake.params_for("createModel")[0]
        self.assertEqual(params["modelName"], anki.MODEL_NAME)
        self.assertTrue(params["isCloze"])
        self.assertEqual(params["inOrderFields"], anki.FIELDS)

    def test_noop_when_model_present(self):
        fake = FakeAnki({"modelNames": ["Basic", anki.MODEL_NAME]})
        anki.ensure_model(invoke=fake)
        self.assertNotIn("createModel", fake.actions())


if __name__ == "__main__":
    unittest.main()
