# Log Tail

A static, black-and-white newspaper-style page rebuilt daily from
[Hacker News](https://news.ycombinator.com) and [lobste.rs](https://lobste.rs).

- **Front Page** — the first two front pages of HN and the two hottest pages
  of lobste.rs, merged into a single list ranked by points. Cross-posted
  URLs are de-duplicated (tracking parameters, `www.`, trailing slashes and
  scheme differences normalized away) with their points summed, so a story
  popular on both sites ranks higher. HN job postings, polls, "Launch HN"
  posts and the monthly "Who is hiring?" / "Who wants to be hired?" threads
  are skipped.
- The edition is paginated like a print newspaper: 15 stories per page
  (the top story leads page one) and Show HN as the back page, with
  prev/next and page-number navigation.
- **Show HN** — the highest-scoring Show HN submissions of the last 24 hours.
- Each story shows a short text excerpt fetched from the linked page
  (silently skipped when a site blocks bots or serves non-HTML content).
- Stories carry an image when the linked site provides one (og:image /
  twitter:image): hotlinked with `no-referrer`, lazy-loaded, rendered in
  black & white via a CSS grayscale filter, and self-removed if the host
  blocks hotlinking. Candidates are validated at build time — placeholder
  and tracker images (e.g. WordPress's blank 200×200 default, sub-1KB
  pixels) are rejected, requiring ≥400×200 raster dimensions. Image-focused
  posts — direct image links, webcomics, photo pages (detected as "has
  share image, no article prose") — are shown uncropped instead of as
  cropped thumbnails.
- Every edition is archived at `site/archive/YYYY-MM-DD.html` and linked from
  the front page. Raw data snapshots land in `data/YYYY-MM-DD.json`
  (git-ignored) — the future AI-summary step will consume those.

## Local run

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python build.py
# serve for a look: python3 -m http.server -d site
```

## Daily rebuild & hosting (GitHub Actions + Pages)

1. Push this repo to GitHub.
2. In repo **Settings → Pages**, set **Source** to *GitHub Actions*.
3. The workflow (`.github/workflows/build.yml`) runs daily at 13:00 UTC and on
   manual dispatch (`workflow_dispatch`), builds the edition, commits new
   archive files back to the default branch, and deploys `site/` to Pages.

## Tuning

Knobs live at the top of `build.py`: feed sizes (`HN_PAGES`, `HN_PER_PAGE`,
`LOBSTERS_PAGES`, `SHOW_HN_LIMIT`), excerpt length (`LEDE_CHARS`), stories
per page (`STORIES_PER_PAGE`), and the number of recent editions linked on
the front page (`RECENT_EDITIONS`).

## Roadmap

- AI-generated summaries replacing the raw text excerpts (data snapshots are
  already produced for this purpose).
