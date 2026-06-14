"""Property-based tests for the pure cores (Hypothesis, dev-only).

Hypothesis is a dev/test tool, never a runtime dependency. The import is guarded
so the stdlib `python -m unittest` baseline still passes with hypothesis absent
(these classes simply skip). Run them with the tool present:

    uvx --with hypothesis python -m unittest discover -s tests -t .

What each class pins is a property that must hold for ALL inputs in range, not a
hand-picked example: the tagio parser round-trips, the Leitner math stays in
bounds, vocab matching respects word boundaries, and the slug/key normalizers are
idempotent + shape-stable.
"""

import re
import unittest
from datetime import date, timedelta

import core
import tagio
from models.base import norm_key
from models.tutor import INTERVALS, VERDICTS, _due, _next_box
from models.vocab import build_pattern, word_in_text

try:
    from hypothesis import assume, given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # dev-only tool — keep the stdlib baseline runnable
    HAS_HYPOTHESIS = False

    def given(*a, **k):
        return lambda f: f

    def settings(*a, **k):
        return lambda f: f

    def assume(*a, **k):
        return None

    class _DummyStrategies:
        def __getattr__(self, name):
            return lambda *a, **k: None

    st = _DummyStrategies()

# alphanumeric, so values carry no TAB / newline / '<' that the parser is
# sensitive to — used where the property only needs "ordinary token" inputs.
TOKEN = st.text(alphabet="abcdefABCDEF0123456789", min_size=1, max_size=8)
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis not installed (dev-only tool)")
class TagioRoundTrip(unittest.TestCase):
    @settings(deadline=None)
    @given(st.text(alphabet=st.characters(blacklist_characters="<")))
    def test_text_field_roundtrips(self, value):
        # a scalar that contains no tag char and no edge newline must come back
        # verbatim (the parser strips only ONE layout newline at each end).
        assume(not value.startswith("\n") and not value.endswith("\n"))
        parsed = tagio.read_fields({"f": tagio.TEXT}, f"<f>{value}</f>")
        self.assertEqual(parsed["f"], value)

    @settings(deadline=None)
    @given(st.lists(st.tuples(TOKEN, TOKEN), max_size=6))
    def test_rows_field_roundtrips(self, records):
        body = "\n".join(f"{a}\t{b}" for a, b in records)
        parsed = tagio.read_fields({"r": tagio.rows("a", "b")}, f"<r>\n{body}\n</r>")
        self.assertEqual(parsed["r"], [{"a": a, "b": b} for a, b in records])

    @settings(deadline=None)
    @given(TOKEN)
    def test_missing_required_tag_raises(self, name):
        assume(name != "present")
        with self.assertRaises(ValueError):
            tagio.read_fields({name: tagio.TEXT}, "<present>x</present>")


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis not installed (dev-only tool)")
class LeitnerMath(unittest.TestCase):
    @settings(deadline=None)
    @given(st.integers(min_value=1, max_value=5), st.sampled_from(VERDICTS))
    def test_next_box_stays_in_bounds(self, box, verdict):
        nb = _next_box(box, verdict)
        self.assertIn(nb, range(1, 6))
        if verdict == "pass":
            self.assertEqual(nb, min(box + 1, 5))
        elif verdict == "fail":
            self.assertEqual(nb, 1)
        else:
            self.assertEqual(nb, box)

    @settings(deadline=None)
    @given(
        st.integers(min_value=1, max_value=5),
        st.dates(min_value=date(1, 1, 1), max_value=date(9999, 11, 1)),
    )
    def test_due_is_strictly_after_today(self, box, today):
        due = _due(box, today.isoformat())
        self.assertEqual(
            date.fromisoformat(due), today + timedelta(days=INTERVALS[box])
        )
        self.assertGreater(date.fromisoformat(due), today)


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis not installed (dev-only tool)")
class VocabMatching(unittest.TestCase):
    @settings(deadline=None)
    @given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=10))
    def test_word_matches_itself_case_insensitively(self, word):
        self.assertTrue(word_in_text(word, word))
        self.assertTrue(word_in_text(word, word.upper()))

    @settings(deadline=None)
    @given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=10))
    def test_word_respects_boundaries(self, word):
        # glued inside a larger run of letters, the boundary lookarounds must fail
        self.assertFalse(word_in_text(word, "z" + word + "z"))

    @settings(deadline=None)
    @given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=10))
    def test_build_pattern_is_anchored(self, word):
        self.assertIsNotNone(build_pattern(word).search(word))


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis not installed (dev-only tool)")
class Normalizers(unittest.TestCase):
    @settings(deadline=None)
    @given(st.text())
    def test_slugify_shape_and_idempotence(self, s):
        out = core.slugify(s)
        self.assertTrue(out == "" or SLUG_RE.match(out), repr(out))
        self.assertEqual(core.slugify(out), out)

    @settings(deadline=None)
    @given(st.text())
    def test_norm_key_idempotent_and_clean(self, s):
        once = norm_key(s)
        self.assertEqual(norm_key(once), once)
        self.assertEqual(once, once.lower())
        self.assertNotIn("  ", once)


if __name__ == "__main__":
    unittest.main()
