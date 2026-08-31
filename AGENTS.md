# AGENTS.md

Static newspaper-style site built daily from HN + lobste.rs. Pure Python (no framework); deps in `requirements.txt`.

## Commands

```sh
.venv/bin/pip install -r requirements.txt   # first setup (python3 -m venv .venv)
.venv/bin/python build.py                   # build today's edition
python3 -m http.server -d site              # preview
```

There is no test suite, linter, or formatter — verify changes by running `build.py` (a snapshot-based run needs no network; see below).

## Build modes (build.py)

`build.py` has three modes keyed off the day's snapshot in `data/YYYY-MM-DD.json` (git-ignored):

- default: reuse today's snapshot if present (no network); otherwise full fetch + extract
- `--refresh`: keep the snapshot, re-fetch article text/images only
- `--full-refresh`: re-fetch feeds and re-extract everything (overwrites the snapshot)

A plain rerun that seems to skip fetching is normal, not a bug.

## Architecture

Pipeline in `build.py`: `fetchers.py` (HN Firebase + Algolia APIs, lobste.rs JSON; also owns filter rules and `BROWSER_HEADERS`) → dedupe/cross-post merge in `build.py` → `extract.py` (article lede + og:image validation, charset sniffing) → `render.py` (Jinja2, `templates/page.html.j2`). Tuning knobs (feed sizes, stories/page, excerpt length) are constants at the top of `build.py`.

Output goes to `site/` (git-ignored): `index.html`, `page-N.html`, `archive/YYYY-MM-DD.html` (+ `-pN` extra pages), plus `static/` assets. `.nojekyll` is emitted because article excerpts can contain Liquid-like braces.

## site branch / deploy

- `main` is code-only; generated HTML never lands in its history.
- CI (`.github/workflows/build-daily-edition.yml`) restores old editions from the `site` branch, builds, and force-pushes `site` as a single squashed commit — that push is the Pages deploy. Never commit `site/` or `data/` to `main`.
- For a full local build with archived editions, restore them first:
  `git fetch origin site && mkdir -p site && git archive origin/site | tar -x -C site`
- CSS changes need no manual version bump — `build.py` cache-busts via a content hash of `static/style.css`.

## Misc

- `tools/make_icons.py` regenerates the favicon PNGs in `static/` from the same geometry as `favicon.svg` (stdlib only, run manually).
