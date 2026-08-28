# The Daily Tech Dispatch

A static, black-and-white newspaper-style page rebuilt daily from
[Hacker News](https://news.ycombinator.com) and [lobste.rs](https://lobste.rs).

- **Page One / Page Two** — the first two front pages of HN and the two hottest
  pages of lobste.rs, merged and de-duplicated by URL (tracking parameters,
  `www.`, trailing slashes and scheme differences are normalized away).
  Cross-posts get both source badges. HN job postings, polls, "Launch HN"
  posts and the monthly "Who is hiring?" / "Who wants to be hired?" threads
  are skipped.
- **Show HN** — the highest-scoring Show HN submissions of the last 24 hours.
- Each story shows a short text excerpt fetched from the linked page
  (silently skipped when a site blocks bots or serves non-HTML content).
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
`LOBSTERS_PAGES`, `SHOW_HN_LIMIT`), excerpt length (`LEDE_CHARS`), and the
number of recent editions linked on the front page (`RECENT_EDITIONS`).

## Roadmap

- AI-generated summaries replacing the raw text excerpts (data snapshots are
  already produced for this purpose).
