#!/usr/bin/env python3
"""
WorldPop Population CLI v2 — Search, download, and subset WorldPop population grids.

What's new vs v1:
  * Adapts to the current WorldPop REST API which returns
    ``{"data": [{"alias": "pop", "name": "...", ...}, ...]}`` (category list)
    at the top level, not a flat dataset list. v1 crashed with
    ``AttributeError: 'str' object has no attribute 'get'`` because of this.
  * Adds a ``search`` sub-mode that knows the two-level structure
    (category → datasets) and supports ``--category``, ``--country``,
    ``--code``, ``--year``, ``--type``, ``--limit``, ``--json``.
  * Adds a ``download`` sub-mode that auto-resolves a dataset by
    ISO+year+category (no more manual ``--id`` lookup), downloads the
    GeoTIFF, then optionally clips to a ``--bbox`` (WGS84) or
    ``--place`` resolved via Open-Meteo Geocoding (Nominatim is
    rate-limited in many networks).
  * Adds ``--qa`` to write a sidecar JSON with the resolved dataset id,
    source URL, bbox, CRS, file size, and provenance.
  * Adds ``bbox-clip`` subcommand for subsetting a previously downloaded
    country GeoTIFF to a bbox or place.

Privacy Notice:
    This tool sends ONLY HTTP GET requests to www.worldpop.org (datasets)
    and geocoding-api.open-meteo.com (place resolution fallback).
    No personal data, cookies, or identifiers are transmitted.

Data Source:
    WorldPop REST API (https://www.worldpop.org/rest/data)
    CC BY 4.0 license for most datasets.

License: MIT-0
Author: ruiduobao
Version: 0.2.0
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Dict, Any, Optional, Tuple

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
OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT = 30
CHUNK_SIZE = 8192
USER_AGENT = "worldpop-population/0.2.0 (OpenClaw GIS tool)"

# Curated set of common WorldPop categories the new API exposes under /rest/data.
# `alias` is the second-level path; `description` is shown to the user.
WP_CATEGORIES = {
    # alias              : (label,                                       family, parent)
    "pop":                ("Population Counts",                            "population",     None),
    "pop/pic":            ("Population Counts / Individual countries",     "population",     "pop"),
    "pop/pop_continent":  ("Population Counts / Whole Continent",          "population",     "pop"),
    "pop/wpgp":           ("Unconstrained individual countries 2000-2020 (100m)",  "population", "pop"),
    "pop/wpgp1km":        ("Unconstrained global mosaics 2000-2020 (1km)",         "population", "pop"),
    "pop/wpgpunadj":      ("Unconstrained individual countries 2000-2020 UN adjusted (100m)", "population", "pop"),
    "pop/wpic1km":        ("Unconstrained individual countries 2000-2020 (1km)",   "population", "pop"),
    "pop/cic2020_100m":   ("Constrained Individual countries 2020 (100m)",          "population", "pop"),
    "pop/G2_UC_POP_R24B_100m": ("Unconstrained individual countries 2015-2030 R2024B (100m)", "population", "pop"),
    "pop/G2_CN_POP_R24B_100m": ("Constrained individual countries 2015-2030 R2024B (100m)",   "population", "pop"),
    "pop/G2_CN_POP_R25A_100m": ("Individual countries 2015-2030 R2025A (100m)",   "population", "pop"),
    "pop/G2_CN_POP_R25A_1km":  ("Individual countries 2015-2030 R2025A (1km)",    "population", "pop"),
    "pop/G2_MOS_POP_R25A_1km": ("Global mosaics 2015-2030 R2025A (1km)",          "population", "pop"),
    "births":             ("Births",                                       "births",         None),
    "pregnancies":        ("Pregnancies",                                  "pregnancies",    None),
    "urban_change":       ("Urban change",                                 "urban",          None),
    "age_structures":     ("Age and sex structures",                       "age",            None),
}

# Friendly alias mapping (used by `search --type`)
TYPE_TO_FAMILY = {
    "population": ["pop", "pop/wpgp", "pop/wpgp1km", "pop/cic2020_100m",
                   "pop/G2_UC_POP_R24B_100m", "pop/G2_CN_POP_R25A_100m"],
    "births":     ["births"],
    "pregnancies": ["pregnancies"],
    "urban":      ["urban_change"],
    "age":        ["age_structures"],
}

DEFAULT_POP_CATEGORY = "pop/wpgp"  # 2000-2020 unconstrained 100m per country (most common)

# Semantic presets for common WorldPop tasks.
# Each preset fills in `--type` and (optionally) `--category` so users don't
# have to memorise the category taxonomy.
PRESETS = {
    "population-1km": {
        "description": "1km resolution global population mosaic (2000-2020)",
        "type": "population",
        "category": "pop/wpgp1km",
    },
    "population-100m": {
        "description": "100m resolution per-country population (2000-2020 unconstrained)",
        "type": "population",
        "category": "pop/wpgp",
    },
    "population-constrained": {
        "description": "100m constrained individual countries 2020",
        "type": "population",
        "category": "pop/cic2020_100m",
    },
    "births": {
        "description": "Annual births per pixel",
        "type": "births",
        "category": None,
    },
    "age-structures": {
        "description": "Age and sex structures",
        "type": "age",
        "category": None,
    },
    "urban-change": {
        "description": "Urban change classification",
        "type": "urban",
        "category": None,
    },
}


# ── Low-level HTTP helpers ────────────────────────────────────────────────────

def _http_get_json(url: str, params: Optional[Dict] = None,
                   timeout: int = TIMEOUT) -> Optional[Any]:
    """GET a URL and return the parsed JSON body, or None on failure."""
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, params=params, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        print(f"ERROR: Request to {url} timed out.", file=sys.stderr)
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Could not connect to {url}. Check your network.", file=sys.stderr)
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: HTTP {e.response.status_code}: {e.response.text[:200]}",
              file=sys.stderr)
    except json.JSONDecodeError:
        print("ERROR: Invalid JSON response.", file=sys.stderr)
    return None


# ── WorldPop API: 2-level navigation ──────────────────────────────────────────

def list_categories() -> List[Dict[str, str]]:
    """Return top-level WorldPop categories (e.g. pop, births, age_structures)."""
    data = _http_get_json(BASE_URL)
    if not data:
        return []
    return data.get("data", data) if isinstance(data, dict) else data


def list_datasets_in_category(category_alias: str,
                             iso3: Optional[str] = None) -> List[Dict[str, Any]]:
    """List concrete datasets under a category (e.g. 'pop/wpgp' → list of countries/years).

    The current WorldPop API returns the *full* record (with ``data_file`` /
    ``files``) only when the request is narrowed by ``?iso3=…``. The
    country-less call returns a sparse record with only ``id`` / ``iso3`` /
    ``popyear`` / ``title``, which is enough to drive ``search`` and let the
    user pick a dataset, but not enough to download directly.
    """
    if not category_alias:
        category_alias = "pop"
    url = f"{BASE_URL}/{category_alias}"
    params = {"iso3": iso3} if iso3 else None
    data = _http_get_json(url, params=params)
    if not data:
        return []
    return data.get("data", data) if isinstance(data, dict) else data


def get_dataset(dataset_id: str) -> Optional[Dict[str, Any]]:
    """Fetch one dataset detail by id."""
    return _http_get_json(f"{BASE_URL}/{dataset_id}")


# ── Geocoding fallback (Nominatim is rate-limited, use Open-Meteo first) ──────

def geocode_place(place: str) -> Optional[Dict[str, float]]:
    """Resolve a place name to a WGS84 point via Open-Meteo Geocoding API.

    Returns a dict with lat/lon, the matched name, the Open-Meteo country
    code, and (when pycountry is installed) the ISO3 code. The user can
    still pass ``--bbox`` for an explicit area.
    """
    data = _http_get_json(OPEN_METEO_GEOCODE_URL, params={"name": place, "count": 1})
    if not data or "results" not in data or not data["results"]:
        return None
    r = data["results"][0]
    iso3 = (r.get("iso3") or "").upper()
    if not iso3:
        # Open-Meteo often returns ``country_code`` (ISO2) but not ISO3.
        # pycountry can map alpha_2 -> alpha_3 robustly.
        ccode = (r.get("country_code") or "").upper()
        if ccode:
            try:
                import pycountry
                rec = pycountry.countries.get(alpha_2=ccode)
                if rec:
                    iso3 = rec.alpha_3
            except Exception:
                pass
    return {
        "lat": float(r["latitude"]),
        "lon": float(r["longitude"]),
        "country_code": (r.get("country_code") or "").upper(),
        "iso3": iso3,
        "name": r.get("name", ""),
        "admin1": r.get("admin1", ""),
    }


def country_to_iso3(country_name: str) -> Optional[str]:
    """Best-effort: take a country name and return its ISO3 via Open-Meteo Geocoding.

    Open-Meteo's geocoding responses include ``iso3`` for the matched city;
    for pure country names it returns the capital city. Used as a fallback
    only when the user did not provide --code.
    """
    geo = geocode_place(country_name)
    if not geo:
        return None
    return geo.get("iso3") or None


# ── Search with the new schema ───────────────────────────────────────────────

def search_datasets(
    country: Optional[str] = None,
    code: Optional[str] = None,
    year: Optional[int] = None,
    dtype: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Search datasets across one or more categories, applying filters.

    Returns a list of dataset dicts (already filtered). Each item is the
    concrete dataset object (id, title, popyear, iso3, files, ...).
    """
    if category:
        cats = [category]
    elif dtype and dtype in TYPE_TO_FAMILY:
        cats = TYPE_TO_FAMILY[dtype]
    else:
        # Default: only the most-commonly-used population category
        cats = [DEFAULT_POP_CATEGORY]

    all_hits: List[Dict[str, Any]] = []
    # When the user narrows by country / code, pass it to the API so the
    # response contains the download URL; otherwise the API returns only
    # id/iso3/popyear/title.
    api_filter = code if code else None
    for cat in cats:
        for ds in list_datasets_in_category(cat, iso3=api_filter):
            # Apply filters (case-insensitive substring on country name,
            # exact match on iso3, exact match on year)
            if code:
                if (ds.get("iso3") or "").upper() != code.upper():
                    continue
            if country:
                # The sparse list response does not include ``country``; fall
                # back to title substring.
                name = ds.get("country") or ds.get("title") or ""
                if country.lower() not in name.lower():
                    continue
            if year is not None:
                py = ds.get("popyear") or ds.get("year")
                if py is None or str(py) != str(year):
                    continue
            ds2 = dict(ds)
            ds2["_category"] = cat
            all_hits.append(ds2)
        if len(all_hits) >= limit:
            break

    return all_hits[:limit]


def pick_dataset(hits: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """When the user did not specify --id, pick the single best dataset
    from a non-empty hit list. Raises an informative error otherwise.
    """
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    # Prefer highest popyear (most recent)
    hits_sorted = sorted(hits, key=lambda d: d.get("popyear") or d.get("year") or 0,
                         reverse=True)
    return hits_sorted[0]


# ── File download + bbox clip ─────────────────────────────────────────────────

def _pick_geo_url(ds: Dict[str, Any]) -> Optional[str]:
    """Pick a downloadable GeoTIFF URL from a dataset detail."""
    files = ds.get("files") or []
    if isinstance(files, list) and files:
        for f in files:
            url = f.get("url") if isinstance(f, dict) else f
            if isinstance(url, str) and (url.endswith(".tif") or url.endswith(".tiff")):
                return url
        # No tif in the list? return first URL we can find
        for f in files:
            url = f.get("url") if isinstance(f, dict) else f
            if isinstance(url, str):
                return url
    # Fallback: data_file
    df = ds.get("data_file")
    if isinstance(df, str):
        if df.startswith("http"):
            return df
        return f"https://data.worldpop.org/{df.lstrip('/')}"
    return None


def download_file(url: str, output_path: str) -> bool:
    """Stream a URL to disk with a tqdm progress bar if available."""
    try:
        with requests.get(url, stream=True, timeout=300,
                          headers={"User-Agent": USER_AGENT}) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            with open(output_path, "wb") as f:
                if tqdm and total > 0:
                    with tqdm(total=total, unit="B", unit_scale=True,
                              desc=os.path.basename(output_path)) as pbar:
                        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                            f.write(chunk)
                            pbar.update(len(chunk))
                else:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        f.write(chunk)
        return True
    except requests.exceptions.Timeout:
        print("ERROR: Download timed out.", file=sys.stderr)
    except requests.exceptions.ConnectionError:
        print("ERROR: Connection lost during download.", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: Download failed: {e}", file=sys.stderr)
    return False


def _safe_unlink(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def clip_geotiff_to_bbox(input_tif: str, output_tif: str, bbox: Tuple[float, float, float, float]) -> bool:
    """Clip a WGS84 GeoTIFF to (west, south, east, north) using rasterio.

    Returns True on success. The input is read with a WGS84 reproject-on-the-fly
    if its native CRS is not EPSG:4326, then a window + warp is written.
    """
    try:
        import rasterio
        from rasterio.windows import from_bounds
    except ImportError:
        print("ERROR: rasterio is required for --bbox. Install with: pip install rasterio",
              file=sys.stderr)
        return False

    west, south, east, north = bbox
    tmp_out = output_tif + ".part"
    try:
        with rasterio.open(input_tif) as src:
            if src.crs and src.crs.to_epsg() != 4326:
                # Reproject bounds into the source CRS
                from rasterio.warp import transform_bounds
                west_s, south_s, east_s, north_s = transform_bounds(
                    "EPSG:4326", src.crs, west, south, east, north)
            else:
                west_s, south_s, east_s, north_s = west, south, east, north
            window = from_bounds(west_s, south_s, east_s, north_s, src.transform)
            window = window.intersection(
                rasterio.windows.Window(0, 0, src.width, src.height))
            if window.width <= 0 or window.height <= 0:
                print(f"ERROR: bbox does not overlap raster.", file=sys.stderr)
                return False
            transform = src.window_transform(window)
            meta = src.meta.copy()
            meta.update({
                "height": int(window.height),
                "width": int(window.width),
                "transform": transform,
            })
            with rasterio.open(tmp_out, "w", **meta) as dst:
                for i in range(1, src.count + 1):
                    dst.write(src.read(i, window=window), i)
                # Preserve nodata
                if src.nodata is not None:
                    dst.nodata = src.nodata
        os.replace(tmp_out, output_tif)
        return True
    except Exception as e:
        print(f"ERROR: clip failed: {e}", file=sys.stderr)
        _safe_unlink(tmp_out)
        return False


def write_qa(qa_path: str, payload: Dict[str, Any]) -> None:
    try:
        with open(qa_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"QA summary: {qa_path}")
    except Exception as e:
        print(f"WARNING: failed to write QA sidecar: {e}", file=sys.stderr)


def inspect_geotiff(path: str) -> Dict[str, Any]:
    """Best-effort rasterio inspection for the QA sidecar."""
    info: Dict[str, Any] = {"path": path, "size_bytes": os.path.getsize(path)}
    try:
        import rasterio
        with rasterio.open(path) as src:
            info.update({
                "crs": str(src.crs) if src.crs else None,
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "dtype": str(src.dtypes[0]) if src.dtypes else None,
                "bounds": [src.bounds.left, src.bounds.bottom,
                           src.bounds.right, src.bounds.top],
                "res": [src.res[0], src.res[1]],
                "nodata": src.nodata,
            })
    except ImportError:
        info["rasterio"] = "not installed (skipping raster QA)"
    except Exception as e:
        info["rasterio_error"] = str(e)
    return info


# ── CLI subcommands ──────────────────────────────────────────────────────────

def cmd_search(args: argparse.Namespace) -> int:
    """List matching datasets with the new schema."""
    if not (args.country or args.code or args.year or args.type or args.category):
        print("NOTE: No filter supplied; returning a small sample of recent "
              "population datasets.", file=sys.stderr)
    hits = search_datasets(
        country=args.country,
        code=args.code,
        year=args.year,
        dtype=args.type,
        category=args.category,
        limit=args.limit,
    )
    if not hits:
        print("No datasets found matching your criteria.")
        print("Hint: try --code CHN --year 2020, or --type population, "
              "or list --categories.", file=sys.stderr)
        return 0

    if args.json:
        print(json.dumps(hits, indent=2, ensure_ascii=False))
    else:
        print(f"Found {len(hits)} dataset(s):\n")
        for r in hits:
            ds_id = r.get("id", "N/A")
            print(f"  ID:       {ds_id}")
            print(f"  Title:    {r.get('title', 'N/A')}")
            print(f"  Country:  {r.get('country', 'N/A')} ({r.get('iso3', 'N/A')})")
            print(f"  Year:     {r.get('popyear') or r.get('year', 'N/A')}")
            print(f"  Category: {r.get('_category', 'N/A')}")
            url = _pick_geo_url(r)
            if url:
                print(f"  URL:      {url}")
            print()
    return 0


def cmd_list_categories(args: argparse.Namespace) -> int:
    """List available top-level WorldPop categories."""
    cats = list_categories()
    if not cats:
        print("ERROR: could not fetch WorldPop category list.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(cats, indent=2, ensure_ascii=False))
    else:
        print(f"Available WorldPop categories ({len(cats)}):\n")
        for c in cats:
            print(f"  {c.get('alias', '?'):<22}  {c.get('name', '?')}")
        print("\nUse --category <alias> with search/download to drill in,")
        print("or pass one of the curated --category values:")
        for a, (lbl, _fam, _par) in WP_CATEGORIES.items():
            print(f"  {a:<35}  {lbl}")
    return 0


def cmd_list_countries(args: argparse.Namespace) -> int:
    """List ISO3 codes that have at least one population dataset.

    Uses the sparse list response (id/iso3/popyear/title only) to avoid
    5000+ requests.
    """
    datasets = list_datasets_in_category(DEFAULT_POP_CATEGORY)
    isos: Dict[str, str] = {}
    for d in datasets:
        iso3 = (d.get("iso3") or "").upper()
        title = d.get("title") or ""
        # Title looks like "The spatial distribution of population in 2000, China"
        country = ""
        if "," in title:
            country = title.rsplit(",", 1)[-1].strip()
        if iso3 and iso3 not in isos:
            isos[iso3] = country or iso3
    sorted_isos = sorted(isos.items(), key=lambda x: x[1])
    if args.json:
        print(json.dumps(dict(sorted_isos), indent=2, ensure_ascii=False))
    else:
        print(f"Available countries ({len(sorted_isos)}):\n")
        for iso3, name in sorted_isos:
            print(f"  {iso3}  {name}")
    return 0


def _resolve_search(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    """Resolve the dataset to download based on --id, --code/--year/--category, or --place+--year."""
    # Apply preset (only when user did not explicitly pass --type / --category)
    if getattr(args, "preset", None):
        if args.preset not in PRESETS:
            print(f"ERROR: unknown preset {args.preset!r}; "
                  f"available: {', '.join(sorted(PRESETS))}", file=sys.stderr)
            return None
        info = PRESETS[args.preset]
        if not args.type:
            args.type = info["type"]
        if not args.category and info.get("category"):
            args.category = info["category"]
        print(f"Using preset {args.preset!r}: {info['description']}")

    if args.id:
        ds = get_dataset(str(args.id))
        return ds

    code = args.code
    country = args.country

    if args.place and not (code or country):
        # Resolve place -> ISO3
        geo = geocode_place(args.place)
        if not geo:
            print(f"ERROR: could not resolve place '{args.place}' via Open-Meteo.",
                  file=sys.stderr)
            return None
        code = geo.get("iso3")
        country = geo.get("name")
        if not code:
            print(f"ERROR: place '{args.place}' resolved but no ISO3 code returned.",
                  file=sys.stderr)
            return None
        print(f"Resolved '{args.place}' -> {country} ({code}) "
              f"lat={geo['lat']:.4f}, lon={geo['lon']:.4f}")

    if not (code or country):
        print("ERROR: provide --id, or (--code/--country/--place) + --year, "
              "or use the new 'search' subcommand first.", file=sys.stderr)
        return None

    hits = search_datasets(
        country=country, code=code,
        year=args.year, dtype=args.type,
        category=args.category, limit=args.limit,
    )
    chosen = pick_dataset(hits)
    if not chosen:
        print(f"ERROR: no matching dataset for "
              f"country={country!r} code={code!r} year={args.year!r} "
              f"category={args.category!r}. Try 'search --json' to inspect.",
              file=sys.stderr)
        return None
    # If user only passed --id we already have detail; otherwise fetch detail
    if not args.id and "files" not in chosen:
        detail = get_dataset(str(chosen["id"]))
        if detail:
            return detail
    return chosen


def cmd_download(args: argparse.Namespace) -> int:
    """Resolve → download → optional bbox clip → optional QA sidecar."""
    chosen = _resolve_search(args)
    if not chosen:
        return 1

    # The current WorldPop REST API returns the download URL inside the list
    # response. The detail endpoint /rest/data/{id} returns HTTP 500, so we
    # accept whichever the list response gave us and only try the detail
    # endpoint as a last resort.
    url = _pick_geo_url(chosen)
    if not url and chosen.get("id"):
        detail = get_dataset(str(chosen["id"]))
        if detail:
            chosen = detail
            url = _pick_geo_url(detail)
    if not url:
        print(f"ERROR: dataset {chosen.get('id')} has no downloadable GeoTIFF.",
              file=sys.stderr)
        return 1

    output_path = args.output
    if not output_path:
        slug = (chosen.get("iso3") or "x").lower()
        year = chosen.get("popyear") or chosen.get("year") or "yyyy"
        output_path = f"worldpop_{slug}_{year}.tif"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".",
                exist_ok=True)

    print(f"Downloading dataset {chosen.get('id')} ({chosen.get('title','?')})")
    print(f"  URL:   {url}")
    print(f"  To:    {output_path}")

    if not download_file(url, output_path):
        return 1

    final_path = output_path
    if args.bbox:
        try:
            w, s, e, n = (float(x) for x in args.bbox)
        except (TypeError, ValueError):
            print("ERROR: --bbox must be 'west south east north' (4 floats).",
                  file=sys.stderr)
            return 1
        clipped = output_path.replace(".tif", "_clipped.tif")
        if clip_geotiff_to_bbox(output_path, clipped, (w, s, e, n)):
            final_path = clipped
        else:
            print("WARN: clipping failed; keeping the un-clipped download.",
                  file=sys.stderr)

    print(f"Done. File: {final_path} ({os.path.getsize(final_path) / (1024*1024):.1f} MB)")

    if args.qa:
        qa = {
            "skill": "worldpop-population",
            "version": "0.2.0",
            "dataset_id": chosen.get("id"),
            "title": chosen.get("title"),
            "iso3": chosen.get("iso3"),
            "country": chosen.get("country"),
            "year": chosen.get("popyear") or chosen.get("year"),
            "category": chosen.get("_category") or args.category,
            "source_url": url,
            "license": "CC BY 4.0 (most WorldPop datasets)",
            "outputs": [output_path] + ([final_path] if final_path != output_path else []),
        }
        qa.update(inspect_geotiff(final_path))
        if args.bbox:
            try:
                w, s, e, n = (float(x) for x in args.bbox)
                qa["clip_bbox_wgs84"] = [w, s, e, n]
            except Exception:
                pass
        qa_path = (final_path.rsplit(".", 1)[0] + ".qa.json")
        write_qa(qa_path, qa)
    return 0


def cmd_bbox_clip(args: argparse.Namespace) -> int:
    """Clip an existing local GeoTIFF to a bbox (or --place)."""
    if not os.path.isfile(args.input):
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1
    if args.bbox:
        try:
            w, s, e, n = (float(x) for x in args.bbox)
        except (TypeError, ValueError):
            print("ERROR: --bbox must be 'west south east north' (4 floats).",
                  file=sys.stderr)
            return 1
    elif args.place:
        geo = geocode_place(args.place)
        if not geo:
            print(f"ERROR: could not resolve place '{args.place}'.", file=sys.stderr)
            return 1
        # Build a 25 km box around the geocoded centroid (rough; flat-earth)
        lat, lon = geo["lat"], geo["lon"]
        dlat, dlon = 0.25, 0.25 / max(0.1, abs(geo["lat"]) < 60 and 1 or 0.5)
        w, s, e, n = lon - dlon, lat - dlat, lon + dlon, lat + dlat
        print(f"Resolved '{args.place}' -> bbox ≈ [{w:.4f}, {s:.4f}, {e:.4f}, {n:.4f}]")
    else:
        print("ERROR: provide --bbox or --place.", file=sys.stderr)
        return 1
    out = args.output or args.input.replace(".tif", "_clipped.tif")
    if clip_geotiff_to_bbox(args.input, out, (w, s, e, n)):
        print(f"Clipped: {out}")
        if args.qa:
            qa = inspect_geotiff(out)
            qa.update({"skill": "worldpop-population", "clip_bbox_wgs84": [w, s, e, n],
                       "source": args.input})
            write_qa(out.rsplit(".", 1)[0] + ".qa.json", qa)
        return 0
    return 1


# ── Argparse ─────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="worldpop-population",
        description=("Search, download, and subset WorldPop population grid datasets "
                     "(GeoTIFF, CC BY 4.0, no API key)."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search
  python worldpop-population.py search --code CHN --year 2020 --type population
  python worldpop-population.py search --country "United States" --year 2020 --limit 5
  python worldpop-population.py list-categories
  python worldpop-population.py list-countries

  # Download by ISO+year+type (no manual id lookup)
  python worldpop-population.py download --code CHN --year 2020 --type population \\
      --output chn_pop_2020.tif --qa

  # Download by place name (Open-Meteo geocoding fallback when Nominatim is rate-limited)
  python worldpop-population.py download --place "Italy" --year 2020 \\
      --output ita_pop_2020.tif

  # Download with a bbox clip applied after download
  python worldpop-population.py download --code CHN --year 2020 \\
      --bbox 116.0 39.5 116.8 40.2 --output beijing_pop_2020.tif --qa

  # Subset an existing country file
  python worldpop-population.py bbox-clip --input chn_pop_2020.tif \\
      --bbox 116.0 39.5 116.8 40.2 --output beijing_pop_2020.tif
""",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    # search
    p_search = sub.add_parser("search", help="Search datasets")
    p_search.add_argument("--country", help="Country name substring (e.g. 'China')")
    p_search.add_argument("--code", help="ISO 3166-1 alpha-3 (e.g. CHN)")
    p_search.add_argument("--year", type=int, help="Population year (e.g. 2020)")
    p_search.add_argument("--type", choices=sorted(TYPE_TO_FAMILY.keys()),
                          help="Dataset family (population, births, age, ...)")
    p_search.add_argument("--category", help="WorldPop category alias (see list-categories)")
    p_search.add_argument("--limit", type=int, default=20, help="Max results (default 20)")
    p_search.add_argument("--json", action="store_true", help="Output as JSON")
    p_search.set_defaults(func=cmd_search)

    # list-categories
    p_lc = sub.add_parser("list-categories",
                          help="List top-level WorldPop categories (and curated sub-paths)")
    p_lc.add_argument("--json", action="store_true")
    p_lc.set_defaults(func=cmd_list_categories)

    # list-countries (kept for back-compat)
    p_lco = sub.add_parser("list-countries",
                           help="List countries with at least one population dataset")
    p_lco.add_argument("--json", action="store_true")
    p_lco.set_defaults(func=cmd_list_countries)

    # download
    p_dl = sub.add_parser("download", help="Download (and optionally clip) a dataset")
    p_dl.add_argument("--preset", choices=sorted(PRESETS.keys()),
                     help="Use a semantic preset (population-1km/population-100m/births/...)")
    p_dl.add_argument("--id", help="Dataset id (use 'search' to discover)")
    p_dl.add_argument("--country", help="Country name filter (alternative to --code)")
    p_dl.add_argument("--code", help="ISO3 filter")
    p_dl.add_argument("--place", help="Place name (resolved via Open-Meteo → ISO3)")
    p_dl.add_argument("--year", type=int, help="Population year")
    p_dl.add_argument("--type", choices=sorted(TYPE_TO_FAMILY.keys()),
                      help="Dataset family (default: population)")
    p_dl.add_argument("--category",
                      help="WorldPop category alias (default: pop/wpgp)")
    p_dl.add_argument("--limit", type=int, default=10,
                      help="Max hits to consider when picking the dataset (default 10)")
    p_dl.add_argument("--bbox", nargs=4, metavar=("W", "S", "E", "N"),
                      help="Clip to bbox (WGS84) after download")
    p_dl.add_argument("--output", help="Output GeoTIFF path (auto if omitted)")
    p_dl.add_argument("--qa", action="store_true", help="Write a .qa.json sidecar")
    p_dl.set_defaults(func=cmd_download)

    # bbox-clip
    p_clip = sub.add_parser("bbox-clip",
                            help="Clip an existing local GeoTIFF to a bbox or place")
    p_clip.add_argument("--input", required=True, help="Input GeoTIFF path")
    p_clip.add_argument("--bbox", nargs=4, metavar=("W", "S", "E", "N"),
                        help="Bbox (WGS84)")
    p_clip.add_argument("--place", help="Place name; uses 25 km box around centroid")
    p_clip.add_argument("--output", help="Output path")
    p_clip.add_argument("--qa", action="store_true")
    p_clip.set_defaults(func=cmd_bbox_clip)

    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
