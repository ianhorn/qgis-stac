"""Knowledge about how STAC catalogs are organised: which collections are point clouds, which asset is
the primary one, thumbnails (pure Python)."""

from __future__ import annotations

import urllib.parse
from typing import Iterable, List, Optional, Tuple

from .sources import is_default_uri
from .stac import Asset, Collection, Item

_POINTCLOUD_KEYWORDS = {"point cloud", "pointcloud", "point-cloud", "copc"}


def is_lidar_collection(collection: Collection) -> bool:
    """Whether a collection belongs on the Point Cloud tab, judged by what it declares: the STAC
    pointcloud extension, a "point cloud"/"copc" keyword, a point-cloud-looking item asset, or a
    conventional id ("laz-...", "...-copc"). A bare "lidar" keyword is deliberately NOT enough --
    LiDAR-derived DEMs carry it too, and belong on the raster tab."""
    if any("pointcloud" in ext.lower() for ext in collection.stac_extensions):
        return True
    if any(k.strip().lower() in _POINTCLOUD_KEYWORDS for k in collection.keywords):
        return True
    if any(k.lower() in ("pointcloud", "copc", "laz") for k in collection.item_asset_keys):
        return True
    cid = collection.id.lower()
    return cid.startswith("laz-") or cid.endswith("copc")


def split_collections(collections: Iterable[Collection]) -> Tuple[List[Collection], List[Collection]]:
    """Split into (raster, point cloud). The default source's collections come first, then each other
    source's, grouped by source and sorted by id (so numbered phases stay in order). Each collection goes
    to the tab for its kind."""
    ordered = sorted(collections, key=lambda c: (not is_default_uri(c.source), c.source, c.id))
    return [c for c in ordered if not is_lidar_collection(c)], [c for c in ordered if is_lidar_collection(c)]


_RASTER_SUFFIXES = (".tif", ".tiff", ".jp2", ".vrt")


def bbox_2d(bbox) -> Optional[Tuple[float, float, float, float]]:
    """(minx, miny, maxx, maxy) of a STAC bbox. A 3D bbox lists [minx, miny, minz, maxx, maxy, maxz]; taking its
    first four numbers would use the minimum height as a longitude (3DEP point clouds do this)."""
    if not bbox:
        return None
    values = [float(v) for v in bbox]
    if len(values) >= 6:
        return values[0], values[1], values[3], values[4]
    return (values[0], values[1], values[2], values[3]) if len(values) >= 4 else None


def is_raster_asset(asset: Asset) -> bool:
    """Whether an asset is an image GDAL can open as a map layer (a GeoTIFF or JPEG 2000 file)."""
    path = urllib.parse.urlparse(asset.href or "").path.lower()
    kind = (asset.type or "").lower()
    return path.endswith(_RASTER_SUFFIXES) or "geotiff" in kind or "jp2" in kind


def can_add_to_map(asset: Asset) -> bool:
    """Whether "add to map" makes sense for this asset: a raster, or a COPC point cloud (plain LAZ/LAS
    can't be streamed). Thumbnails, metadata files and the like are not."""
    return bool(asset.href) and (asset.is_copc or is_raster_asset(asset))


def primary_asset(item: Item, lidar: bool) -> Optional[Asset]:
    """The asset a tile is searched/loaded/downloaded for: the point cloud (preferring COPC over
    plain LAZ/LAS) on the LiDAR tab, otherwise the item's data asset (a COG)."""
    if lidar:
        assets = item.lidar_assets()
        return next((a for a in assets if a.is_copc), assets[0] if assets else None)
    return item.data_asset()


def thumbnail_href(item: Item, lidar: bool) -> Optional[str]:
    """The item's own thumbnail image URL, or None if it declares none."""
    asset = item.thumbnail_asset()
    return asset.href if asset is not None and asset.href else None


def item_crs(item: Item) -> str:
    """The CRS a tile declares in its STAC properties as "EPSG:N", or "" if it gives no EPSG code."""
    epsg = item.properties.get("proj:epsg")
    try:
        return f"EPSG:{int(epsg)}" if epsg else ""
    except (TypeError, ValueError):
        return ""


def format_size(size: Optional[int]) -> str:
    if size is None:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""
