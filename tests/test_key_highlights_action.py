import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from actions.key_highlights_action import run_key_highlights_action


class KeyHighlightsActionTests(unittest.TestCase):
    @patch("actions.key_highlights_action.fetch_upcoming_events")
    @patch("actions.key_highlights_action.fetch_recent_emails")
    @patch("actions.key_highlights_action.fetch_open_tasks")
    def test_falls_back_to_due_soon_and_overdue_tasks_when_no_overlaps(
        self,
        mock_fetch_open_tasks,
        mock_fetch_recent_emails,
        mock_fetch_upcoming_events,
    ):
        mock_fetch_upcoming_events.return_value = [
            {
                "summary": "Calendar Test 1",
                "start": "2026-06-06",
                "attendees": [
                    {
                        "email": "someone@example.com",
                        "is_user": False,
                        "is_vip": False,
                        "response_status": "accepted",
                    }
                ],
            }
        ]
        mock_fetch_recent_emails.return_value = [
            {
                "subject": "Unrelated message",
                "direction": "sent_to_user",
                "from_addresses": ["other@example.com"],
                "to_addresses": ["user@example.com"],
                "cc_addresses": [],
            }
        ]
        mock_fetch_open_tasks.return_value = (
            "tasklist-1",
            "John's list",
            [
                {
                    "id": "t1",
                    "title": "Overdue follow-up",
                    "notes": "",
                    "due": "2024-01-01T00:00:00.000Z",
                    "owner_label": "user@example.com",
                },
                {
                    "id": "t2",
                    "title": "No due date task",
                    "notes": "",
                    "due": None,
                    "owner_label": "user@example.com",
                },
            ],
        )

        result = run_key_highlights_action()
        self.assertIn("Key highlights:", result)
        self.assertIn("overdue task:", result)

    @patch("actions.key_highlights_action.fetch_upcoming_events")
    @patch("actions.key_highlights_action.fetch_recent_emails")
    @patch("actions.key_highlights_action.fetch_open_tasks")
    def test_highlights_critical_unread_email_when_no_overlap(
        self,
        mock_fetch_open_tasks,
        mock_fetch_recent_emails,
        mock_fetch_upcoming_events,
    ):
        mock_fetch_upcoming_events.return_value = [
            {
                "summary": "Calendar Test 1",
                "start": "2026-06-06",
                "attendees": [
                    {
                        "email": "attendee@example.com",
                        "is_user": False,
                        "is_vip": False,
                        "response_status": "accepted",
                    }
                ],
            }
        ]
        mock_fetch_recent_emails.return_value = [
            {
                "subject": "Action Needed: Contract Signature",
                "date": "Mon, 01 Jun 2026 08:00:00 +0000",
                "from_addresses": ["vip@example.com"],
                "to_addresses": ["user@example.com"],
                "cc_addresses": [],
                "direction": "sent_to_user",
                "vip_matches": ["vip@example.com"],
                "body_preview": "Please sign immediately",
                "is_unread": True,
            }
        ]
        mock_fetch_open_tasks.return_value = ("tasklist-1", "John's list", [])

        result = run_key_highlights_action()
        self.assertIn("critical unread email:", result)
        self.assertIn("Action Needed: Contract Signature", result)

    @patch("actions.key_highlights_action.fetch_upcoming_events")
    @patch("actions.key_highlights_action.fetch_recent_emails")
    @patch("actions.key_highlights_action.fetch_open_tasks")
    def test_highlights_events_starting_within_next_24_hours(
        self,
        mock_fetch_open_tasks,
        mock_fetch_recent_emails,
        mock_fetch_upcoming_events,
    ):
        soon_start = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
        mock_fetch_upcoming_events.return_value = [
            {
                "summary": "Customer Check-in",
                "start": soon_start,
                "attendees": [
                    {
                        "email": "attendee@example.com",
                        "is_user": False,
                        "is_vip": False,
                        "response_status": "accepted",
                    }
                ],
            }
        ]
        mock_fetch_recent_emails.return_value = []
        mock_fetch_open_tasks.return_value = ("tasklist-1", "John's list", [])

        result = run_key_highlights_action()
        self.assertIn("upcoming event in next 24h:", result)
        self.assertIn("Customer Check-in", result)


if __name__ == "__main__":
    unittest.main()
