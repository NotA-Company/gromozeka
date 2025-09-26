"""
Test suite for lib/utils.py
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from lib.utils import parseDelay


class TestUtils(unittest.TestCase):

    def test_parse_delay_days_hours_minutes_seconds_format(self):
        """Test parsing delay in DDdHHhMMmSSs format with all components"""
        # Test various combinations with all components
        self.assertEqual(
            parseDelay("1d2h30m15s"), 95415
        )  # 1 day, 2 hours, 30 minutes, 15 seconds
        self.assertEqual(parseDelay("0d1h0m0s"), 3600)  # 1 hour
        self.assertEqual(parseDelay("0d0h30m0s"), 1800)  # 30 minutes
        self.assertEqual(parseDelay("0d0h0m45s"), 45)  # 45 seconds
        self.assertEqual(parseDelay("2d0h0m0s"), 172800)  # 2 days
        self.assertEqual(
            parseDelay("1d1h1m1s"), 90061
        )  # 1 day, 1 hour, 1 minute, 1 second

    def test_parse_delay_optional_sections_format(self):
        """Test parsing delay in DDdHHhMMmSSs format with optional sections"""
        # Test with only days
        self.assertEqual(parseDelay("1d"), 86400)  # 1 day
        self.assertEqual(parseDelay("5d"), 432000)  # 5 days

        # Test with only hours
        self.assertEqual(parseDelay("2h"), 7200)  # 2 hours
        self.assertEqual(parseDelay("10h"), 36000)  # 10 hours

        # Test with only minutes
        self.assertEqual(parseDelay("30m"), 1800)  # 30 minutes
        self.assertEqual(parseDelay("45m"), 2700)  # 45 minutes

        # Test with only seconds
        self.assertEqual(parseDelay("15s"), 15)  # 15 seconds
        self.assertEqual(parseDelay("45s"), 45)  # 45 seconds

        # Test with combinations of sections (not all)
        self.assertEqual(parseDelay("1d2h"), 93600)  # 1 day, 2 hours
        self.assertEqual(parseDelay("2h30m"), 9000)  # 2 hours, 30 minutes
        self.assertEqual(parseDelay("30m15s"), 1815)  # 30 minutes, 15 seconds
        self.assertEqual(parseDelay("1d30m"), 88200)  # 1 day, 30 minutes
        self.assertEqual(parseDelay("1d15s"), 86415)  # 1 day, 15 seconds
        self.assertEqual(parseDelay("2h15s"), 7215)  # 2 hours, 15 seconds

        # Test with zero values in optional sections
        self.assertEqual(parseDelay("0d"), 0)  # 0 days
        self.assertEqual(parseDelay("0h"), 0)  # 0 hours
        self.assertEqual(parseDelay("0m"), 0)  # 0 minutes
        self.assertEqual(parseDelay("0s"), 0)  # 0 seconds

    def test_parse_delay_hours_minutes_seconds_format(self):
        """Test parsing delay in HH:MM:SS format"""
        self.assertEqual(parseDelay("2:30:15"), 9015)  # 2 hours, 30 minutes, 15 seconds
        self.assertEqual(parseDelay("1:00:00"), 3600)  # 1 hour
        self.assertEqual(parseDelay("0:30:00"), 1800)  # 30 minutes
        self.assertEqual(parseDelay("0:00:45"), 45)  # 45 seconds
        self.assertEqual(parseDelay("24:00:00"), 86400)  # 24 hours (1 day)

    def test_parse_delay_hours_minutes_format(self):
        """Test parsing delay in HH:MM format (seconds default to 0)"""
        self.assertEqual(parseDelay("2:30"), 9000)  # 2 hours, 30 minutes
        self.assertEqual(parseDelay("1:00"), 3600)  # 1 hour
        self.assertEqual(parseDelay("0:30"), 1800)  # 30 minutes

    def test_parse_delay_invalid_formats(self):
        """Test that invalid formats raise ValueError"""

        # Invalid format 2: Wrong order or missing separators
        with self.assertRaises(ValueError):
            parseDelay("1d2h30s1m")  # Wrong order

        # Invalid format 3: Invalid characters
        with self.assertRaises(ValueError):
            parseDelay("1d2h30m15x")  # 'x' instead of 's'

        # Invalid format 4: Invalid time format
        with self.assertRaises(ValueError):
            parseDelay("25:70:00")  # 70 minutes is invalid

        # Invalid format 5: Invalid time format with colon
        with self.assertRaises(ValueError):
            parseDelay("2:30:60")  # 60 seconds is invalid

        # Invalid format 6: Completely wrong format
        with self.assertRaises(ValueError):
            parseDelay("invalid")

        # Invalid format 7: Empty string
        with self.assertRaises(ValueError):
            parseDelay("")

    def test_parse_delay_edge_cases(self):
        """Test edge cases"""
        # Test zero values
        self.assertEqual(parseDelay("0d0h0m0s"), 0)
        self.assertEqual(parseDelay("0:00:00"), 0)
        self.assertEqual(parseDelay("0:00"), 0)

        # Test large values
        self.assertEqual(parseDelay("100d0h0m0s"), 8640000)  # 100 days
        self.assertEqual(parseDelay("100:00:00"), 360000)  # 100 hours


if __name__ == "__main__":
    unittest.main()
