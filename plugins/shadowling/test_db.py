import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

import db
import models
from models.base import Model


class Widget(Model):
    file = "widgets.md"
    columns = ["sku", "counter", "name"]
    key = "sku"
    counter = "counter"


class DbTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home
        models.REGISTRY["widget"] = Widget

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        models.REGISTRY.pop("widget", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = db.main(argv)
        return code, buf.getvalue()

    def test_upsert_maps_positional_args_skipping_counter(self):
        code, out = self._run(["widget", "upsert", "A", "Gadget"])
        self.assertEqual(code, 0)
        self.assertIn("inserted", out)
        self.assertEqual(Widget.select("A"),
                         {"sku": "A", "counter": "1", "name": "Gadget"})

    def test_select_prints_json_rows(self):
        Widget.insert({"sku": "A", "name": "Gadget"})
        code, out = self._run(["widget", "select", "A"])
        self.assertEqual(code, 0)
        self.assertIn('"name": "Gadget"', out)
        self.assertIn('"counter": "1"', out)

    def test_unknown_repo_exits_nonzero(self):
        code, _ = self._run(["nope", "select"])
        self.assertEqual(code, 1)

    def test_unique_violation_exits_nonzero(self):
        self._run(["widget", "insert", "A", "Gadget"])
        code, _ = self._run(["widget", "insert", "A", "Other"])
        self.assertEqual(code, 1)


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        models.RECORDERS["faux"] = lambda *a: self.calls.append(a) or "inserted"

    def tearDown(self):
        models.RECORDERS.pop("faux", None)

    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = db.main(argv)
        return code, buf.getvalue()

    def test_record_dispatches_positional_args(self):
        code, out = self._run(["faux", "record", "a", "b", "c"])
        self.assertEqual(code, 0)
        self.assertIn("inserted", out)
        self.assertEqual(self.calls, [("a", "b", "c")])

    def test_unknown_recorder_exits_nonzero(self):
        code, _ = self._run(["nope", "record", "x"])
        self.assertEqual(code, 1)

    def test_record_arity_error_exits_nonzero(self):
        models.RECORDERS["strict"] = lambda x, y: "inserted"
        try:
            code, _ = self._run(["strict", "record", "only-one-arg"])
        finally:
            models.RECORDERS.pop("strict", None)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
