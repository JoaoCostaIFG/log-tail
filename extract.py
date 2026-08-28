"""Fetch article pages and extract a short text lede for each."""

import re
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup

from fetchers import BROWSER_HEADERS

MAX_BYTES = 2_000_000
TEXT_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml")
SKIP_TAGS = (
    "script",
    "style",
    "noscript",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "svg",
    "iframe",
    "button",
)


def _clean_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(list(SKIP_TAGS)):
        tag.decompose()
    paragraphs = []
    for p in soup.find_all("p"):
        text = re.sub(r"\s+", " ", p.get_text(" ")).strip()
        if len(text) >= 40:
            paragraphs.append(text)
    text = " ".join(paragraphs)
    if len(text) < 200:
        text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return text


def _truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.-–—") + " …"


def fetch_lede(session, url, max_chars=800):
    """Return a text excerpt of the page at `url`, or None if unavailable."""
    try:
        with session.get(
            url,
            headers=BROWSER_HEADERS,
            timeout=(5, 12),
            stream=True,
            allow_redirects=True,
        ) as resp:
            ctype = resp.headers.get("Content-Type", "").lower()
            if resp.status_code != 200 or not any(
                t in ctype for t in TEXT_CONTENT_TYPES
            ):
                return None
            chunks = []
            size = 0
            for chunk in resp.iter_content(chunk_size=16384):
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_BYTES:
                    break
            html = b"".join(chunks).decode(resp.encoding or "utf-8", "replace")
    except Exception:
        return None
    text = _clean_text(html)
    if not text:
        return None
    return _truncate(text, max_chars)


def extract_ledes(session, urls, workers=16):
    """Concurrently fetch ledes; returns {url: lede} with failures omitted."""
    unique = sorted(set(urls))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_lede, session, u): u for u in unique}
        ledes = {}
        for future in futures:
            url = futures[future]
            try:
                lede = future.result()
            except Exception:
                lede = None
            if lede:
                ledes[url] = lede
    return ledes
