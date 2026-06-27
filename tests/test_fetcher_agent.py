import unittest
from unittest.mock import patch

from fetcher_agent import fetcher_agent


class FetcherAgentTests(unittest.TestCase):
    @patch("fetcher_agent.fetch_open_tasks")
    @patch("fetcher_agent.fetch_recent_emails")
    @patch("fetcher_agent.fetch_upcoming_events")
    @patch("fetcher_agent.fetch_news_items")
    @patch("fetcher_agent.fetch_weather_snapshot")
    @patch("fetcher_agent.resolve_location_details")
    @patch("fetcher_agent.current_location")
    @patch("fetcher_agent.format_location")
    def test_fetcher_agent_populates_raw_fetched_data_only(
        self,
        mock_format_location,
        mock_current_location,
        mock_resolve_location,
        mock_fetch_weather,
        mock_fetch_news,
        mock_fetch_calendar,
        mock_fetch_emails,
        mock_fetch_tasks,
    ):
        mock_current_location.return_value = {
            "city": "Pittsburgh",
            "region": "PA",
            "country": "US",
        }
        mock_format_location.return_value = "Pittsburgh, PA, US"
        mock_resolve_location.return_value = {
            "name": "Pittsburgh, Pennsylvania, United States",
            "latitude": 40.4406,
            "longitude": -79.9959,
            "timezone": "America/New_York",
        }
        mock_fetch_weather.return_value = {
            "description": "Clear sky",
            "temperature_c": 22.5,
            "apparent_temperature_c": 23.1,
            "high_c": 26.0,
            "low_c": 18.0,
            "wind_kmh": 6.0,
            "weather_code": 0,
        }
        mock_fetch_news.return_value = [{"title": "Headline", "source": "Source", "url": "u", "published_at": "p"}]
        mock_fetch_calendar.return_value = [{"id": "evt-1", "summary": "Meeting"}]
        mock_fetch_emails.return_value = [{"id": "msg-1", "subject": "Hello"}]
        mock_fetch_tasks.return_value = ("list-1", "Tasks", [{"id": "task-1", "title": "Do thing"}])

        initial_state = {
            "retrieved_corrections": [{"id": "corr-1"}],
            "candidate_rankings": [{"id": "rank-1"}],
        }

        updated = fetcher_agent(initial_state)

        self.assertIn("raw_fetched_data", updated)
        self.assertEqual(updated["retrieved_corrections"], initial_state["retrieved_corrections"])
        self.assertEqual(updated["candidate_rankings"], initial_state["candidate_rankings"])

        raw = updated["raw_fetched_data"]
        self.assertIn("location", raw)
        self.assertIn("weather", raw)
        self.assertIn("news", raw)
        self.assertIn("calendar_events", raw)
        self.assertIn("emails", raw)
        self.assertIn("tasks", raw)
        self.assertIn("fetch_errors", raw)
        self.assertIn("fetched_at_utc", raw)
        self.assertEqual(raw["fetch_errors"], {})

    @patch("fetcher_agent.fetch_open_tasks")
    @patch("fetcher_agent.fetch_recent_emails")
    @patch("fetcher_agent.fetch_upcoming_events")
    @patch("fetcher_agent.fetch_news_items")
    @patch("fetcher_agent.fetch_weather_snapshot")
    @patch("fetcher_agent.resolve_location_details")
    @patch("fetcher_agent.current_location")
    @patch("fetcher_agent.format_location")
    def test_fetcher_agent_collects_partial_errors_without_stopping(
        self,
        mock_format_location,
        mock_current_location,
        mock_resolve_location,
        mock_fetch_weather,
        mock_fetch_news,
        mock_fetch_calendar,
        mock_fetch_emails,
        mock_fetch_tasks,
    ):
        mock_current_location.return_value = {
            "city": "Pittsburgh",
            "region": "PA",
            "country": "US",
        }
        mock_format_location.return_value = "Pittsburgh, PA, US"
        mock_resolve_location.return_value = {
            "name": "Pittsburgh, Pennsylvania, United States",
            "latitude": 40.4406,
            "longitude": -79.9959,
            "timezone": "America/New_York",
        }
        mock_fetch_weather.side_effect = RuntimeError("weather failed")
        mock_fetch_news.return_value = [{"title": "Headline", "source": "Source", "url": "u", "published_at": "p"}]
        mock_fetch_calendar.return_value = [{"id": "evt-1", "summary": "Meeting"}]
        mock_fetch_emails.return_value = [{"id": "msg-1", "subject": "Hello"}]
        mock_fetch_tasks.return_value = ("list-1", "Tasks", [{"id": "task-1", "title": "Do thing"}])

        updated = fetcher_agent({})
        raw = updated["raw_fetched_data"]

        self.assertIn("weather", raw)
        self.assertIsNone(raw["weather"]["temperature_c"])
        self.assertIn("weather", raw["fetch_errors"])
        self.assertEqual(raw["news"], [{"title": "Headline", "source": "Source", "url": "u", "published_at": "p"}])
        self.assertEqual(raw["calendar_events"], [{"id": "evt-1", "summary": "Meeting"}])
        self.assertEqual(raw["emails"], [{"id": "msg-1", "subject": "Hello"}])
        self.assertEqual(raw["tasks"], [{"id": "task-1", "title": "Do thing"}])


if __name__ == "__main__":
    unittest.main()
