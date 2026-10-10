import locale
import unittest
from datetime import date, time

from clients.vlr import VlrClient


class LocaleTests(unittest.TestCase):
    def test_english_dates_and_times_under_both_locales(self):
        old = locale.setlocale(locale.LC_TIME)
        try:
            for loc in ("C", "zh_CN.UTF-8"):
                locale.setlocale(locale.LC_TIME, loc)
                self.assertEqual(
                    VlrClient._parse_vlr_date_label("Thu, September 24, 2026"),
                    date(2026, 9, 24),
                )
                self.assertEqual(
                    VlrClient._parse_vlr_date_label(
                        "Thursday, February 29, 2024 Today"
                    ),
                    date(2024, 2, 29),
                )
                self.assertIsNone(VlrClient._parse_vlr_date_label("February 29, 2025"))
                for raw, expected in [
                    ("5:00 PM", time(17)),
                    ("12 AM", time(0)),
                    ("12:30 PM", time(12, 30)),
                    ("23:59", time(23, 59)),
                ]:
                    self.assertEqual(VlrClient._parse_vlr_time_to_obj(raw), expected)
                for raw in ("13 PM", "00 AM", "25:00", "5:99 PM", "TBD"):
                    self.assertIsNone(VlrClient._parse_vlr_time_to_obj(raw))
        finally:
            locale.setlocale(locale.LC_TIME, old)
