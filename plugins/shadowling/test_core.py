import unittest
from datetime import datetime

import core


class TodayTest(unittest.TestCase):
    def test_today_is_iso_date(self):
        self.assertRegex(core.today(), r"^\d{4}-\d{2}-\d{2}$")

    def test_today_matches_now(self):
        self.assertEqual(core.today(), datetime.now().strftime("%Y-%m-%d"))


if __name__ == "__main__":
    unittest.main()
