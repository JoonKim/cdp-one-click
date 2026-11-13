import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cataloglib import LEVELS, USERS, assign_tables, parse_hbase_tables, render_assignment_doc


SHELL_OUTPUT = """
HBase Shell
Use "help" to get list of supported commands.
TABLE
hbase:meta
hbase:namespace
2 row(s)
Took 0.2104 seconds
=> ["hbase:meta", "hbase:namespace"]
"""


class ParseTests(unittest.TestCase):
    def test_table_block(self):
        self.assertEqual(parse_hbase_tables(SHELL_OUTPUT), ["hbase:meta", "hbase:namespace"])

    def test_ruby_fallback(self):
        text = 'something\n=> ["orders", "customers"]\n'
        self.assertEqual(parse_hbase_tables(text), ["orders", "customers"])

    def test_empty(self):
        self.assertEqual(parse_hbase_tables("no tables here"), [])


class AssignmentTests(unittest.TestCase):
    def test_each_table_has_one_level_and_matching_user(self):
        rows = assign_tables(["hbase:meta", "hbase:namespace", "orders"], seed=11)
        self.assertEqual([row["name"] for row in rows], ["hbase:meta", "hbase:namespace", "orders"])
        for row in rows:
            self.assertIn(row["level"], LEVELS)
            self.assertEqual(row["user"], USERS[row["level"]])
            self.assertEqual(row["atlas_classification"], row["level"])
            self.assertTrue(row["ranger_policy"].endswith(row["level"]))

    def test_seed_is_stable(self):
        self.assertEqual(assign_tables(["a", "b", "c"], 99), assign_tables(["a", "b", "c"], 99))

    def test_document_lists_every_table(self):
        rows = assign_tables(["hbase:meta", "sales"], seed=3)
        doc = {
            "cluster": {
                "name": "cdp-reduced-local",
                "mode": "reduced",
                "live_cdp": {"blocker": "No live CDP cluster is reachable."},
                "services": {
                    "hbase": {"ui": "http://127.0.0.1:16010"},
                    "ranger": {"ui": "http://127.0.0.1:6080"},
                    "atlas": {"ui": "http://127.0.0.1:21000"},
                },
            },
            "seed": 3,
            "recorded_at": "2026-11-13T00:00:00+00:00",
            "status": "recorded",
            "tables": rows,
            "ranger": {"service": "cdp_hbase", "policies": []},
            "atlas": {"entities": []},
        }
        text = render_assignment_doc(doc)
        self.assertIn("`hbase:meta`", text)
        self.assertIn("`sales`", text)
        for row in rows:
            self.assertIn(row["level"], text)
            self.assertIn(row["user"], text)


if __name__ == "__main__":
    unittest.main()
