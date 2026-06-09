import os
import shutil
import tempfile
import unittest

from mddb import NotFound, UniqueViolation
from models.base import Model


class Widget(Model):
    file = "widgets.md"
    columns = ["sku", "counter", "name"]
    key = "sku"
    counter = "counter"


class Log(Model):           # append-only: no key, no counter
    file = "log.md"
    columns = ["date", "msg"]


class ModelTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)


class WidgetTest(ModelTestBase):
    def test_insert_sets_counter_one(self):
        self.assertEqual(Widget.insert({"sku": "A", "name": "Gadget"}), "inserted")
        self.assertEqual(Widget.select("A"),
                         {"sku": "A", "counter": "1", "name": "Gadget"})

    def test_insert_duplicate_key_raises(self):
        Widget.insert({"sku": "A", "name": "Gadget"})
        with self.assertRaises(UniqueViolation):
            Widget.insert({"sku": " a ", "name": "Other"})   # norm_key matches

    def test_upsert_increments_and_overwrites(self):
        Widget.insert({"sku": "A", "name": "Gadget"})
        self.assertEqual(Widget.upsert({"sku": "A", "name": "Gizmo"}), "incremented")
        self.assertEqual(Widget.select("A"),
                         {"sku": "A", "counter": "2", "name": "Gizmo"})

    def test_upsert_missing_inserts(self):
        self.assertEqual(Widget.upsert({"sku": "B", "name": "New"}), "inserted")
        self.assertEqual(Widget.select("B")["counter"], "1")

    def test_update_overwrites_but_keeps_counter(self):
        Widget.insert({"sku": "A", "name": "Gadget"})
        Widget.upsert({"sku": "A", "name": "x"})             # counter -> 2
        self.assertEqual(Widget.update({"sku": "A", "name": "Final"}), "updated")
        self.assertEqual(Widget.select("A"),
                         {"sku": "A", "counter": "2", "name": "Final"})

    def test_update_missing_raises(self):
        with self.assertRaises(NotFound):
            Widget.update({"sku": "Z", "name": "x"})

    def test_delete(self):
        Widget.insert({"sku": "A", "name": "Gadget"})
        self.assertEqual(Widget.delete("A"), "deleted")
        self.assertIsNone(Widget.select("A"))

    def test_delete_missing_raises(self):
        with self.assertRaises(NotFound):
            Widget.delete("nope")

    def test_drop_removes_file(self):
        Widget.insert({"sku": "A", "name": "Gadget"})
        Widget.drop()
        self.assertEqual(Widget.select(), [])

    def test_unknown_column_raises(self):
        with self.assertRaises(ValueError):
            Widget.insert({"sku": "A", "bogus": "x"})

    def test_non_int_counter_treated_as_zero(self):
        Widget.insert({"sku": "A", "name": "g"})
        rows = Widget.select()
        rows[0]["counter"] = "abc"                            # corrupt the tally
        Widget._write(rows)
        Widget.upsert({"sku": "A", "name": "g"})
        self.assertEqual(Widget.select("A")["counter"], "1")  # 0 -> +1


class LogTest(ModelTestBase):
    def test_append_only_allows_duplicates(self):
        Log.insert({"date": "d1", "msg": "hello"})
        Log.insert({"date": "d1", "msg": "hello"})
        self.assertEqual(len(Log.select()), 2)

    def test_upsert_without_key_raises(self):
        with self.assertRaises(ValueError):
            Log.upsert({"date": "d1", "msg": "x"})


if __name__ == "__main__":
    unittest.main()
