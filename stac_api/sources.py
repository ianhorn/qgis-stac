"""Which STAC APIs the dock searches: the default Microsoft Planetary Computer catalog, plus any other
API the user adds -- typed in by hand, or picked from STAC Index (https://stacindex.org), where
KyFromAbove is just another entry.

Ported from the ArcGIS Pro add-in (stac-arcgispro-addin: StacApiSource.cs, StacIndexClient.cs,
AddApiSourceDialog). Pure Python -- no QGIS import -- so the parsing/filtering is unit-testable;
fetching and persistence (QgsSettings) live in the QGIS-side callers.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, replace
from typing import Any, Iterable, List, Optional

from .stac import DEFAULT_BASE_URI

STAC_INDEX_URL = "https://stacindex.org/api/catalogs"
KYFROMABOVE_NAME = "KyFromAbove"
KYFROMABOVE_BASE_URI = "https://spved5ihrl.execute-api.us-west-2.amazonaws.com"  # offered as a pickable example source
DEFAULT_NAME = "Microsoft Planetary Computer"
_PC_HOST = "planetarycomputer.microsoft.com"
_SUMMARY_MAX = 240


@dataclass(frozen=True)
class ApiSource:
    name: str
    base_uri: str
    is_default: bool = False
    # The id of a QGIS authentication configuration (Settings > Options > Authentication) used for this
    # API and for reading its files. Only the id is stored here: the secrets stay in QGIS's encrypted database.
    auth_cfg: str = ""


DEFAULT_SOURCE = ApiSource(DEFAULT_NAME, DEFAULT_BASE_URI, is_default=True)


def normalize_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _is_planetary_computer(url: str) -> bool:
    return urllib.parse.urlparse(normalize_url(url)).netloc.lower() == _PC_HOST


def is_default_uri(base_uri: str) -> bool:
    """True for the default catalog (Planetary Computer) -- also for "" (an item/collection whose source
    was never recorded)."""
    uri = normalize_url(base_uri)
    return not uri or uri.lower() == normalize_url(DEFAULT_BASE_URI).lower() or _is_planetary_computer(uri)


def is_valid_api_url(url: str) -> bool:
    """A plausible http(s) URL -- the check for a URL typed in by hand."""
    parsed = urllib.parse.urlparse(normalize_url(url))
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def is_usable_base_url(url: str) -> bool:
    """Whether a STAC Index entry's URL can be a search root: this plugin talks to {base}/collections
    and {base}/search, so static catalogs mislabeled as APIs (".json"), openEO endpoints (a different
    API) and URLs carrying a query string or API key are dropped -- same rules as the add-in."""
    if not is_valid_api_url(url):
        return False
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.query:
        return False
    if parsed.path.lower().endswith(".json"):
        return False
    if "openeo" in url.lower():
        return False
    return True


@dataclass(frozen=True)
class CatalogEntry:
    """One pickable STAC API in the "add a source" dialog."""

    title: str
    name: str  # what the dialog's Name box is filled with
    url: str
    detail: str
    is_builtin: bool = False
    is_preset: bool = False  # built-in presets are listed first, above the STAC Index entries


BUILTIN_ENTRY = CatalogEntry(
    "Microsoft Planetary Computer (default)",
    DEFAULT_NAME,
    DEFAULT_BASE_URI,
    f"{DEFAULT_BASE_URI}\n\nMicrosoft's open Planetary Computer catalog: Sentinel, Landsat, NAIP, "
    "elevation and many other public datasets.",
    is_builtin=True,
)

KYFROMABOVE_ENTRY = CatalogEntry(
    "KyFromAbove",
    KYFROMABOVE_NAME,
    KYFROMABOVE_BASE_URI,
    f"{KYFROMABOVE_BASE_URI}\n\nKentucky Aerial Photography and Elevation Data (KYAPED), 2010 - present: "
    "leaf-off orthoimagery, LiDAR point clouds, and LiDAR-derived DEMs.",
    is_preset=True,
)


def _preset(title: str, url: str, summary: str) -> CatalogEntry:
    return CatalogEntry(title, title, url, f"{url}\n\n{summary}", is_preset=True)


# Well-known public STAC APIs, always offered (so they work even when STAC Index can't be reached). Only
# APIs whose /collections and /search work anonymously are listed; static catalogs and APIs that need a
# login to search are left to STAC Index or a typed-in URL.
PRESET_ENTRIES = (
    _preset("Earth Search (Element 84)", "https://earth-search.aws.element84.com/v1",
            "Sentinel-2, Landsat, NAIP and Copernicus DEM on AWS. Some collections are requester-pays."),
    _preset("Copernicus Data Space", "https://stac.dataspace.copernicus.eu/v1",
            "Copernicus Sentinel missions. Searching is anonymous; downloading files needs a free account's S3 keys."),
    _preset("Digital Earth Australia", "https://explorer.sandbox.dea.ga.gov.au/stac",
            "Geoscience Australia analysis-ready Landsat and Sentinel data, water observations and more."),
    _preset("INPE Brazil Data Cube", "https://data.inpe.br/bdc/stac/v1",
            "Brazilian satellite data cubes (Landsat, Sentinel, CBERS)."),
    _preset("OpenAerialMap", "https://api.imagery.hotosm.org/stac",
            "Openly licensed community and humanitarian aerial imagery."),
    _preset("Earth Genome Sentinel-2 mosaics", "https://stac.earthgenome.org",
            "Cloud-free Sentinel-2 mosaics."),
    _preset("USGS Astrogeology", "https://stac.astrogeology.usgs.gov/api",
            "Planetary data for the Moon, Mars and other bodies."),
    _preset("HUB Ocean - Ocean Data Platform", "https://api.hubocean.earth/api/stac",
            "Ocean datasets from the HUB Ocean Data Platform."),
    _preset("JAXA Earth API", "https://data.earth.jaxa.jp/app/stac/v2",
            "JAXA Earth observation datasets."),
)


def _known_urls() -> set:
    return {normalize_url(e.url).lower() for e in PRESET_ENTRIES} | {normalize_url(KYFROMABOVE_BASE_URI).lower()}


def _presets_sorted() -> List[CatalogEntry]:
    return sorted(list(PRESET_ENTRIES) + [KYFROMABOVE_ENTRY], key=lambda e: e.title.casefold())


def fallback_entries() -> List[CatalogEntry]:
    """What the catalog picker offers when STAC Index can't be reached."""
    return [BUILTIN_ENTRY] + _presets_sorted()


def parse_stac_index(data: Any) -> List[CatalogEntry]:
    """Public, searchable STAC APIs from a STAC Index /api/catalogs response: the default Microsoft
    Planetary Computer entry always first (so it's the way back after switching APIs, even if STAC
    Index lists nothing usable), then the rest sorted by title. KyFromAbove sorts in among them, and is
    added in its place if STAC Index doesn't list it. Private/protected catalogs are left out: there's
    no way to supply credentials."""
    entries: List[CatalogEntry] = []
    known = _known_urls()
    for el in data if isinstance(data, list) else []:
        if not isinstance(el, dict):
            continue
        if el.get("isApi") is not True or el.get("isPrivate") is True or el.get("access") != "public":
            continue
        title = (el.get("title") or "").strip()
        url = (el.get("url") or "").strip()
        if not title or not is_usable_base_url(url):
            continue
        base = normalize_url(url)
        if is_default_uri(base) or base.lower() in known:
            continue  # BUILTIN_ENTRY / PRESET_ENTRIES / KYFROMABOVE_ENTRY cover them
        summary = (el.get("summary") or "").strip()
        if len(summary) > _SUMMARY_MAX:
            summary = summary[:_SUMMARY_MAX].rstrip() + "..."
        detail = f"{url}\n\n{summary}" if summary else url
        entries.append(CatalogEntry(title, title, base, detail))
    entries.sort(key=lambda e: e.title.casefold())
    return [BUILTIN_ENTRY] + _presets_sorted() + entries


def serialize_sources(sources: Iterable[ApiSource]) -> str:
    return json.dumps(
        [{"name": s.name, "base_uri": s.base_uri, "auth_cfg": s.auth_cfg} for s in sources]
    )


def deserialize_sources(text: Optional[str]) -> List[ApiSource]:
    """The saved source list, or just the default catalog if nothing (valid) was saved. The
    default entry is recognized by URL rather than trusted from the saved data, so it can't be
    duplicated or lose its is_default flag."""
    try:
        raw = json.loads(text) if text else None
    except ValueError:
        raw = None
    sources: List[ApiSource] = []
    seen = set()
    for el in raw if isinstance(raw, list) else []:
        if not isinstance(el, dict):
            continue
        uri = normalize_url(str(el.get("base_uri") or ""))
        if not is_valid_api_url(uri) or uri.lower() in seen:
            continue
        seen.add(uri.lower())
        if is_default_uri(uri):
            sources.append(DEFAULT_SOURCE)
        else:
            name = str(el.get("name") or "").strip() or uri
            sources.append(ApiSource(name, uri, auth_cfg=_clean_cfg(el.get("auth_cfg"))))
    return sources or [DEFAULT_SOURCE]


def _clean_cfg(value) -> str:
    """A QGIS auth config id (7 letters/digits) or "" -- anything else saved by hand is dropped."""
    text = str(value or "").strip()
    return text if text.isalnum() and len(text) <= 32 else ""


def add_source(sources: List[ApiSource], name: str, url: str, replace: bool, auth_cfg: str = "") -> List[ApiSource]:
    """The source list after adding (or, with replace, switching to) the API at url. Picking the
    default catalog's URL yields DEFAULT_SOURCE itself, not a user-named copy."""
    uri = normalize_url(url)
    new = (
        DEFAULT_SOURCE
        if is_default_uri(uri)
        else ApiSource(
            (name or "").strip() or uri,
            uri,
            auth_cfg=_clean_cfg(auth_cfg),
        )
    )
    if replace:
        return [new]
    if any(normalize_url(s.base_uri).lower() == uri.lower() for s in sources):
        return list(sources)
    return list(sources) + [new]


def source_name(sources: Iterable[ApiSource], base_uri: str) -> str:
    uri = normalize_url(base_uri).lower()
    for s in sources:
        if normalize_url(s.base_uri).lower() == uri:
            return s.name
    if normalize_url(base_uri).lower() == normalize_url(KYFROMABOVE_BASE_URI).lower():
        return KYFROMABOVE_NAME
    return DEFAULT_NAME if is_default_uri(base_uri) else base_uri


def _editable(source: ApiSource, uri: str) -> bool:
    """A source whose login can be set: any but the default catalog (public)."""
    return not is_default_uri(source.base_uri) and normalize_url(source.base_uri).lower() == uri


def with_auth_cfg(sources: Iterable[ApiSource], base_uri: str, auth_cfg: str) -> List[ApiSource]:
    """The source list with one source's authentication config set (or cleared, with ""). The default
    catalog is never changed."""
    uri = normalize_url(base_uri).lower()
    cfg = _clean_cfg(auth_cfg)
    return [replace(s, auth_cfg=cfg) if _editable(s, uri) else s for s in sources]


def auth_cfg_for(sources: Iterable[ApiSource], base_uri: str) -> str:
    """The authentication config id set for a source, or "" if none."""
    uri = normalize_url(base_uri).lower()
    for s in sources:
        if normalize_url(s.base_uri).lower() == uri:
            return s.auth_cfg
    return ""
