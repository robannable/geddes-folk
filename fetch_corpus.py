"""Download corpus texts listed in corpus/manifest.json into corpus/raw/.

Two fetch modes per entry:
  - `download_url`     : direct GET, saved as-is. An entry may add
                         `download_url_part2`, `_part3`... for a work
                         split across several archive.org items (the
                         Indore report is two volumes); the parts are
                         fetched in order and concatenated into one file.
  - `wikipedia_title`  : Wikipedia REST API, plain-text extract saved.

Entries already present locally are skipped, so this is safe to re-run.
corpus/raw/ is gitignored and rebuilt per install; entries that ship with
the repo live in corpus/studio/ and are skipped here.

Usage:
    python fetch_corpus.py                                        # everything missing
    python fetch_corpus.py cities_in_evolution wiki_geddes        # selected ids

Run locally on a machine with outbound access — Claude Code on the web
sessions typically block archive.org, gutenberg.org, and en.wikipedia.org.
After fetching, commit the new files (or leave them local) and run
`python ingest.py` to rebuild the index.

If a download_url 404s, click through the entry's source_url on
archive.org and check whether the item's filename differs from the
standard `<identifier>_djvu.txt` pattern; some IMSLP-uploaded items use
longer filenames that need to be looked up by hand.
"""

import json
import re
import sys
import urllib.parse
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
RAW = ROOT / "corpus" / "raw"
STUDIO = ROOT / "corpus" / "studio"
MANIFEST = ROOT / "corpus" / "manifest.json"

USER_AGENT = "geddes-folk corpus fetcher (https://github.com/robannable/geddes-folk)"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"


def fetch_url(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_wikipedia(title: str) -> str:
    params = {
        "format": "json",
        "action": "query",
        "prop": "extracts",
        "explaintext": "1",
        "exsectionformat": "plain",
        "redirects": "1",
        "titles": title,
    }
    url = f"{WIKIPEDIA_API}?{urllib.parse.urlencode(params)}"
    raw = fetch_url(url)
    pages = json.loads(raw).get("query", {}).get("pages") or {}
    if not pages:
        raise RuntimeError("Wikipedia API returned no pages")
    page = next(iter(pages.values()))
    if "missing" in page:
        raise RuntimeError(f"Wikipedia article not found: {title!r}")
    extract = (page.get("extract") or "").strip()
    if not extract:
        raise RuntimeError(f"Wikipedia article empty: {title!r}")
    return extract


def download_urls(entry: dict) -> list[str]:
    """Every URL for an entry, in order: download_url then _partN.

    A work split across archive.org items — the Indore report is two
    volumes — lists the rest as `download_url_part2`, `_part3` and so on.
    Sorted numerically, so _part10 follows _part9 rather than _part1.
    """
    urls = []
    if "download_url" in entry:
        urls.append(entry["download_url"])
    parts = []
    for key, value in entry.items():
        m = re.fullmatch(r"download_url_part(\d+)", key)
        if m:
            parts.append((int(m.group(1)), value))
    urls.extend(v for _, v in sorted(parts))
    return urls


def fetch_one(entry: dict) -> str:
    # Studio material is placed by hand and is not fetchable; never
    # report it as a failure or try to overwrite it.
    if (STUDIO / entry["file"]).exists():
        return f"skip {entry['id']}: present in corpus/studio/"

    file_path = RAW / entry["file"]
    if file_path.exists():
        return f"skip {entry['id']}: {entry['file']} already present"

    if "wikipedia_title" in entry:
        title = entry["wikipedia_title"]
        print(f"  fetching {entry['id']}")
        print(f"    Wikipedia: {title}")
        text = fetch_wikipedia(title)
    elif download_urls(entry):
        urls = download_urls(entry)
        print(f"  fetching {entry['id']}"
              + (f" ({len(urls)} parts)" if len(urls) > 1 else ""))
        segments = []
        for i, url in enumerate(urls, 1):
            print(f"    {url}")
            segment = fetch_url(url)
            # A blank line between parts so the paragraph chunker does
            # not run the end of one volume into the start of the next.
            segments.append(segment)
            if len(urls) > 1:
                print(f"      part {i}: {len(segment):,} chars")
        text = "\n\n".join(segments)
    else:
        return (f"skip {entry['id']}: no download_url or wikipedia_title "
                f"— place {entry['file']} in corpus/studio/ by hand")

    RAW.mkdir(parents=True, exist_ok=True)
    file_path.write_text(text, encoding="utf-8")
    return f"    wrote {file_path.relative_to(ROOT)} ({len(text):,} chars)"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ids = sys.argv[1:]
    if ids:
        unknown = [i for i in ids if i not in {e["id"] for e in manifest}]
        if unknown:
            sys.exit(f"unknown manifest id(s): {', '.join(unknown)}")
        manifest = [e for e in manifest if e["id"] in ids]

    failures: list[tuple[str, str]] = []
    for entry in manifest:
        try:
            print(fetch_one(entry))
        except Exception as exc:
            print(f"  FAILED {entry['id']}: {exc}")
            failures.append((entry["id"], str(exc)))

    if failures:
        print(f"\n{len(failures)} failure(s):")
        for fid, err in failures:
            print(f"  - {fid}: {err}")
        return 1
    print("\ndone. Now run: python ingest.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
