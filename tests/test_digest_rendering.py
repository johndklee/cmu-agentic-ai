import re
import unittest

from actions.email_action import _rich_markup_to_html
from digest_rendering import render_email_digest_markup, render_terminal_digest
from formatting import strip_rich_markup


class DigestRenderingParityTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "title": "Daily Digest for Tests",
            "location": "San Francisco, California, US",
            "date": "Monday, June 01, 2026",
            "time": "10:08 PM PDT",
            "sections": {
                "weather": "Clear sky, 12.1C",
                "key_highlights": "overdue task: Task A | due soon task: Task B",
                "tasks": "Task A (due 2026-06-02) | Task B (due 2026-06-03)",
                "calendar": (
                    "Team Sync @ 2026-06-02 | organizer: user@example.com | "
                    "attending: a@x.com, b@x.com | "
                    "1:1 @ 2026-06-03 | organizer: user@example.com | "
                    "attending: c@x.com"
                ),
                "emails": (
                    "Subject One - Relation: sent_to_user - From: one@example.com | "
                    "Date: Mon, 01 Jun 2026 13:23:53 +0000 (UTC) | "
                    "Body(3 lines, 280 chars max): Line 1 || Line 2 || Line 3 | "
                    "Subject Two - Relation: sent_by_user - From: two@example.com | "
                    "Date: Mon, 01 Jun 2026 15:00:00 +0000 (UTC) | "
                    "Body(3 lines, 280 chars max): A || B || C"
                ),
                "news": "Headline 1 - URL: https://example.com/1 | Headline 2 - URL: https://example.com/2",
            },
        }

    def _terminal_sections(self, text: str) -> dict:
        pattern = r"\[bold cyan\]([^:]+):\[/bold cyan\](.*?)(?=\n\[bold cyan\]|$)"
        return {name: body for name, body in re.findall(pattern, text, flags=re.DOTALL)}

    def _email_html_sections(self, html: str) -> dict:
        pattern = (
            r'<div style="margin: 0 0 14px 0; padding: 12px 14px; border: 1px solid #e2e8f0; border-radius: 10px;">'
            r'<div style="font-weight: 700; color: #0e7490; margin-bottom: 8px; font-size: 14px; text-transform: uppercase; letter-spacing: 0.02em;">([^<]+)</div>'
            r'(.*?)</div>'
        )
        return {name: body for name, body in re.findall(pattern, html, flags=re.DOTALL)}

    def test_date_time_is_single_row_in_terminal_and_email_markup(self):
        terminal = render_terminal_digest(self.payload)
        terminal_plain = strip_rich_markup(terminal)
        email_markup = render_email_digest_markup(self.payload)

        self.assertEqual(terminal.count("[bold cyan]Date & Time:[/bold cyan]"), 1)
        self.assertIn("Date & Time: Monday, June 01, 2026 | 10:08 PM PDT", terminal_plain)

        self.assertEqual(email_markup.count("Date & Time:"), 1)
        self.assertIn("Date & Time: Monday, June 01, 2026 | 10:08 PM PDT", email_markup)
        self.assertNotIn("\nDate:", email_markup)
        self.assertNotIn("\nTime:", email_markup)

    def test_terminal_calendar_has_one_bullet_per_event(self):
        terminal = render_terminal_digest(self.payload)
        calendar_block = self._terminal_sections(terminal).get("Calendar", "")
        self.assertTrue(calendar_block, "Missing terminal section block for Calendar")

        bullets = re.findall(r"^\s*-\s+", calendar_block, flags=re.MULTILINE)
        self.assertEqual(len(bullets), 2)
        self.assertIn("Team Sync @ 2026-06-02 | organizer:", calendar_block)
        self.assertIn("1:1 @ 2026-06-03 | organizer:", calendar_block)

    def test_terminal_emails_has_one_bullet_per_email(self):
        terminal = render_terminal_digest(self.payload)
        emails_block = self._terminal_sections(terminal).get("Emails", "")
        self.assertTrue(emails_block, "Missing terminal section block for Emails")

        bullets = re.findall(r"^\s*-\s+", emails_block, flags=re.MULTILINE)
        self.assertEqual(len(bullets), 2)
        self.assertIn("Subject One - Relation: sent_to_user", emails_block)
        self.assertIn("Body(3 lines, 280 chars max): Line 1 | Line 2 | Line 3", emails_block)
        self.assertIn("Subject Two - Relation: sent_by_user", emails_block)

    def test_email_html_calendar_and_emails_group_one_list_item_each(self):
        email_markup = render_email_digest_markup(self.payload)
        html = _rich_markup_to_html(email_markup)
        sections = self._email_html_sections(html)

        calendar_block = sections.get("Calendar", "")
        emails_block = sections.get("Emails", "")
        self.assertTrue(calendar_block, "Missing HTML section block for Calendar")
        self.assertTrue(emails_block, "Missing HTML section block for Emails")

        self.assertEqual(calendar_block.count("<li"), 2)
        self.assertEqual(emails_block.count("<li"), 2)

    def test_terminal_and_email_markup_section_order_is_consistent(self):
        terminal = render_terminal_digest(self.payload)
        email_markup = render_email_digest_markup(self.payload)

        terminal_sections = re.findall(r"\[bold cyan\]([^:]+):\[/bold cyan\]", terminal)
        email_sections = re.findall(r"^([A-Za-z &]+):", email_markup, flags=re.MULTILINE)

        expected_order = [
            "Location",
            "Date & Time",
            "Weather",
            "Key Highlights",
            "Tasks",
            "Calendar",
            "Emails",
            "News",
        ]
        self.assertEqual(terminal_sections, expected_order)
        self.assertEqual(email_sections, expected_order)


if __name__ == "__main__":
    unittest.main()
