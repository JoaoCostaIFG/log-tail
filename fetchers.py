"""Fetch stories from Hacker News and lobste.rs."""

import time
from concurrent.futures import ThreadPoolExecutor

import requests

HN_API = "https://hacker-news.firebaseio.com/v0"
HN_ITEM_URL = "https://news.ycombinator.com/item?id={id}"
ALGOLIA_API = "https://hn.algolia.com/api/v1/search"
LOBSTERS_URLS = ("https://lobste.rs/hottest.json", "https://lobste.rs/page/2.json")

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


def hn_front_page(session, pages=2, per_page=30):
    """Return the top `pages * per_page` stories from the HN front page."""
    ids = session.get(f"{HN_API}/topstories.json", timeout=TIMEOUT).json()
    ids = ids[: pages * per_page]
    with ThreadPoolExecutor(max_workers=16) as pool:
        items = [d for d in pool.map(lambda i: _hn_item(session, i), ids) if d]
    stories = []
    for rank, d in enumerate(items):
        if d.get("type") not in ("story", "job"):
            continue
        stories.append(
            {
                "title": d.get("title", ""),
                "url": d.get("url"),
                "points": d.get("score", 0),
                "by": d.get("by", ""),
                "sources": ["HN"],
                "item_url": HN_ITEM_URL.format(id=d["id"]),
                "page": rank // per_page + 1,
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
                "points": hit.get("points", 0),
                "by": hit.get("author", ""),
                "sources": ["HN"],
                "item_url": HN_ITEM_URL.format(id=hit["objectID"]),
                "page": 1,
            }
        )
    return stories


def lobsters_pages(session, pages=2):
    """Return the hottest lobste.rs stories across `pages` pages."""
    stories = []
    for page_no, url in enumerate(LOBSTERS_URLS[:pages], start=1):
        try:
            data = session.get(url, headers=BROWSER_HEADERS, timeout=TIMEOUT).json()
        except (requests.RequestException, ValueError):
            continue
        for s in data:
            stories.append(
                {
                    "title": s.get("title", ""),
                    "url": s.get("url"),
                    "points": s.get("score", 0),
                    "by": s.get("submitter_user", ""),
                    "sources": ["L"],
                    "item_url": s.get("comments_url", "https://lobste.rs/"),
                    "page": page_no,
                }
            )
    return stories
