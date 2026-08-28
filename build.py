#!/usr/bin/env python3
"""Build the daily edition of The Daily Tech Dispatch.

Pipeline: fetch feeds -> de-duplicate -> extract article text -> render HTML.
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from extract import extract_ledes
from fetchers import hn_front_page, hn_show_day, lobsters_pages
from render import render_page

ROOT = Path(__file__).resolve().parent
SITE_DIR = ROOT / "site"
DATA_DIR = ROOT / "data"
ARCHIVE_DIR = SITE_DIR / "archive"

HN_PAGES = 2
HN_PER_PAGE = 30
LOBSTERS_PAGES = 2
SHOW_HN_LIMIT = 30
LEDE_CHARS = 800
RECENT_EDITIONS = 7

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "fbclid", "gclid", "mc_cid", "mc_eid",
}

ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII",
         8: "VIII", 9: "IX", 10: "X"}


def normalize_url(url):
    """Canonical form used for de-duplication (https, no www, no tracking)."""
    parts = urlsplit(url)
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if k not in TRACKING_PARAMS]
    )
    return urlunsplit(("https", netloc, path, query, ""))


def story_key(story):
    if story.get("url"):
        return normalize_url(story["url"])
    return "~item/" + story["item_url"]


def dedupe(*groups):
    """Merge stories that point at the same URL, keeping first-seen rank."""
    by_key = {}
    ordered = []
    for group in groups:
        for story in group:
            key = story_key(story)
            existing = by_key.get(key)
            if existing is None:
                copy = dict(story)
                by_key[key] = copy
                ordered.append(copy)
            else:
                for src in story["sources"]:
                    if src not in existing["sources"]:
                        existing["sources"].append(src)
                existing["page"] = min(existing["page"], story["page"])
                existing["points"] = max(existing["points"], story["points"])
    return ordered


def finalize(stories, ledes):
    """Attach link/domain/lede to each story in place."""
    for story in stories:
        link = story.get("url") or story["item_url"]
        story["link"] = link
        host = urlsplit(link).netloc
        story["domain"] = host[4:] if host.startswith("www.") else host
        story["lede"] = ledes.get(story.get("url")) if story.get("url") else None


def recent_archives(edition_date):
    if not ARCHIVE_DIR.exists():
        return []
    dates = sorted(
        p.stem for p in ARCHIVE_DIR.glob("*.html") if p.stem != edition_date
    )
    dates.reverse()
    out = []
    for d in dates[:RECENT_EDITIONS]:
        day = datetime.strptime(d, "%Y-%m-%d")
        out.append({
            "date": d,
            "label": day.strftime("%A, %B ") + str(day.day) + day.strftime(", %Y"),
        })
    return out


def main():
    now = datetime.now(timezone.utc)
    edition_date = now.strftime("%Y-%m-%d")
    date_label = now.strftime("%A, %B ") + str(now.day) + now.strftime(", %Y")

    session = requests.Session()

    print("Fetching Hacker News front pages…")
    hn = hn_front_page(session, pages=HN_PAGES, per_page=HN_PER_PAGE)
    print(f"  {len(hn)} stories")

    print("Fetching lobste.rs pages…")
    lob = lobsters_pages(session, pages=LOBSTERS_PAGES)
    print(f"  {len(lob)} stories")

    print("Fetching Show HN (last 24h)…")
    show = dedupe(hn_show_day(session, limit=SHOW_HN_LIMIT))
    print(f"  {len(show)} stories")

    merged = dedupe(hn, lob)
    dupes = len(hn) + len(lob) - len(merged)
    print(f"Merged front pages: {len(merged)} stories ({dupes} cross-posts merged)")

    urls = [s["url"] for s in merged + show if s.get("url")]
    print(f"Extracting text from {len(set(urls))} article URLs…")
    ledes = extract_ledes(session, urls)
    print(f"  {len(ledes)} excerpts extracted")

    finalize(merged, ledes)
    finalize(show, ledes)

    lead = max(merged, key=lambda s: s["points"]) if merged else None
    rest = [s for s in merged if s is not lead]
    page_one = [s for s in rest if s["page"] == 1]
    page_two = [s for s in rest if s["page"] == 2]

    context = {
        "date_label": date_label,
        "edition_no": f"{now.timetuple().tm_yday:03d}",
        "volume": ROMAN.get(now.year - 2025, str(now.year - 2025)),
        "lead": lead,
        "page_one": page_one,
        "page_two": page_two,
        "show_hn": show,
        "archives": recent_archives(edition_date),
        "stats": {
            "total": len(merged) + len(show),
            "merged": dupes,
            "excerpts": len(ledes),
        },
    }

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    context["base"] = ""
    (SITE_DIR / "index.html").write_text(render_page(context), encoding="utf-8")
    context["base"] = "../"
    (ARCHIVE_DIR / f"{edition_date}.html").write_text(
        render_page(context), encoding="utf-8"
    )

    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / f"{edition_date}.json").write_text(
        json.dumps(
            {"edition": edition_date, "front_page": merged, "show_hn": show},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    static_src = ROOT / "static" / "style.css"
    shutil.copy(static_src, SITE_DIR / "style.css")

    print(f"Edition {edition_date} written to {SITE_DIR}/ "
          f"({len(page_one)} page-one, {len(page_two)} page-two, {len(show)} show)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
