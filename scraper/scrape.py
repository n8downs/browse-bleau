#!/usr/bin/env python3
"""Scrape boulder + beta-video data from bleau.info into static JSON.

Polite by design: honours robots.txt Crawl-delay (5s), caches every response
on disk so re-runs are free, and only fetches boulder pages for problems that
the area listing marks as having video.

Usage:
    python3 scraper/scrape.py --list-areas            # refresh data/areas_index.json
    python3 scraper/scrape.py cuvier canard           # scrape sectors (all grades)
    python3 scraper/scrape.py cuvier --min 6a --max 7a

Output:
    data/areas_index.json      all bleau.info areas (slug, name, region)
    data/areas.json            areas that have been scraped (drives the UI)
    data/areas/<slug>.json     boulders + videos for one area
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://bleau.info"
USER_AGENT = "browse-bleau-poc/0.1 (personal beta-video browser)"
CRAWL_DELAY = 5.0

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
DATA_DIR = ROOT / "data"

_last_request = 0.0


# --------------------------------------------------------------------------- #
# HTTP with cache + rate limit
# --------------------------------------------------------------------------- #
def fetch(path: str, *, xhr: bool = False, refresh: bool = False) -> str:
    url = path if path.startswith("http") else BASE + path
    key = hashlib.sha1(f"{url}|{xhr}".encode()).hexdigest()
    cache_file = CACHE_DIR / f"{key}.html"
    if cache_file.exists() and not refresh:
        return cache_file.read_text(encoding="utf-8")

    global _last_request
    wait = CRAWL_DELAY - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en"}
    if xhr:
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Accept"] = "text/javascript, application/javascript, */*"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            break
        except Exception as exc:  # network hiccup: back off and retry
            if attempt == 3:
                raise
            print(f"  ! {exc} — retrying", file=sys.stderr)
            time.sleep(CRAWL_DELAY * (attempt + 2))
    _last_request = time.monotonic()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(body, encoding="utf-8")
    return body


def text(s: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


# --------------------------------------------------------------------------- #
# Grades
# --------------------------------------------------------------------------- #
GRADE_RE = re.compile(r"^([1-9])([abc])?(\+)?(-)?$", re.I)


def grade_value(grade: str | None) -> float | None:
    """Map a Fontainebleau grade to a sortable number (6a=36, 6a+=37, 6b=38...)."""
    if not grade:
        return None
    m = GRADE_RE.match(grade.strip())
    if not m:
        return None
    num, letter, plus, minus = m.groups()
    v = int(num) * 6
    if letter:
        v += "abc".index(letter.lower()) * 2
    if plus:
        v += 1
    if minus:
        v -= 0.5
    return v


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #
def parse_areas_index(page: str) -> list[dict]:
    areas = []
    start = page.find("area_by_regions")
    body = page[start:]
    region = None
    for m in re.finditer(
        r'<div><strong>(.*?)</strong></div>|<a href="/([A-Za-z0-9_.\-]+)">\s*(.*?)\s*</a>',
        body,
        re.S,
    ):
        if m.group(1) is not None:
            region = text(m.group(1))
        elif region and not m.group(2).startswith(("toggle_favarea", "faq", "privacy")):
            areas.append({"slug": m.group(2), "name": text(m.group(3)), "region": region})
    return areas


VSR_RE = re.compile(r'<div class="vsr">(.*?)</div>', re.S)


def parse_area(slug: str, page: str) -> dict:
    title = re.search(r"<h3>\s*(.*?)\s*<small", page, re.S)
    name = text(title.group(1)) if title else slug
    boulders = []
    for m in VSR_RE.finditer(page):
        block = m.group(1)
        link = re.search(r'<a href="(/[^"]+/(\d+)\.html)">(.*?)</a>(.*)', block, re.S)
        if not link:
            continue
        href, bid, bname, rest = link.groups()
        # grade is the bare text right after the link, before the next tag
        g = re.match(r"\s*([^<\s]+)", rest)
        grade = g.group(1) if g else None
        alt = re.search(r'<span class="ag">(.*?)</span>', rest)
        btype = re.search(r'<span class="btype">(.*?)</span>', rest, re.S)
        setter = re.search(r"<em>(.*?)</em>", rest, re.S)
        boulders.append(
            {
                "id": bid,
                "name": text(bname),
                "url": BASE + href,
                "path": href,
                "grade": grade,
                "grade_value": grade_value(grade),
                "alt_grade": text(alt.group(1)) if alt else None,
                "stars": rest.count("glyphicon-star\"") + 0.5 * rest.count("glyphicon-star half"),
                "type": text(btype.group(1)) if btype else "",
                "setter": text(setter.group(1)) if setter else "",
                "has_video": "glyphicon-film" in rest,
            }
        )
    return {"slug": slug, "name": name, "boulders": boulders}


def _total(label: str, page: str) -> int | None:
    m = re.search(label + r".*?\((\d+) total\)", page, re.S)
    return int(m.group(1)) if m else None


def parse_boulder(page: str) -> dict:
    rating = re.search(r"([\d.]+) Stars", page)
    return {
        "ascents": _total("Public ascents", page) or 0,
        "rating": float(rating.group(1)) if rating else None,
        "ratings_count": _total("Average rating", page),
    }


VIDEO_BLOCK_RE = re.compile(r'class="col-md-12 mp4-container">(.*?)(?=<div class="row|\Z)', re.S)


def parse_videos(fragment: str) -> list[dict]:
    videos = []
    for m in VIDEO_BLOCK_RE.finditer(fragment):
        block = m.group(1)
        climber = re.search(r'<a href="/profiles/[^"]+">(.*?)</a>', block)
        start = re.search(r"<div>[^<]*?(\d{1,2}):(\d{2})</div>", block)
        start_s = int(start.group(1)) * 60 + int(start.group(2)) if start else 0
        v = {"climber": text(climber.group(1)) if climber else None, "start": start_s}
        iframe = re.search(r'<iframe[^>]+src="([^"]+)"', block)
        mp4 = re.search(r'<source src="([^"]+)"', block)
        insta = re.search(r'class="insta_e"[^>]*>(.*?)<', block, re.S)
        if iframe:
            src = html.unescape(iframe.group(1))
            if src.startswith("//"):
                src = "https:" + src
            host = urllib.parse.urlparse(src).netloc
            v["kind"] = "youtube" if "youtu" in host else "vimeo" if "vimeo" in host else "iframe"
            v["src"] = src
        elif mp4:
            v["kind"] = "mp4"
            v["src"] = html.unescape(mp4.group(1))
        elif insta:
            v["kind"] = "link"
            v["src"] = text(insta.group(1))
        else:
            continue
        videos.append(v)
    return videos


def unescape_js(s: str) -> str:
    """Undo the escaping in the `$(...).before('...')` XHR responses."""
    m = re.search(r"\.before\('(.*)'\)", s, re.S)
    if not m:
        return ""
    body = m.group(1)
    return (
        body.replace("\\n", "\n")
        .replace('\\"', '"')
        .replace("\\'", "'")
        .replace("\\/", "/")
    )


def fetch_videos(boulder_path: str, refresh: bool) -> list[dict]:
    base = boulder_path[: -len(".html")]
    videos: list[dict] = []
    seen: set[str] = set()
    offset = 0
    while True:
        resp = fetch(f"{base}/more_videos?offset={offset}&locale=en", xhr=True, refresh=refresh)
        batch = parse_videos(unescape_js(resp))
        new = [v for v in batch if v["src"] not in seen]
        if not new:
            break
        for v in new:
            seen.add(v["src"])
        videos.extend(new)
        nxt = re.search(r"data\('offset', (\d+)\)", resp)
        if not nxt or int(nxt.group(1)) <= offset:
            break
        offset = int(nxt.group(1))
    return videos


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def scrape_area(slug: str, gmin: float | None, gmax: float | None, refresh: bool) -> dict:
    print(f"[{slug}] area page")
    area = parse_area(slug, fetch(f"/{slug}?locale=en", refresh=refresh))
    targets = [
        b
        for b in area["boulders"]
        if b["has_video"]
        and (gmin is None or (b["grade_value"] or 0) >= gmin)
        and (gmax is None or (b["grade_value"] or 99) <= gmax)
    ]
    print(f"[{slug}] {len(area['boulders'])} boulders, {len(targets)} with video in range")

    # Keep data from previous runs so narrower grade ranges don't drop boulders.
    out_file = DATA_DIR / "areas" / f"{slug}.json"
    previous = {}
    if out_file.exists():
        previous = {b["id"]: b for b in json.loads(out_file.read_text())["boulders"]}

    for i, b in enumerate(targets, 1):
        print(f"[{slug}] {i}/{len(targets)} {b['grade']:>4} {b['name']}")
        b.update(parse_boulder(fetch(b["path"] + "?locale=en", refresh=refresh)))
        b["videos"] = fetch_videos(b["path"], refresh)
        previous[b["id"]] = b

    boulders = sorted(
        (b for b in previous.values() if b.get("videos")),
        key=lambda b: -b.get("ascents", 0),
    )
    for b in boulders:
        b.pop("path", None)
        b.pop("has_video", None)
    result = {
        "slug": slug,
        "name": area["name"],
        "url": f"{BASE}/{slug}",
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "boulders": boulders,
    }
    write_json(out_file, result)
    return result


def update_manifest() -> None:
    entries = []
    for f in sorted((DATA_DIR / "areas").glob("*.json")):
        a = json.loads(f.read_text())
        entries.append(
            {
                "slug": a["slug"],
                "name": a["name"],
                "boulders": len(a["boulders"]),
                "videos": sum(len(b["videos"]) for b in a["boulders"]),
                "scraped_at": a["scraped_at"],
            }
        )
    entries.sort(key=lambda e: e["name"].lower())
    write_json(DATA_DIR / "areas.json", entries)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("areas", nargs="*", help="area slugs as in bleau.info/<slug>")
    ap.add_argument("--min", help="minimum grade to fetch, e.g. 6a")
    ap.add_argument("--max", help="maximum grade to fetch, e.g. 7a+")
    ap.add_argument("--list-areas", action="store_true", help="refresh data/areas_index.json")
    ap.add_argument("--refresh", action="store_true", help="ignore the on-disk cache")
    args = ap.parse_args()

    if args.list_areas:
        areas = parse_areas_index(fetch("/areas_by_region?locale=en", refresh=args.refresh))
        write_json(DATA_DIR / "areas_index.json", areas)
        print(f"{len(areas)} areas written to data/areas_index.json")

    gmin, gmax = grade_value(args.min), grade_value(args.max)
    if (args.min and gmin is None) or (args.max and gmax is None):
        ap.error("grades look like 5+, 6a, 6b+, 7c ...")
    for slug in args.areas:
        scrape_area(slug, gmin, gmax, args.refresh)
    if args.areas:
        update_manifest()
    if not args.areas and not args.list_areas:
        ap.print_help()


if __name__ == "__main__":
    main()
