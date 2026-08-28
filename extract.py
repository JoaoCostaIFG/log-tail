"""Fetch article pages and extract a text lede and a lead image for each."""

import re
import struct
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

# A share image must be at least this big; smaller ones are placeholders
# (e.g. WordPress's blank 200x200 default) or tracker pixels.
MIN_IMAGE_WIDTH = 400
MIN_IMAGE_HEIGHT = 200
IMAGE_PROBE_BYTES = 262144


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


def _jpeg_size(data):
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + seglen
    return None


def _image_dimensions(data):
    """(width, height) for PNG/JPEG/GIF/WebP, or None if unknown."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:3] == b"GIF":
        return struct.unpack("<HH", data[6:10])
    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if data[12:16] == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if data[12:16] == b"VP8L":
            bits = struct.unpack("<I", data[21:25])[0]
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if data[12:16] == b"VP8X":
            w = int.from_bytes(data[24:27], "little") + 1
            h = int.from_bytes(data[27:30], "little") + 1
            return w, h
    if b"<svg" in data[:1024].lower():
        return None  # vector; no fixed dimensions — treated as valid
    return None


def _valid_share_image(session, url):
    """Reject placeholder/tracker images; True means OK to use.

    Unverifiable images (blocked, timing out) are kept optimistically —
    the reader's browser may still load them.
    """
    try:
        with session.get(
            url, headers=BROWSER_HEADERS, timeout=(5, 12), stream=True
        ) as resp:
            if resp.status_code != 200:
                return True
            ctype = resp.headers.get("Content-Type", "").lower()
            if ctype and not ctype.startswith("image/"):
                return False
            chunks = []
            size = 0
            for chunk in resp.iter_content(chunk_size=8192):
                chunks.append(chunk)
                size += len(chunk)
                if size >= IMAGE_PROBE_BYTES:
                    break
            data = b"".join(chunks)
    except Exception:
        return True
    if len(data) < 1024:
        return False  # tracker pixels
    if b"<svg" in data[:1024].lower():
        return True
    dims = _image_dimensions(data)
    if dims is None:
        return False  # not a recognizable raster image
    w, h = dims
    return w >= MIN_IMAGE_WIDTH and h >= MIN_IMAGE_HEIGHT


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
    if image and not _valid_share_image(session, image):
        image = None
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
