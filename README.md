# FaveKad Search QA Scraper

A small Python script that runs a list of search queries against
`https://favekad.com/gallery?search=<words>`, records how many results each
query returns and what the top 5 are, and marks whether the expected results
showed up.

## How it works

The gallery is an [Inertia.js](https://inertiajs.com/) app, so the results are
not in the visible HTML. They are embedded as JSON in the `data-page="..."`
attribute of the root `<div>`. For each query the script:

1. Requests `https://favekad.com/gallery?search=<query>`
2. Finds the `data-page` attribute and HTML-unescapes it
3. Parses it as JSON and reads:
   - `props.cards.data`: the cards on the page (24 per page), each with `title`, `slug` and `category`
   - `props.cards.total`: the total number of results
4. Builds each card link as `https://favekad.com/gallery/<category>/<slug>`

Only the first page is fetched per query, because the top 5 results are on page 1.

## Requirements

- Python 3.8+
- `requests`

```bash
pip install requests
```

## Files

| File | Purpose |
|------|---------|
| `favekad_scraper.py` | The script |
| `search-tests-template.csv` | Your test cases (input). The script never modifies it. |
| `search-tests.csv` | The results (output). Rebuilt from the template on every run. |

## Usage

```bash
# Default: read search-tests-template.csv, write search-tests.csv
python favekad_scraper.py

# Also test extra queries (these are not saved back to the template)
python favekad_scraper.py "cat" "dog"

# Use different files
python favekad_scraper.py --input my-template.csv --output my-results.csv
```

| Option | Default | Description |
|--------|---------|-------------|
| `words` | none | Extra queries to test. Each argument is one search. |
| `--input` | `search-tests-template.csv` | Template CSV to read |
| `--output` | `search-tests.csv` | Results CSV to write |
| `--delay` | `1.0` | Seconds between requests. Minimum 1.0; lower values are raised to 1.0. |

The script refuses to run if `--input` and `--output` are the same file.

## CSV columns

```
id,query,lang,what_the_person_wants,should_be_in_top5,today_total,today_top5,pass,note
```

You fill in these columns in the template:

| Column | Meaning |
|--------|---------|
| `id` | Test id. If left blank, the row number is used. |
| `query` | The search words that are sent to the site |
| `lang` | Language of the query. Carried through to the output; it is not sent to the site. |
| `what_the_person_wants` | A plain-language description of the intent, for your own reference |
| `should_be_in_top5` | One or more expected results (see below) |
| `note` | Your own notes |

The script fills in these columns in the output:

| Column | Meaning |
|--------|---------|
| `today_total` | Total number of results the site reports for the query |
| `today_top5` | The titles of the top 5 results, joined with ` \| ` |
| `pass` | `Y`, `N`, blank or `ERROR` (see below) |

### Expected results (`should_be_in_top5`)

Put one or more expected results in the cell, separated by `|` or `;`.
Each one can be:

- a title, for example `Selamat Pagi`
- a slug, for example `selamat-pagi`
- `category/slug`, for example `greetings/selamat-pagi`

Matching is case-insensitive.

### Pass rule

| `pass` | When |
|--------|------|
| `Y` | At least one expected result is in the top 5 |
| `N` | None of the expected results are in the top 5 |
| blank | `should_be_in_top5` is empty, so there is nothing to check |
| `ERROR` | The request failed, the page could not be parsed, or the query was empty |

When a row is `N` or `ERROR`, the script adds an explanation to `note`,
after your own note and tagged `[auto]`:

```
my note | [auto] none of expected found in top5: nope
```

## Example

`search-tests-template.csv`:

```csv
id,query,lang,what_the_person_wants,should_be_in_top5,today_total,today_top5,pass,note
1,cat,en,cute cat pictures,,,,,
2,selamat pagi,ms,good morning greeting card,selamat-pagi,,,,
```

After a run, `search-tests.csv` has the `today_total`, `today_top5` and `pass`
columns filled in.

## Re-running

Every run starts again from the template and overwrites `search-tests.csv`, so
results are never stale or duplicated. To retest, run the script again. To add
or change test cases, edit the template.

The output is written to a temporary file and then swapped in, so a crash
cannot leave a half-written CSV. If you press Ctrl+C during a run, the rows
already tested are saved and the remaining rows are written with blank results.

## Being polite to the site

- Requests are sent one at a time, never in parallel
- At most 1 request per second, enforced inside the script (`--delay` can only slow it down)
- Every request sends the User-Agent `FaveKad-QA/1.0 (Roshan, for Redz)`

One request is made per query, so a 100-row template takes a little under two
minutes.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `data-page attribute not found` in `note` | The site layout changed, or the request was blocked or redirected. Open the URL in a browser and check the page source. |
| `request failed: ...` in `note` | Network error, timeout or an HTTP error status |
| Every row has `today_total` of 0 | The search URL or `props.cards` structure may have changed. Check the `data-page` JSON in the browser. |
| Titles or links look wrong | `category` or `slug` may have a different shape. The script accepts plain strings or objects with a `slug`, `name` or `title`. |
| Accented characters look garbled in Excel | The output is written as UTF-8 with a byte order mark, which Excel normally reads correctly. If it still looks wrong, use Data > From Text/CSV and choose UTF-8. |

## Limitations

- Only page 1 of the results is read (24 cards); the top 5 is all that is checked
- `lang` is informational only and is not used in the search
- The script depends on the site's current Inertia page structure (`props.cards.data` and `props.cards.total`)
