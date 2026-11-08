import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendRegressionTests(unittest.TestCase):
    def test_dialog_cancel_controls_never_submit_required_forms(self):
        markup = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(markup.count('type="button" data-dialog-close'), 6)
        self.assertNotIn('class="icon-button" value="cancel"', markup)

    def test_theme_bootstraps_before_styles_and_has_a_toggle(self):
        markup = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        boot = markup.index("document.documentElement.dataset.theme")
        stylesheet = markup.index('rel="stylesheet"')
        self.assertLess(boot, stylesheet)
        self.assertIn('id="themeToggle"', markup)

    def test_recurring_form_exposes_weekday_schedules(self):
        markup = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn('value="weekday">Every selected weekday', markup)
        self.assertIn('value="nth_weekday">Nth weekday of each month', markup)
        self.assertIn('<option value="3" selected>Thursday</option>', markup)
        self.assertIn('<option value="3" selected>Third</option>', markup)

    def test_calendar_credit_cards_and_funding_source_are_present(self):
        markup = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-view-panel="calendar"', markup)
        self.assertIn('data-view-panel="cards"', markup)
        self.assertIn('id="calendarGrid"', markup)
        self.assertIn('id="creditForm"', markup)
        self.assertIn('name="funding_account"', markup)
        self.assertIn('class="field wide expense-funding"', markup)
        self.assertIn('name="payment_target"', markup)

    def test_calendar_renders_daily_running_checking_balance(self):
        script = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("state.calendarBalanceProjection.starting_balance", script)
        self.assertIn("event.signed_amount", script)
        self.assertIn('class="day-balance', script)
        self.assertIn(".day-balance", styles)

    def test_item_actions_use_visible_menu_instead_of_typed_prompt(self):
        script = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn("prompt(`Type", script)
        self.assertIn('data-item-action="edit"', script)
        self.assertIn('data-item-action="delete"', script)
        self.assertIn('.item-menu:hover .action-menu', styles)


if __name__ == "__main__":
    unittest.main()
