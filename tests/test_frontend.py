import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendRegressionTests(unittest.TestCase):
    def test_dialog_cancel_controls_never_submit_required_forms(self):
        markup = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(markup.count('type="button" data-dialog-close'), 4)
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


if __name__ == "__main__":
    unittest.main()
