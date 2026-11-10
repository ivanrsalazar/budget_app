import tempfile
import unittest
from datetime import date
from pathlib import Path

from budget.store import Store, nth_weekday_of_month, occurrences_between, scheduled_occurrences


class RecurrenceTests(unittest.TestCase):
    def test_month_end_is_clamped_without_drifting(self):
        dates = list(occurrences_between(date(2026, 1, 31), "monthly", date(2026, 2, 1), date(2026, 4, 30)))
        self.assertEqual(dates, [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)])

    def test_biweekly_skips_to_window(self):
        dates = list(occurrences_between(date(2026, 1, 2), "biweekly", date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(dates, [date(2026, 2, 13), date(2026, 2, 27)])

    def test_every_thursday_schedule(self):
        dates = list(scheduled_occurrences(
            date(2026, 11, 8), "weekly", "weekday", 3, None,
            date(2026, 11, 8), date(2026, 11, 30),
        ))
        self.assertEqual(dates, [date(2026, 11, 12), date(2026, 11, 19), date(2026, 11, 26)])

    def test_third_thursday_schedule(self):
        dates = list(scheduled_occurrences(
            date(2026, 11, 1), "monthly", "nth_weekday", 3, 3,
            date(2026, 11, 1), date(2027, 1, 31),
        ))
        self.assertEqual(dates, [date(2026, 11, 19), date(2026, 12, 17), date(2027, 1, 21)])

    def test_last_weekday_schedule(self):
        self.assertEqual(nth_weekday_of_month(2027, 2, 3, -1), date(2027, 2, 25))


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

    def test_projection_rolls_balance_forward_and_keeps_current_week_history(self):
        self.store.save_item("transactions", {
            "name": "Misc.", "kind": "expense", "amount": 24.44,
            "date": "2026-11-09", "status": "posted",
        })
        self.store.save_item("recurring_items", {
            "name": "Paycheck", "kind": "income", "amount": 1276,
            "frequency": "weekly", "start_date": "2026-11-12", "active": True,
        })

        result = self.store.projection(date(2026, 11, 9), 2, date(2026, 11, 10))
        self.assertEqual(result["through"], "2026-11-10")
        self.assertEqual(result["available_balance"], 975.56)
        self.assertEqual(result["balance_before_next_income"], 975.56)
        self.assertEqual(result["weeks"][0]["events"][0]["name"], "Misc.")
        self.assertEqual(result["weeks"][0]["opening_balance"], 1000)

        later_window = self.store.projection(date(2026, 11, 10), 1, date(2026, 11, 10))
        self.assertEqual(later_window["starting_balance"], 975.56)

        self.store.update_settings({"current_balance": 975.56, "balance_as_of": "2026-11-10"})
        full_week = self.store.projection(date(2026, 11, 9), 1, date(2026, 11, 10))
        self.assertEqual(full_week["starting_balance"], 1000)
        self.assertEqual(full_week["available_balance"], 975.56)

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

    def test_nth_weekday_item_projects_on_requested_day(self):
        item = self.store.save_item("recurring_items", {
            "name": "Rent", "kind": "expense", "amount": 1600,
            "schedule_type": "nth_weekday", "weekday": 3, "ordinal": 3,
            "start_date": "2026-11-01", "active": True,
        })
        self.assertEqual(item["frequency"], "monthly")
        result = self.store.projection(date(2026, 11, 1), 8)
        rent_dates = [event["date"] for week in result["weeks"] for event in week["events"]]
        self.assertEqual(rent_dates, ["2026-11-19", "2026-12-17"])

    def test_credit_funded_expense_increases_card_charges_not_cash_outflow(self):
        card = self.store.save_item("credit_lines", {
            "name": "Discover", "balance": 500, "credit_limit": 3000,
            "apr": 24.99, "due_day": 15, "minimum_payment": 35,
        })
        recurring = self.store.save_item("recurring_items", {
            "name": "Streaming", "kind": "expense", "amount": 25,
            "frequency": "weekly", "start_date": "2026-11-09", "active": True,
            "funding_source": "credit", "credit_line_id": card["id"],
        })
        result = self.store.projection(date(2026, 11, 8), 1)
        self.assertEqual(result["weeks"][0]["expenses"], 0)
        self.assertEqual(result["weeks"][0]["card_charges"], 25)
        self.assertEqual(result["ending_balance"], 1000)
        self.assertEqual(result["credit_lines"][0]["projected_balance"], 525)
        self.assertEqual(result["weeks"][0]["events"][0]["credit_line_name"], "Discover")

        self.store.delete_item("credit_lines", card["id"])
        updated = next(item for item in self.store.list_items("recurring_items") if item["id"] == recurring["id"])
        self.assertEqual(updated["funding_source"], "checking")
        self.assertIsNone(updated["credit_line_id"])

    def test_one_time_and_recurring_card_payments_reduce_projected_debt(self):
        card = self.store.save_item("credit_lines", {"name": "Capital One", "balance": 600})
        recurring = self.store.save_item("recurring_items", {
            "name": "Monthly card payment", "kind": "expense", "amount": 100,
            "frequency": "monthly", "start_date": "2026-11-10", "active": True,
            "funding_source": "credit", "credit_line_id": card["id"],
            "destination_credit_line_id": card["id"],
        })
        transaction = self.store.save_item("transactions", {
            "name": "Extra card payment", "kind": "expense", "amount": 50,
            "date": "2026-11-12", "status": "planned",
            "destination_credit_line_id": card["id"],
        })

        # A payment target always forces the source back to Checking.
        self.assertEqual(recurring["funding_source"], "checking")
        self.assertIsNone(recurring["credit_line_id"])
        result = self.store.projection(date(2026, 11, 8), 1)
        self.assertEqual(result["weeks"][0]["expenses"], 150)
        self.assertEqual(result["weeks"][0]["card_payments"], 150)
        self.assertEqual(result["ending_balance"], 850)
        self.assertEqual(result["credit_lines"][0]["scheduled_payments"], 150)
        self.assertEqual(result["credit_lines"][0]["projected_balance"], 450)

        self.store.delete_item("credit_lines", card["id"])
        recurring_after = next(item for item in self.store.list_items("recurring_items") if item["id"] == recurring["id"])
        transaction_after = next(item for item in self.store.list_items("transactions") if item["id"] == transaction["id"])
        self.assertIsNone(recurring_after["destination_credit_line_id"])
        self.assertIsNone(transaction_after["destination_credit_line_id"])

    def test_one_time_card_purchase_increases_debt_without_reducing_checking(self):
        card = self.store.save_item("credit_lines", {"name": "Discover", "balance": 400})
        purchase = self.store.save_item("transactions", {
            "name": "Plane ticket", "kind": "expense", "amount": 350,
            "date": "2026-11-12", "status": "planned",
            "funding_source": "credit", "credit_line_id": card["id"],
        })
        self.assertEqual(purchase["funding_source"], "credit")
        result = self.store.projection(date(2026, 11, 8), 1)
        self.assertEqual(result["weeks"][0]["expenses"], 0)
        self.assertEqual(result["weeks"][0]["card_charges"], 350)
        self.assertEqual(result["ending_balance"], 1000)
        self.assertEqual(result["credit_lines"][0]["projected_balance"], 750)
        event = result["weeks"][0]["events"][0]
        self.assertEqual(event["credit_line_name"], "Discover")

        self.store.delete_item("credit_lines", card["id"])
        updated = next(item for item in self.store.list_items("transactions") if item["id"] == purchase["id"])
        self.assertEqual(updated["funding_source"], "checking")
        self.assertIsNone(updated["credit_line_id"])

    def test_spendable_before_payday_includes_credit_aware_comparison(self):
        self.store.update_settings({"auto_pay_card_charges": False})
        card = self.store.save_item("credit_lines", {"name": "Discover", "balance": 0})
        self.store.save_item("recurring_items", {
            "name": "Paycheck", "kind": "income", "amount": 2000,
            "frequency": "biweekly", "start_date": "2026-11-13", "active": True,
        })
        self.store.save_item("transactions", {
            "name": "Prior-week purchase", "kind": "expense", "amount": 200,
            "date": "2026-11-03", "status": "planned",
            "funding_source": "credit", "credit_line_id": card["id"],
        })
        self.store.save_item("transactions", {
            "name": "Plane ticket", "kind": "expense", "amount": 300,
            "date": "2026-11-10", "status": "planned",
            "funding_source": "credit", "credit_line_id": card["id"],
        })
        result = self.store.projection(date(2026, 11, 1), 2)
        self.assertEqual(result["balance_before_next_income"], 1000)
        self.assertEqual(result["balance_before_next_income_after_card_charges"], 700)

    def test_monday_payoff_moves_prior_week_card_charges_to_checking(self):
        card = self.store.save_item("credit_lines", {"name": "Discover", "balance": 250})
        for name, amount, purchase_date in (
            ("Flight", 200, "2026-11-03"),
            ("Dinner", 50, "2026-11-08"),
        ):
            self.store.save_item("transactions", {
                "name": name, "kind": "expense", "amount": amount,
                "date": purchase_date, "status": "planned",
                "funding_source": "credit", "credit_line_id": card["id"],
            })

        result = self.store.projection(date(2026, 11, 9), 1)
        payoff = result["weeks"][0]["events"][0]
        self.assertEqual(payoff["source"], "auto_card_payment")
        self.assertEqual(payoff["date"], "2026-11-09")
        self.assertEqual(payoff["amount"], 250)
        self.assertEqual(payoff["destination_credit_line_id"], card["id"])
        self.assertEqual(result["weeks"][0]["expenses"], 250)
        self.assertEqual(result["weeks"][0]["card_payments"], 250)
        self.assertEqual(result["ending_balance"], 750)
        self.assertEqual(result["credit_lines"][0]["projected_balance"], 0)

        settings = self.store.update_settings({"auto_pay_card_charges": False})
        self.assertFalse(settings["auto_pay_card_charges"])
        disabled = self.store.projection(date(2026, 11, 9), 1)
        self.assertEqual(disabled["weeks"][0]["events"], [])
        self.assertEqual(disabled["ending_balance"], 1000)

if __name__ == "__main__":
    unittest.main()

