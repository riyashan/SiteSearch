#!/usr/bin/env python3
"""
FaveKad search QA scraper  (https://favekad.com/gallery?search=<words>)

The site is an Inertia.js app: results are embedded as JSON in the
`data-page="..."` attribute of the root div. We fetch the HTML,
HTML-unescape that attribute, and parse it as JSON.

    props.cards.data   -> list of cards (24 per page): title, slug, category
    props.cards.total  -> total number of results
    card link          -> https://favekad.com/gallery/<category>/<slug>

Reads:   search-tests-template.csv   (your test cases; never modified)
Writes:  search-tests.csv            (template rows + results; rebuilt on every run)
    id,query,lang,what_the_person_wants,should_be_in_top5,today_total,today_top5,pass,note

  You edit (in the template): id, query, lang, what_the_person_wants,
                              should_be_in_top5, note
  Script fills (in the output): today_total, today_top5, pass

  should_be_in_top5: one or more expected results separated by "|" or ";"
                     (title, slug, or "category/slug").
  today_top5: the top 5 titles joined with " | ".
  pass: Y if at least one expected result is in the top 5, else N
        (blank if nothing expected, ERROR if the request failed).

Re-runnable: every run starts again from the template and overwrites
search-tests.csv, so results are never stale or duplicated. The output is
written atomically, and if a run is interrupted the rows already done are saved.
Script notes are tagged "[auto]" after your own note.

Politeness: sequential requests, at most 1 per second, custom User-Agent.
Only page 1 is fetched per query (the top 5 is on page 1).

Usage:
    python favekad_scraper.py                        # template -> search-tests.csv
    python favekad_scraper.py "cat" "dog"            # also test these extra queries
    python favekad_scraper.py --input a.csv --output b.csv

Install:
    pip install requests
"""

import argparse
import csv
import html
import json
import os
import re
import sys
import tempfile
import time
from urllib.parse import urlencode

import requests

BASE_URL = "https://favekad.com/gallery"
DEFAULT_INPUT = "search-tests-template.csv"
DEFAULT_OUTPUT = "search-tests.csv"
HEADERS = {
    "User-Agent": "FaveKad-QA/1.0 (Roshan, for Redz)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
COLUMNS = ["id", "query", "lang", "what_the_person_wants", "should_be_in_top5",
           "today_total", "today_top5", "pass", "note"]
AUTO_NOTE_RE = re.compile(r"\s*\|?\s*\[auto\].*$", re.DOTALL)

DATA_PAGE_RE = re.compile(r'data-page=(?:"([^"]*)"|\'([^\']*)\')', re.DOTALL)

MIN_INTERVAL = 1.0  # at most 1 request per second, one at a time
_last_request = 0.0


def polite_get(session, url):
    global _last_request
    wait = MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()
    resp = session.get(url, headers=HEADERS, timeout=30)
    _last_request = time.monotonic()
    resp.raise_for_status()
    return resp


def extract_page_data(page_html):
    m = DATA_PAGE_RE.search(page_html)
    if not m:
        raise ValueError("data-page attribute not found (layout changed or blocked?)")
    raw = m.group(1) if m.group(1) is not None else m.group(2)
    return json.loads(html.unescape(raw))


def as_text(value):
    if isinstance(value, dict):
        return str(value.get("slug") or value.get("name") or value.get("title") or "")
    return "" if value is None else str(value)


def card_to_row(card):
    category, slug = as_text(card.get("category")), as_text(card.get("slug"))
    return {"title": as_text(card.get("title")), "category": category, "slug": slug,
            "url": f"{BASE_URL}/{category}/{slug}"}


def search(session, query):
    """Return (total, first-page cards) for one query."""
    resp = polite_get(session, f"{BASE_URL}?{urlencode({'search': query})}")
    cards = extract_page_data(resp.text).get("props", {}).get("cards", {})
    data = cards.get("data") or []
    return int(cards.get("total", len(data)) or 0), [card_to_row(c) for c in data]


def matches(expected, card):
    e = expected.strip().lower()
    return e in (card["slug"].lower(), card["title"].lower(),
                 f'{card["category"]}/{card["slug"]}'.lower()) or e in card["url"].lower()


def run_row(session, row):
    """Re-test one row. Keeps every input column, overwrites the today_*/pass columns."""
    out = {k: (v or "").strip() if isinstance(v, str) or v is None else v for k, v in row.items()}
    user_note = AUTO_NOTE_RE.sub("", out.get("note", "")).strip()
    out["today_total"] = out["today_top5"] = out["pass"] = ""
    auto = ""

    query = out.get("query", "")
    if not query:
        out["pass"], auto = "ERROR", "empty query"
    else:
        try:
            total, cards = search(session, query)
        except (requests.RequestException, ValueError, json.JSONDecodeError) as e:
            out["pass"], auto = "ERROR", f"request failed: {e}"
        else:
            top5 = cards[:5]
            out["today_total"] = total
            out["today_top5"] = " | ".join(c["title"] for c in top5)
            expected = [x for x in re.split(r"[|;]", out.get("should_be_in_top5", "")) if x.strip()]
            if expected:
                hit = any(matches(x, c) for x in expected for c in top5)
                out["pass"] = "Y" if hit else "N"
                if not hit:
                    auto = "none of expected found in top5: " + ", ".join(x.strip() for x in expected)

    out["note"] = " | ".join(p for p in (user_note, f"[auto] {auto}" if auto else "") if p)
    return out


def load_rows(path):
    if not os.path.exists(path):
        return [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def save_rows(path, rows, fieldnames):
    """Atomic write: temp file in the same folder, then replace."""
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", restval="")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def main():
    global MIN_INTERVAL
    ap = argparse.ArgumentParser(description="FaveKad search QA scraper (re-runnable)")
    ap.add_argument("words", nargs="*", help="extra queries to test (not written to the template)")
    ap.add_argument("--input", default=DEFAULT_INPUT, help=f"template CSV to read (default {DEFAULT_INPUT})")
    ap.add_argument("--output", default=DEFAULT_OUTPUT, help=f"results CSV to write (default {DEFAULT_OUTPUT})")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="seconds between requests (minimum 1.0; faster is not allowed)")
    args = ap.parse_args()
    MIN_INTERVAL = max(1.0, args.delay)

    if os.path.abspath(args.input) == os.path.abspath(args.output):
        sys.exit("--input and --output must be different files (the template is never overwritten).")

    rows, fieldnames = load_rows(args.input)
    if not rows and not os.path.exists(args.input) and not args.words:
        sys.exit(f"{args.input} not found. Create it with the columns: {','.join(COLUMNS)}")
    fieldnames = fieldnames + [c for c in COLUMNS if c not in fieldnames] if fieldnames else list(COLUMNS)

    existing = {(r.get("query") or "").strip().lower() for r in rows}
    for w in args.words:
        if w.strip().lower() not in existing:
            rows.append({"query": w.strip()})
            existing.add(w.strip().lower())
    if not rows:
        sys.exit("Nothing to test.")

    for i, r in enumerate(rows, 1):
        if not (r.get("id") or "").strip():
            r["id"] = str(i)

    # untested rows keep blank result columns until their turn comes
    done = [{**r, "today_total": "", "today_top5": "", "pass": ""} for r in rows]
    try:
        with requests.Session() as s:
            for i, row in enumerate(rows):
                done[i] = run_row(s, row)
                d = done[i]
                print(f'[{i + 1}/{len(rows)}] {d.get("query", "")!r}: '
                      f'total={d["today_total"] if d["today_total"] != "" else "-"} pass={d["pass"] or "-"}')
    except KeyboardInterrupt:
        print("\nInterrupted: saving rows completed so far.", file=sys.stderr)
    finally:
        save_rows(args.output, done, fieldnames)
    print(f"Read {args.input}, wrote {args.output} ({len(done)} rows)")


if __name__ == "__main__":
    main()