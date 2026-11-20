# browse-bleau
POC to browse boulders and get inspired for a day out.

Pick a Fontainebleau sector and a grade range, then flip through the beta
videos for each boulder, ranked by number of public ascents on
[bleau.info](https://bleau.info).

## How it works

```
scraper/scrape.py  ──(polite, cached)──▶  data/*.json  ──▶  index.html + app.js
```

* **Scraper** (Python 3 stdlib only). bleau.info has no public API, so the
  scraper reads the area listing, and only for boulders flagged as having
  video it fetches the boulder page (ascent count, rating) and the video
  list. It honours robots.txt `Crawl-delay: 5` and caches every response in
  `scraper/.cache/`, so re-runs and grade-range changes cost nothing.
* **Frontend** is static HTML/JS, no build step. View state lives in the URL
  hash (`#area=canard&min=6a&max=7a&i=3`) so views can be bookmarked.

## Usage

```bash
# list all area slugs (written to data/areas_index.json)
python3 scraper/scrape.py --list-areas

# scrape one or more sectors; --min/--max limit how many pages are fetched
python3 scraper/scrape.py cuvier canard --min 5+ --max 7a

# serve locally (YouTube embeds don't work from file://)
python3 -m http.server 8000
# open http://localhost:8000
```

Expect roughly 2 requests × 5 s per boulder with video, so a large sector
over a wide grade range takes several minutes. Results are merged into the
existing `data/areas/<slug>.json`, so scraping additional grade ranges later
extends the data rather than replacing it.

Keyboard: ←/→ previous/next boulder, ↑/↓ previous/next video for that boulder.

## Ideas / next steps

* Mark boulders as done / todo (localStorage first; later import a
  bleau.info ticklist from a profile page) and filter out done ones.
* Filter by style (sit start, traverse, slab…) — `type` is already scraped.
* Multi-sector browsing for a day out.
