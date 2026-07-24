#!/usr/bin/env python3
"""
WorldPop Population CLI — Search and download WorldPop population grid datasets.

Privacy Notice:
    This tool sends ONLY HTTP GET requests to www.worldpop.org.
    No personal data, cookies, or identifiers are transmitted.

Data Source:
    WorldPop REST API (https://www.worldpop.org/rest/data)
    CC BY 4.0 license for most datasets.

License: MIT-0
Author: ruiduobao
Version: 0.1.0
"""

import argparse
import json
import sys
import os
import re
from typing import List, Dict, Any, Optional

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is required. Install with: pip install requests>=2.28.0")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore

BASE_URL = "https://www.worldpop.org/rest/data"
TIMEOUT = 30
CHUNK_SIZE = 8192


def fetch_json(url: str, params: Optional[Dict] = None) -> Optional[Any]:
    """Fetch JSON from URL with error handling."""
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        print(f"ERROR: Request to {url} timed out.", file=sys.stderr)
        return None
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Could not connect to {url}. Check your network.", file=sys.stderr)
        return None
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: HTTP {e.response.status_code}: {e.response.text[:200]}", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        print("ERROR: Invalid JSON response.", file=sys.stderr)
        return None


def search_datasets(
    country: Optional[str] = None,
    code: Optional[str] = None,
    year: Optional[int] = None,
    dtype: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Search WorldPop datasets with optional filters."""
    data = fetch_json(BASE_URL)
    if data is None:
        return None

    results = []
    for item in data:
        # Filter by country
        if country:
            item_country = (item.get("country") or "").lower()
            if country.lower() not in item_country:
                continue
        if code:
            item_code = (item.get("iso3") or "").lower()
            if code.lower() != item_code:
                continue
        # Filter by year
        if year:
            item_year = item.get("year")
            if item_year and int(item_year) != year:
                continue
        # Filter by type
        if dtype:
            item_title = (item.get("title") or "").lower()
            if dtype.lower() not in item_title:
                continue
        results.append(item)

    return results


def download_file(url: str, output_path: str) -> bool:
    """Download a file with progress bar."""
    try:
        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))

        with open(output_path, "wb") as f:
            if tqdm and total > 0:
                with tqdm(total=total, unit="B", unit_scale=True, desc="Downloading") as pbar:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        f.write(chunk)
                        pbar.update(len(chunk))
            else:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    f.write(chunk)
        return True
    except requests.exceptions.Timeout:
        print("ERROR: Download timed out.", file=sys.stderr)
        return False
    except requests.exceptions.ConnectionError:
        print("ERROR: Connection lost during download.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"ERROR: Download failed: {e}", file=sys.stderr)
        return False


def cmd_search(args: argparse.Namespace) -> int:
    """Handle the 'search' subcommand."""
    if not args.country and not args.code:
        print("WARNING: No country or code filter. This may return many results.", file=sys.stderr)

    results = search_datasets(
        country=args.country,
        code=args.code,
        year=args.year,
        dtype=args.type,
    )
    if results is None:
        return 1

    if not results:
        print("No datasets found matching your criteria.")
        return 0

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(f"Found {len(results)} dataset(s):\n")
        for r in results:
            print(f"  ID:      {r.get('id', 'N/A')}")
            print(f"  Title:   {r.get('title', 'N/A')}")
            print(f"  Country: {r.get('country', 'N/A')}")
            print(f"  ISO3:    {r.get('iso3', 'N/A')}")
            print(f"  Year:    {r.get('year', 'N/A')}")
            files = r.get("files", [])
            if files:
                print(f"  Files:   {len(files)} file(s)")
            print()
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    """Handle the 'download' subcommand."""
    ds_id = args.id
    output_path = args.output

    # Fetch dataset detail
    data = fetch_json(f"{BASE_URL}/{ds_id}")
    if data is None:
        print(f"ERROR: Could not fetch dataset {ds_id}.", file=sys.stderr)
        return 1

    files = data.get("files", [])
    if not files:
        print(f"ERROR: Dataset {ds_id} has no downloadable files.", file=sys.stderr)
        return 1

    # Pick the first GeoTIFF or the first file
    download_url = None
    for f in files:
        fname = f.get("filename", "") if isinstance(f, dict) else str(f)
        if fname.endswith(".tif") or fname.endswith(".tiff"):
            download_url = f.get("url") if isinstance(f, dict) else f
            break
    if not download_url:
        # Use first file
        f = files[0]
        download_url = f.get("url") if isinstance(f, dict) else f

    if not download_url:
        print("ERROR: No download URL found.", file=sys.stderr)
        return 1

    # Ensure output directory exists
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    print(f"Downloading dataset {ds_id}...")
    print(f"  Title: {data.get('title', 'N/A')}")
    print(f"  URL:   {download_url}")
    print(f"  To:    {output_path}")

    if download_file(download_url, output_path):
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"Done. File size: {size_mb:.1f} MB")
        return 0
    else:
        return 1


def cmd_list_countries(args: argparse.Namespace) -> int:
    """Handle the 'list-countries' subcommand."""
    data = fetch_json(BASE_URL)
    if data is None:
        return 1

    countries: Dict[str, str] = {}
    for item in data:
        name = item.get("country", "")
        iso3 = item.get("iso3", "")
        if name and iso3:
            countries[iso3] = name

    sorted_countries = sorted(countries.items(), key=lambda x: x[1])

    if args.json:
        print(json.dumps(dict(sorted_countries), indent=2, ensure_ascii=False))
    else:
        print(f"Available countries ({len(sorted_countries)}):\n")
        for iso3, name in sorted_countries:
            print(f"  {iso3}  {name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="worldpop-population",
        description="Search and download WorldPop population grid datasets.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    # search
    p_search = subparsers.add_parser("search", help="Search available datasets")
    p_search.add_argument("--country", help="Country name (e.g., 'China')")
    p_search.add_argument("--code", help="ISO 3166-1 alpha-3 code (e.g., 'CHN')")
    p_search.add_argument("--year", type=int, help="Filter by year (2000-2020)")
    p_search.add_argument("--type", help="Dataset type filter (e.g., 'population', 'births')")
    p_search.add_argument("--json", action="store_true", help="Output as JSON")

    # download
    p_download = subparsers.add_parser("download", help="Download a dataset by ID")
    p_download.add_argument("--id", type=int, required=True, help="Dataset ID")
    p_download.add_argument("--output", required=True, help="Output file path")

    # list-countries
    p_list = subparsers.add_parser("list-countries", help="List available countries")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "search":
        return cmd_search(args)
    elif args.command == "download":
        return cmd_download(args)
    elif args.command == "list-countries":
        return cmd_list_countries(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
