import tempfile
import unittest
from datetime import date
from pathlib import Path

from budget.store import Store, add_months, occurrences_between


class RecurrenceTests(unittest.TestCase):
    def test_month_end_is_clamped_without_drifting(self):
        dates = list(occurrences_between(date(2026, 1, 31), "monthly", date(2026, 2, 1), date(2026, 4, 30)))
        self.assertEqual(dates, [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)])

    def test_biweekly_skips_to_window(self):
        dates = list(occurrences_between(date(2026, 1, 2), "biweekly", date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(dates, [date(2026, 2, 13), date(2026, 2, 27)])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "budget.db")
        self.store.initialize()
        self.store.update_settings({"current_balance": 1000, "balance_as_of": "2026-11-08"})

    def tearDown(self):
        self.temp.cleanup()

    def test_projection_calculates_next_payday_and_week_totals(self):
        self.store.save_item("recurring_items", {
            "name": "Paycheck", "kind": "income", "amount": 2000,
            "frequency": "biweekly", "start_date": "2026-11-13", "active": True,
        })
        self.store.save_item("recurring_items", {
            "name": "Groceries", "kind": "expense", "amount": 100,
            "frequency": "weekly", "start_date": "2026-11-09", "active": True,
        })
        self.store.save_item("transactions", {
            "name": "Car repair", "kind": "expense", "amount": 250,
            "date": "2026-11-11", "status": "planned",
        })

        result = self.store.projection(date(2026, 11, 8), 2)
        self.assertEqual(result["balance_before_next_income"], 650)
        self.assertEqual(result["next_income"]["date"], "2026-11-13")
        self.assertEqual(result["weeks"][0]["income"], 2000)
        self.assertEqual(result["weeks"][0]["expenses"], 350)
        self.assertEqual(result["weeks"][1]["expenses"], 100)
        self.assertEqual(result["ending_balance"], 2550)

    def test_crud_and_pause_recurring_item(self):
        item = self.store.save_item("recurring_items", {
            "name": "Rent", "kind": "expense", "amount": 1600,
            "frequency": "monthly", "start_date": "2026-11-19", "active": True,
        })
        item["active"] = False
        updated = self.store.save_item("recurring_items", item, item["id"])
        self.assertEqual(updated["active"], 0)
        result = self.store.projection(date(2026, 11, 8), 4)
        self.assertEqual(result["ending_balance"], 1000)
        self.store.delete_item("recurring_items", item["id"])
        self.assertEqual(self.store.list_items("recurring_items"), [])

    def test_sample_import_is_idempotent(self):
        sample = Path(self.temp.name) / "sample.csv"
        sample.write_text(",Nov 5th,,Nov 12th\n,389,,1343\nExpenses,,Expenses,\nRent,/500,Food,100\nexpense subtotal,500,expense subtotal,100\nLeft,111,Left,1243\n", encoding="utf-8")
        first = self.store.import_sample(sample)
        second = self.store.import_sample(sample)
        self.assertEqual(first["imported"], 2)
        self.assertTrue(second["skipped"])
        self.assertEqual(self.store.settings()["current_balance"], 111)
        self.assertEqual([x["name"] for x in self.store.list_items("transactions")], ["Rent", "Food"])


if __name__ == "__main__":
    unittest.main()

