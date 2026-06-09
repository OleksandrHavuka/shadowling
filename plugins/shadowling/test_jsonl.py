import os
import shutil
import tempfile
import unittest

import jsonl


class JsonlTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "x.jsonl")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_missing_reads_empty(self):
        self.assertEqual(jsonl.read(self.path), [])

    def test_append_then_read_round_trips_lossless(self):
        jsonl.append(self.path, {"a": 1})
        jsonl.append(self.path, {"a": 2, "b": "x|y\nz"})  # pipe + newline survive
        self.assertEqual(jsonl.read(self.path),
                         [{"a": 1}, {"a": 2, "b": "x|y\nz"}])

    def test_corrupt_line_skipped(self):
        jsonl.append(self.path, {"ok": 1})
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("not json at all\n")
        jsonl.append(self.path, {"ok": 2})
        self.assertEqual(jsonl.read(self.path), [{"ok": 1}, {"ok": 2}])

    def test_append_creates_parent_dir(self):
        nested = os.path.join(self.dir, "sub", "y.jsonl")
        jsonl.append(nested, {"k": "v"})
        self.assertEqual(jsonl.read(nested), [{"k": "v"}])


if __name__ == "__main__":
    unittest.main()
