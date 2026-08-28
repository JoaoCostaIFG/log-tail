"""Fetch article pages and extract a text lede and a lead image for each."""

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

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

IMAGE_META_KEYS = {
    "og:image",
    "og:image:url",
    "og:image:secure_url",
    "twitter:image",
    "twitter:image:src",
}


def _clean_text(soup):
    """Return (text, has_prose). has_prose is False for pages with no real
    article paragraphs (e.g. webcomics, photo pages) — a signal that the
    page is focused on its image."""
    for tag in soup.find_all(list(SKIP_TAGS)):
        tag.decompose()
    paragraphs = []
    for p in soup.find_all("p"):
        text = re.sub(r"\s+", " ", p.get_text(" ")).strip()
        if len(text) >= 40:
            paragraphs.append(text)
    prose = " ".join(paragraphs)
    if len(prose) >= 200:
        return prose, True
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return text, False


def _truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.-–—") + " …"


def _extract_image(soup, base_url):
    """Best share image for the page: og:image > twitter:image > image_src."""
    metas = []
    for meta in soup.find_all("meta"):
        key = (meta.get("property") or meta.get("name") or "").lower()
        if key in IMAGE_META_KEYS:
            metas.append((key, (meta.get("content") or "").strip()))
    links = [
        (link.get("href") or "").strip()
        for link in soup.find_all("link")
        if "image_src" in [r.lower() for r in (link.get("rel") or [])]
    ]
    og_keys = ("og:image", "og:image:url", "og:image:secure_url")
    candidates = (
        [c for k, c in metas if k in og_keys and c]
        + [c for k, c in metas if k not in og_keys and c]
        + [c for c in links if c]
    )
    for src in candidates:
        url = urljoin(base_url, src)
        if url.startswith(("http://", "https://")):
            return url
    return None


def fetch_article(session, url, max_chars=800):
    """Return {"lede", "image", "full"} for the page at `url`.

    `full` is True when the page is focused on an image (a direct image
    link, or a page with a share image but no article prose) — those are
    displayed uncropped instead of as thumbnails.
    """
    try:
        with session.get(
            url,
            headers=BROWSER_HEADERS,
            timeout=(5, 12),
            stream=True,
            allow_redirects=True,
        ) as resp:
            ctype = resp.headers.get("Content-Type", "").lower()
            if resp.status_code != 200:
                return {"lede": None, "image": None, "full": False}
            if ctype.startswith("image/"):
                # The link points straight at the image itself.
                return {"lede": None, "image": url, "full": True}
            if not any(t in ctype for t in TEXT_CONTENT_TYPES):
                return {"lede": None, "image": None, "full": False}
            chunks = []
            size = 0
            for chunk in resp.iter_content(chunk_size=16384):
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_BYTES:
                    break
            html = b"".join(chunks).decode(resp.encoding or "utf-8", "replace")
    except Exception:
        return {"lede": None, "image": None, "full": False}
    soup = BeautifulSoup(html, "html.parser")
    text, has_prose = _clean_text(soup)
    image = _extract_image(soup, url)
    return {
        "lede": _truncate(text, max_chars) if text else None,
        "image": image,
        "full": bool(image) and not has_prose,
    }


def extract_content(session, urls, workers=16):
    """Concurrently fetch articles; returns {url: {"lede", "image"}}.

    Pages that fail entirely are omitted.
    """
    unique = sorted(set(urls))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_article, session, u): u for u in unique}
        results = {}
        for future in futures:
            url = futures[future]
            try:
                article = future.result()
            except Exception:
                article = None
            if article and (article["lede"] or article["image"]):
                results[url] = article
    return results
