#!/usr/bin/env python3
"""Build the daily edition of Log Tail.

Pipeline: fetch feeds -> de-duplicate -> extract article text -> render HTML.
"""

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from extract import extract_content
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
STORIES_PER_PAGE = 15

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
    """Merge stories that point at the same URL, summing their points."""
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
                existing["points"] += story["points"]
    return ordered


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


def finalize(stories, content):
    """Attach link/domain/lede/image to each story in place."""
    for story in stories:
        link = story.get("url") or story["item_url"]
        story["link"] = link
        host = urlsplit(link).netloc
        story["domain"] = host[4:] if host.startswith("www.") else host
        article = content.get(story.get("url")) if story.get("url") else None
        if article:
            story["lede"] = article["lede"]
            story["image"] = article["image"]
            story["image_full"] = article["full"]
        else:
            story["lede"] = None
            story["image"] = None
            story["image_full"] = False
            url = story.get("url") or ""
            if url.lower().split("?")[0].endswith(IMAGE_EXTENSIONS):
                # Unfetched direct image link — let the browser try it.
                story["image"] = url
                story["image_full"] = True


def recent_archives(edition_date):
    """Recent past editions (first page only) newest-first."""
    out = []
    if not ARCHIVE_DIR.exists():
        return out
    for path in ARCHIVE_DIR.glob("*.html"):
        stem = path.stem
        try:
            day = datetime.strptime(stem, "%Y-%m-%d")
        except ValueError:
            continue  # extra pages of an edition (e.g. 2026-08-28-p2.html)
        if stem == edition_date:
            continue
        out.append({
            "date": stem,
            "label": day.strftime("%A, %B ") + str(day.day) + day.strftime(", %Y"),
        })
    out.sort(key=lambda a: a["date"], reverse=True)
    return out[:RECENT_EDITIONS]


def main():
    args = sys.argv[1:]
    refresh = "--refresh" in args
    full_refresh = "--full-refresh" in args

    now = datetime.now(timezone.utc)
    edition_date = now.strftime("%Y-%m-%d")
    date_label = now.strftime("%A, %B ") + str(now.day) + now.strftime(", %Y")

    snapshot_path = DATA_DIR / f"{edition_date}.json"
    has_snapshot = snapshot_path.exists()

    # Resolve the build mode:
    #   --full-refresh  re-fetch feeds + re-extract articles
    #   --refresh       keep the feed snapshot, re-extract articles only
    #   (neither)       reuse the day's snapshot if present, else full fetch
    if full_refresh:
        do_full_fetch = True
        do_extract = True
    elif refresh:
        do_full_fetch = False
        do_extract = True
        if not has_snapshot:
            print(f"No snapshot for {edition_date}; performing a full fetch.")
            do_full_fetch = True
    elif has_snapshot:
        do_full_fetch = False
        do_extract = False
    else:
        do_full_fetch = True
        do_extract = True

    session = requests.Session() if do_extract else None
    dupes = 0

    if do_full_fetch:
        print("Fetching Hacker News front pages…")
        hn = hn_front_page(session, pages=HN_PAGES, per_page=HN_PER_PAGE)
        print(f"  {len(hn)} stories")

        print("Fetching lobste.rs pages…")
        lob = lobsters_pages(session, pages=LOBSTERS_PAGES)
        print(f"  {len(lob)} stories")

        print("Fetching Show HN (last 24h)…")
        show_raw = hn_show_day(session, limit=SHOW_HN_LIMIT)
        print(f"  {len(show_raw)} stories")

        # Drop Show HN submissions already on the front page — they're the same
        # HN item, so letting them through dedupe would double-count their
        # points.
        seen_items = {s["item_url"] for s in hn}
        show = [s for s in show_raw if s["item_url"] not in seen_items]

        merged = dedupe(hn, show, lob)
        dupes = len(hn) + len(show) + len(lob) - len(merged)
        print(f"Merged front pages: {len(merged)} stories "
              f"({dupes} cross-posts merged, ranked by points)")

        urls = [s["url"] for s in merged if s.get("url")]
        print(f"Extracting text and images from {len(set(urls))} article URLs…")
        content = extract_content(session, urls)

        finalize(merged, content)
        n_images = sum(1 for s in merged if s.get("image"))
        print(f"  {sum(1 for v in content.values() if v['lede'])} excerpts, "
              f"{n_images} images")
    elif refresh:
        print(f"Re-extracting articles from the {edition_date} snapshot…")
        snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
        merged = snap["front_page"]
        dupes = snap.get("dupes", 0)

        urls = [s["url"] for s in merged if s.get("url")]
        print(f"Extracting text and images from {len(set(urls))} article URLs…")
        content = extract_content(session, urls)

        finalize(merged, content)
        n_images = sum(1 for s in merged if s.get("image"))
        print(f"  {sum(1 for v in content.values() if v['lede'])} excerpts, "
              f"{n_images} images")
    else:
        print(f"Loading edition {edition_date} from snapshot "
              f"(no network)…")
        snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
        merged = snap["front_page"]
        dupes = snap.get("dupes", 0)
        n_images = sum(1 for s in merged if s.get("image"))

    # Stable ranking: equal-point stories break ties by item_url so the order
    # doesn't depend on which API response came back first. Harmless on the
    # snapshot path (already in this order) and makes a full-fetch rerun
    # deterministic against minor feed reordering.
    merged.sort(key=lambda s: (-s["points"], s["item_url"]))

    lead = merged[0] if merged else None
    front_page = merged[1:] if lead else merged

    chunks = [
        front_page[i:i + STORIES_PER_PAGE]
        for i in range(0, len(front_page), STORIES_PER_PAGE)
    ]
    if not chunks:
        chunks = [[]]
    n_pages = len(chunks)

    def page_href(base, page):
        """Filename for an edition page (1..n_pages)."""
        if base:  # archived edition
            if page == 1:
                return f"{edition_date}.html"
            return f"{edition_date}-p{page}.html"
        if page == 1:
            return "index.html"
        return f"page-{page}.html"

    # Page sequence: numbered front-page chunks.
    sequence = list(range(1, n_pages + 1))

    # Content hash of the stylesheet: cache-busting query param so browsers
    # pick up CSS changes immediately after a rebuild.
    css_version = hashlib.sha256(
        (ROOT / "static" / "style.css").read_bytes()
    ).hexdigest()[:8]

    def build_context(base, page):
        number = page
        pagination = [
            {
                "label": str(p),
                "href": page_href(base, p),
                "current": p == page,
            }
            for p in sequence
        ]
        index = sequence.index(page)
        return {
            "date_label": date_label,
            "edition_no": f"{now.timetuple().tm_yday:03d}",
            "volume": ROMAN.get(now.year - 2025, str(now.year - 2025)),
            "base": base,
            "css_version": css_version,
            "page_number": number,
            "lead": lead if page == 1 else None,
            "stories": chunks[page - 1],
            "pagination": pagination,
            "hrefs": {
                "front": page_href(base, 1),
                "prev": page_href(base, sequence[index - 1]) if index > 0 else None,
                "next": page_href(base, sequence[index + 1]) if index + 1 < len(sequence) else None,
            },
            "archives": recent_archives(edition_date) if page == 1 else [],
            "stats": {
                "total": len(merged),
                "merged": dupes,
                "excerpts": sum(1 for s in merged if s.get("lede")),
                "images": n_images,
            },
        }

    # Remove today's pages from previous runs so page counts can shrink.
    for pattern in ("page-*.html", "show-hn.html"):
        for stale in SITE_DIR.glob(pattern):
            stale.unlink()
    for pattern in (f"{edition_date}-p*.html", f"{edition_date}-show.html"):
        for stale in ARCHIVE_DIR.glob(pattern):
            stale.unlink()

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for base, directory in (("", SITE_DIR), ("../", ARCHIVE_DIR)):
        for page in sequence:
            html = render_page(build_context(base, page))
            (directory / page_href(base, page)).write_text(html, encoding="utf-8")

    DATA_DIR.mkdir(exist_ok=True)
    if do_extract:
        snapshot_path.write_text(
            json.dumps(
                {"edition": edition_date, "front_page": merged, "dupes": dupes},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    for asset in (ROOT / "static").iterdir():
        shutil.copy(asset, SITE_DIR / asset.name)

    print(f"Edition {edition_date} written to {SITE_DIR}/ "
          f"({len(front_page)} stories in {n_pages} pages of "
          f"{STORIES_PER_PAGE})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
