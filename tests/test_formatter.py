import csv
import io
import json
import unittest

from zeroql.formatter import format_csv, format_json, format_table


class TestFormatTable(unittest.TestCase):
    def test_empty_rows(self):
        self.assertEqual(format_table([]), "(0 rows)")

    def test_renders_null_and_bool(self):
        out = format_table([{"a": None, "b": True}, {"a": 1, "b": False}])
        self.assertIn("NULL", out)
        self.assertIn("true", out)
        self.assertIn("false", out)
        self.assertIn("(2 rows)", out)


class TestFormatCsv(unittest.TestCase):
    def test_empty_rows(self):
        self.assertEqual(format_csv([]), "")

    def test_header_and_rows(self):
        out = format_csv([{"name": "Ada", "age": 36}, {"name": "Grace", "age": 45}])
        lines = out.splitlines()
        self.assertEqual(lines[0], "name,age")
        self.assertEqual(lines[1], "Ada,36")
        self.assertEqual(lines[2], "Grace,45")

    def test_null_becomes_empty_field(self):
        # A lone empty field gets quoted ("") by Python's csv module itself,
        # to distinguish it from a genuinely blank line -- round-trip
        # through csv.reader instead of asserting on the raw text.
        out = format_csv([{"a": None}])
        rows = list(csv.reader(io.StringIO(out)))
        self.assertEqual(rows, [["a"], [""]])


class TestFormatJson(unittest.TestCase):
    def test_round_trips_through_json(self):
        rows = [{"name": "Ada", "age": 36}, {"name": "Grace", "age": 45}]
        self.assertEqual(json.loads(format_json(rows)), rows)

    def test_empty_rows_is_empty_array(self):
        self.assertEqual(format_json([]), "[]")


if __name__ == "__main__":
    unittest.main()
