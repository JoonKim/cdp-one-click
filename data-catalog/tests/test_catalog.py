import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cataloglib import (
    LEVELS,
    USERS,
    USER_PRODUCTS,
    assign_new_tables,
    assign_tables,
    parse_hbase_tables,
    render_assignment_doc,
    tables_for_level,
)


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
            self.assertEqual(row["kind"], "system" if row["name"].startswith("hbase:") else "product")

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
        self.assertIn("were not drawn again", text)
        for row in rows:
            self.assertIn(row["level"], text)
            self.assertIn(row["user"], text)


class NewTableAssignmentTests(unittest.TestCase):
    def existing(self):
        return [
            {"name": "hbase:meta", "level": "SECRET", "user": "user_S"},
            {"name": "hbase:namespace", "level": "SECRET", "user": "user_S"},
        ]

    def test_keeps_locked_rows_and_covers_both_levels(self):
        existing = self.existing()
        snapshot = [dict(row) for row in existing]
        rows, used = assign_new_tables(existing, list(USER_PRODUCTS), seed=11)
        self.assertEqual(existing, snapshot)
        self.assertEqual([row["name"] for row in rows], list(USER_PRODUCTS))
        combined = existing + rows
        self.assertTrue(tables_for_level(combined, "CUI"))
        self.assertTrue(tables_for_level(combined, "UNCLASSIFIED"))
        self.assertEqual({row["level"] for row in existing}, {"SECRET"})
        again, used_again = assign_new_tables(existing, list(USER_PRODUCTS), seed=11)
        self.assertEqual(used_again, used)
        self.assertEqual(again, rows)

    def test_redraws_when_the_first_draw_misses_a_required_level(self):
        existing = self.existing()
        weak = None
        for candidate in range(1, 5000):
            levels = {row["level"] for row in assign_tables(list(USER_PRODUCTS), candidate)}
            if "CUI" not in levels or "UNCLASSIFIED" not in levels:
                weak = candidate
                break
        self.assertIsNotNone(weak)
        rows, used = assign_new_tables(existing, list(USER_PRODUCTS), weak)
        self.assertNotEqual(used, weak)
        self.assertTrue(tables_for_level(rows, "CUI"))
        self.assertTrue(tables_for_level(rows, "UNCLASSIFIED"))

    def test_refuses_to_reassign_locked_tables(self):
        with self.assertRaises(ValueError):
            assign_new_tables(self.existing(), ["hbase:meta", "catalog:personnel"], seed=1)


if __name__ == "__main__":
    unittest.main()
