"""News action helper."""

from xml.etree import ElementTree
from urllib.parse import quote_plus

import requests


_LATEST_NEWS_RECORDS = []


def fetch_news_items(location: str, max_items: int = 8) -> list:
    """Fetch top news headlines for a location as structured records."""
    query = location.strip()
    if not query:
        raise ValueError("news[location] requires a non-empty location.")

    rss_url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    response = requests.get(rss_url, timeout=10)
    response.raise_for_status()

    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError as err:
        raise ValueError(f"Could not parse news feed for '{location}'.") from err

    items = root.findall("./channel/item")
    if not items:
        raise ValueError(f"No news results found for '{location}'.")

    records = []
    for item in items[:max_items]:
        title = (item.findtext("title") or "").strip()
        source = ((item.find("source").text if item.find("source") is not None else "") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        if not title:
            continue
        records.append(
            {
                "title": title,
                "source": source,
                "url": link,
                "published_at": pub_date,
            }
        )

    if not records:
        raise ValueError(f"No parseable headlines found for '{location}'.")

    return records


def current_news(location: str, max_items: int = 8) -> str:
    """Fetch top news headlines for a location via Google News RSS search."""
    global _LATEST_NEWS_RECORDS
    records = fetch_news_items(location, max_items=max_items)
    _LATEST_NEWS_RECORDS = records

    headlines = []
    for record in records:
        title = record["title"]
        source = record.get("source", "")
        link = record.get("url", "")
        headline = f"{title} ({source})" if source else title
        if link:
            headline += f" [[{link}]]"
        headlines.append(headline)

    return f"Top news for {location}: " + " | ".join(headlines)


def run_news_action(location: str) -> str:
    """Execute the news action and return a one-line observation."""
    return current_news(location)


def get_latest_news_records() -> list:
    """Return latest fetched news records from the most recent news action call."""
    return list(_LATEST_NEWS_RECORDS)
