from qgis_stac.catalog import is_lidar_collection, item_crs, split_collections, thumbnail_href
from qgis_stac.sources import (
    BUILTIN_ENTRY,
    DEFAULT_BASE_URI,
    DEFAULT_SOURCE,
    KYFROMABOVE_BASE_URI,
    KYFROMABOVE_ENTRY,
    PRESET_ENTRIES,
    ApiSource,
    add_source,
    deserialize_sources,
    fallback_entries,
    is_default_uri,
    is_usable_base_url,
    is_valid_api_url,
    parse_stac_index,
    serialize_sources,
    source_name,
)
from qgis_stac.stac import Collection, Item

OTHER = "https://earth-search.aws.element84.com/v1"
_FIXED = set(PRESET_ENTRIES) | {KYFROMABOVE_ENTRY}


def _entry(title, url, **kw):
    base = {"title": title, "url": url, "isApi": True, "isPrivate": False, "access": "public", "summary": ""}
    base.update(kw)
    return base


def test_parse_stac_index_filters_like_the_addin():
    data = [
        _entry("Zeta API", "https://zeta.example/stac/"),
        _entry("Alpha API", "https://alpha.example/v1", summary="x" * 300),
        _entry("Static catalog", "https://s3.example/catalog.json"),
        _entry("Keyed", "https://keyed.example/stac?apikey=1"),
        _entry("openEO thing", "https://openeo.example/"),
        _entry("Private", "https://private.example/", isPrivate=True),
        _entry("Protected", "https://protected.example/", access="protected"),
        _entry("Not an API", "https://static.example/", isApi=False),
        _entry("KyFromAbove duplicate", KYFROMABOVE_BASE_URI + "/"),
        _entry("", "https://untitled.example/"),
        "garbage",
    ]
    entries = parse_stac_index(data)
    assert entries[0] == BUILTIN_ENTRY
    assert [e.title for e in entries[1:] if e not in _FIXED] == ["Alpha API", "Zeta API"]
    by_title = {e.title: e for e in entries}
    assert by_title["Zeta API"].url == "https://zeta.example/stac"  # trailing slash trimmed
    assert by_title["Alpha API"].detail.endswith("...")  # long summary truncated


def test_parse_stac_index_lists_default_first_then_a_to_z_with_kyfromabove_in_place():
    data = [
        _entry("Alpha API", "https://alpha.example/v1"),
        _entry("Zeta API", "https://zeta.example/stac"),
        _entry("Microsoft Planetary Computer STAC API", "https://planetarycomputer.microsoft.com/api/stac/v1/"),
        _entry("Earth Search", OTHER),
    ]
    entries = parse_stac_index(data)
    assert entries[0] == BUILTIN_ENTRY
    # The index's own Planetary Computer entry is the default, listed once at the top.
    titles = [e.title for e in entries[1:] if e not in _FIXED]
    assert titles == sorted(titles, key=str.casefold)
    assert entries[1 : 1 + len(_FIXED)] == fallback_entries()[1:]  # presets come first, above the index entries
    assert titles == ["Alpha API", "Zeta API"] and KYFROMABOVE_ENTRY in entries
    # The index's own Earth Search entry is the preset's URL, so it's listed once, under the preset's title.
    assert [e.url for e in entries].count(OTHER) == 1 and "Earth Search" not in titles


def test_parse_stac_index_lists_default_then_a_to_z():
    entries = parse_stac_index([_entry("Zeta API", "https://zeta.example/stac"), _entry("Alpha API", "https://alpha.example/v1")])
    assert [e.title for e in entries[1:] if e not in _FIXED] == ["Alpha API", "Zeta API"]


def test_parse_stac_index_on_bad_data_still_offers_default_and_presets():
    assert parse_stac_index(None) == fallback_entries()
    assert parse_stac_index({"not": "a list"}) == fallback_entries()
    assert fallback_entries()[0] == BUILTIN_ENTRY
    assert set(fallback_entries()[1:]) == set(PRESET_ENTRIES) | {KYFROMABOVE_ENTRY}


def test_preset_urls_are_usable_and_unique():
    urls = [e.url.lower() for e in PRESET_ENTRIES]
    assert len(urls) == len(set(urls))
    assert all(is_usable_base_url(u) and not is_default_uri(u) for u in urls)


def test_url_checks():
    assert is_valid_api_url("https://a.example/stac")
    assert not is_valid_api_url("ftp://a.example")
    assert not is_valid_api_url("not a url")
    assert not is_usable_base_url("https://a.example/catalog.JSON")
    assert is_default_uri(DEFAULT_BASE_URI + "/") and is_default_uri("") and not is_default_uri(OTHER)
    assert not is_default_uri(KYFROMABOVE_BASE_URI)


def test_sources_round_trip_and_default_fallback():
    sources = [DEFAULT_SOURCE, ApiSource("Earth Search", OTHER)]
    assert deserialize_sources(serialize_sources(sources)) == sources
    assert deserialize_sources(None) == [DEFAULT_SOURCE]
    assert deserialize_sources("not json") == [DEFAULT_SOURCE]
    assert deserialize_sources('[{"name": "x", "base_uri": "nonsense"}]') == [DEFAULT_SOURCE]
    # Only other APIs saved (the user replaced KyFromAbove) -- respected, not forced back.
    assert deserialize_sources(serialize_sources([ApiSource("ES", OTHER)])) == [ApiSource("ES", OTHER)]
    # A saved built-in entry is recognized by URL, keeping its default flag.
    assert deserialize_sources('[{"name": "renamed", "base_uri": "%s"}]' % DEFAULT_BASE_URI) == [DEFAULT_SOURCE]


def test_add_and_replace_sources():
    added = add_source([DEFAULT_SOURCE], "Earth Search", OTHER + "/", replace=False)
    assert added == [DEFAULT_SOURCE, ApiSource("Earth Search", OTHER)]
    assert add_source(added, "dup", OTHER, replace=False) == added  # already active
    assert add_source(added, "Earth Search", OTHER, replace=True) == [ApiSource("Earth Search", OTHER)]
    # Picking the default catalog's URL is the way back, as the built-in source itself.
    assert add_source([ApiSource("ES", OTHER)], "whatever", DEFAULT_BASE_URI, replace=True) == [DEFAULT_SOURCE]
    assert add_source([DEFAULT_SOURCE], "", OTHER, replace=False)[1].name == OTHER  # blank name -> URL
    assert source_name(added, OTHER) == "Earth Search"


def test_lidar_detection_for_other_sources():
    def c(**kw):
        return Collection(id=kw.pop("id", "x"), source=OTHER, **kw)

    assert is_lidar_collection(c(stac_extensions=["https://stac-extensions.github.io/pointcloud/v1.0.0/schema.json"]))
    assert is_lidar_collection(c(keywords=["Point Cloud"]))
    assert is_lidar_collection(c(item_asset_keys=["copc"]))
    # A LiDAR-derived DEM is a raster -- "lidar" alone isn't enough.
    assert not is_lidar_collection(c(keywords=["LiDAR", "DEM"]))
    # Conventional ids count too.
    assert is_lidar_collection(c(id="laz-thing"))
    assert is_lidar_collection(c(id="3dep-lidar-copc"))
    assert not is_lidar_collection(c(id="3dep-lidar-hag"))


def test_split_puts_default_first_then_other_sources():
    cols = [Collection(id="b", source=OTHER), Collection(id="z"), Collection(id="a")]
    imagery, _ = split_collections(cols)
    assert [(x.id, x.source) for x in imagery] == [("a", ""), ("z", ""), ("b", OTHER)]


def test_each_collection_goes_to_one_tab_by_kind():
    cols = [Collection(id="laz-phase3"), Collection(id="dem-phase2"), Collection(id="x", source=OTHER)]
    imagery, lidar = split_collections(cols)
    assert [c.id for c in imagery] == ["dem-phase2", "x"]
    assert [c.id for c in lidar] == ["laz-phase3"]


def test_thumbnail_is_only_the_items_own_asset():
    item = Item(id="t", collection="laz-phase3", source=OTHER)
    assert thumbnail_href(item, lidar=True) is None
    assert item_crs(Item(properties={"proj:epsg": 3089})) == "EPSG:3089"
    assert item_crs(Item(properties={})) == ""
    assert item_crs(Item(properties={"proj:epsg": "junk"})) == ""


def test_saved_per_source_tile_servers_from_older_versions_are_ignored():
    """The tile server is one global setting now (server_layers.tiler_url): a saved per-source
    "tiler_url" is dropped on load, not carried along."""
    old = '[{"name": "ES", "base_uri": "%s", "tiler_url": "https://titiler.example.com"}]' % OTHER
    assert deserialize_sources(old) == [ApiSource("ES", OTHER)]
    assert "tiler_url" not in serialize_sources([ApiSource("ES", OTHER)])


def test_data_asset_key():
    it = Item.from_dict({"id": "x", "assets": {"thumbnail": {"href": "t.png"}, "visual": {"href": "v.tif"}}})
    assert it.data_asset_key() == "visual" and Item().data_asset_key() is None


def test_item_json_text_and_html():
    from qgis_stac.item_json import item_json_text, json_to_html

    raw = {"id": "t1", "properties": {"note": "a <b> & c"}, "assets": {"data": {"href": "https://x.example/a.tif?sig=1&b=2"}}}
    item = Item.from_dict(raw)
    assert '"id": "t1"' in item_json_text(item) and item_json_text(item).startswith("{\n  ")
    page = json_to_html(item_json_text(item))
    assert "a &lt;b&gt; &amp; c" in page  # escaped
    assert '<a href="https://x.example/a.tif?sig=1&amp;b=2">https://x.example/a.tif?sig=1&amp;b=2</a>' in page
    # An Item built by hand (no raw document) still renders from its fields.
    assert '"id": "h"' in item_json_text(Item(id="h"))


def test_auth_cfg_is_saved_cleaned_and_looked_up():
    from qgis_stac.sources import (
        ApiSource,
        auth_cfg_for,
        deserialize_sources,
        serialize_sources,
        with_auth_cfg,
    )

    src = ApiSource("Private", OTHER, auth_cfg="abc1234")
    again = deserialize_sources(serialize_sources([src]))
    assert [s.auth_cfg for s in again if not s.is_default] == ["abc1234"]
    # an id that isn't a plain alphanumeric (something edited in by hand) is dropped, not trusted
    text = serialize_sources([src]).replace("abc1234", "bad id; drop")
    assert [s.auth_cfg for s in deserialize_sources(text) if not s.is_default] == [""]
    assert auth_cfg_for([src], OTHER + "/") == "abc1234" and auth_cfg_for([src], "https://elsewhere.org") == ""
    cleared = with_auth_cfg([src], OTHER, "")
    assert cleared[0].auth_cfg == "" and with_auth_cfg([DEFAULT_SOURCE], DEFAULT_BASE_URI, "x1")[0].auth_cfg == ""


def test_add_source_takes_a_login():
    added = add_source([DEFAULT_SOURCE], "Private", OTHER, replace=False, auth_cfg="xyz9876")
    assert added[-1].auth_cfg == "xyz9876"
    assert add_source([DEFAULT_SOURCE], "Private", OTHER, replace=False)[-1].auth_cfg == ""
