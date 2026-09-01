"""Fetch stories from Hacker News and lobste.rs."""

import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

HN_API = "https://hacker-news.firebaseio.com/v0"
HN_ITEM_URL = "https://news.ycombinator.com/item?id={id}"
ALGOLIA_API = "https://hn.algolia.com/api/v1/search"
LOBSTERS_URLS = ("https://lobste.rs/hottest.json", "https://lobste.rs/page/2.json")

# Extra IDs fetched so pages stay full after filtering.
FILTER_BUFFER = 15

# Launch HN posts (title match — no fixed author), and any non-official
# "Ask HN" hiring threads as a fallback. The official monthly threads are
# dropped by author ("whoishiring"); job postings and polls by item type.
EXCLUDED_TITLES = re.compile(
    r"^launch\shn\b|^ask\shn:.*\bwho\s+(is\s+hiring|wants\sto\s+be\shired)",
    re.IGNORECASE,
)
EXCLUDED_AUTHORS = {"whoishiring"}

# Recurring lobste.rs community threads that aren't news items.
LOBSTERS_EXCLUDED_TITLES = re.compile(
    r"^now\shiring\b|^what\sare\syou\sdoing\sthis\sweek(?:end)?\b",
    re.IGNORECASE,
)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
BROWSER_HEADERS = {"User-Agent": USER_AGENT}
TIMEOUT = (5, 15)


def _hn_item(session, item_id):
    for _ in range(2):
        try:
            data = session.get(f"{HN_API}/item/{item_id}.json", timeout=TIMEOUT).json()
            if data:
                return data
        except requests.RequestException:
            pass
    return None


def _keep_hn_item(item):
    if item.get("type") != "story":
        return False  # drops job postings and polls
    if item.get("by") in EXCLUDED_AUTHORS:
        return False  # official monthly hiring threads
    return not EXCLUDED_TITLES.search(item.get("title", ""))


def hn_front_page(session, pages=2, per_page=30):
    """Return the top `pages * per_page` stories from the HN front page."""
    ids = session.get(f"{HN_API}/topstories.json", timeout=TIMEOUT).json()
    ids = ids[: pages * per_page + FILTER_BUFFER]
    with ThreadPoolExecutor(max_workers=16) as pool:
        items = [
            d for d in pool.map(lambda i: _hn_item(session, i), ids)
            if d and _keep_hn_item(d)
        ]
    items = items[: pages * per_page]
    stories = []
    for d in items:
        stories.append(
            {
                "title": d.get("title", ""),
                "url": d.get("url"),
                "self_text": d.get("text"),  # HTML body of text-only posts
                "points": d.get("score", 0),
                "by": d.get("by", ""),
                "sources": ["HN"],
                "item_url": HN_ITEM_URL.format(id=d["id"]),
            }
        )
    return stories


def hn_show_day(session, hours=24, limit=30):
    """Return the top Show HN submissions from the last `hours` hours."""
    cutoff = int(time.time()) - hours * 3600
    resp = session.get(
        ALGOLIA_API,
        params={
            "tags": "show_hn",
            "hitsPerPage": limit,
            "numericFilters": f"created_at_i>{cutoff}",
        },
        timeout=TIMEOUT,
    )
    stories = []
    for hit in resp.json().get("hits", []):
        stories.append(
            {
                "title": hit.get("title", ""),
                "url": hit.get("url"),
                "self_text": hit.get("story_text"),  # HTML body, text posts
                "points": hit.get("points", 0),
                "by": hit.get("author", ""),
                "sources": ["HN"],
                "item_url": HN_ITEM_URL.format(id=hit["objectID"]),
            }
        )
    return stories


def lobsters_pages(session, pages=2):
    """Return the hottest lobste.rs stories across `pages` pages."""
    stories = []
    for url in LOBSTERS_URLS[:pages]:
        try:
            data = session.get(url, headers=BROWSER_HEADERS, timeout=TIMEOUT).json()
        except (requests.RequestException, ValueError):
            continue
        for s in data:
            if LOBSTERS_EXCLUDED_TITLES.search(s.get("title", "")):
                continue
            stories.append(
                {
                    "title": s.get("title", ""),
                    "url": s.get("url"),
                    # HTML body of text-only posts (empty string for links)
                    "self_text": s.get("description") or None,
                    "points": s.get("score", 0),
                    "by": s.get("submitter_user", ""),
                    "sources": ["L"],
                    "item_url": s.get("comments_url", "https://lobste.rs/"),
                }
            )
    return stories
