import os
import shutil
import tempfile
import unittest

import mddb


class PrimitiveTest(unittest.TestCase):
    def test_norm_key_collapses_and_lowers(self):
        self.assertEqual(mddb.norm_key("  Go   HOME "), "go home")

    def test_split_row_strips_borders_and_cells(self):
        self.assertEqual(mddb._split_row("| a | b |"), ["a", "b"])

    def test_is_separator(self):
        self.assertTrue(mddb._is_separator(["---", "---"]))
        self.assertFalse(mddb._is_separator(["a", "---"]))

    def test_escape_cell_neutralizes_pipe_and_newlines(self):
        self.assertEqual(mddb._escape_cell("a|b\nc"), "a\\|b c")


class TableIOTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "t.md")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_missing_file_reads_empty(self):
        self.assertEqual(mddb.read_table(self.path), ([], []))

    def test_round_trip_preserves_headers_and_rows(self):
        headers = ["k", "counter", "v"]
        rows = [{"k": "a", "counter": "1", "v": "x"},
                {"k": "b", "counter": "2", "v": "y"}]
        mddb.write_table(self.path, headers, rows)
        self.assertEqual(mddb.read_table(self.path), (headers, rows))

    def test_pipe_in_cell_round_trips(self):
        mddb.write_table(self.path, ["k", "v"], [{"k": "a", "v": "x|y"}])
        _, rows = mddb.read_table(self.path)
        self.assertEqual(rows[0]["v"], "x|y")

    def test_missing_cells_pad_to_empty(self):
        # a hand-written short row should read back with empty trailing cells
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("| k | v |\n| --- | --- |\n| a |\n")
        _, rows = mddb.read_table(self.path)
        self.assertEqual(rows, [{"k": "a", "v": ""}])


if __name__ == "__main__":
    unittest.main()
