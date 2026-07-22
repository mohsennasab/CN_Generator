"""
GCN10 Access Module
Stream Global Curve Number 10m (GCN10) raster data for a watershed area.

GCN10 is a global 10 m Curve Number dataset by Azzam and Cho (2026), built from
ESA WorldCover 2021 land cover and HYSOGs250m hydrologic soil groups. The data
is served as Cloud Optimized GeoTIFF tiles, which lets this module read only
the pixels that cover the user's watershed instead of downloading whole tiles.

Dataset license: Open Data Commons Open Database License (ODbL) v1.0.
Required attribution: "GCN10 -- Global 10 m Curve Number Dataset (Azzam et al.)"

Citation:
Azzam, M. A., Cho, H., 2026. GCN10: An MPI-parallelized framework for
processing global curve number rasters for hydrologic modeling.
SoftwareX 34, 102725. doi:10.1016/j.softx.2026.102725
"""

import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds, bounds as window_bounds
from rasterio.errors import RasterioIOError

try:
    from .zonal_exact import stats_from_values
except ImportError:  # when imported as a top-level module
    from zonal_exact import stats_from_values

GCN10_BASE_URL = "https://hydro.nmsu.edu/datasets/gcn10"
GCN10_NODATA = 255
GCN10_CRS = "EPSG:4326"

GCN10_ATTRIBUTION = "GCN10 -- Global 10 m Curve Number Dataset (Azzam et al.)"
GCN10_CITATION = (
    "Azzam, M. A., Cho, H., 2026. GCN10: An MPI-parallelized framework for "
    "processing global curve number rasters for hydrologic modeling. "
    "SoftwareX 34, 102725. doi:10.1016/j.softx.2026.102725"
)
GCN10_LICENSE_NOTE = (
    "GCN10 data is distributed under the Open Data Commons Open Database "
    "License (ODbL) v1.0."
)
GCN10_DATASET_URL = "https://hydro.nmsu.edu/datasets/gcn10/"

# UI label -> filename code
HYDROLOGIC_CONDITIONS = {"Poor": "p", "Fair": "f", "Good": "g"}
ARC_CONDITIONS = {"ARC I": "i", "ARC II": "ii", "ARC III": "iii"}
DRAINAGE_CONDITIONS = {"Drained": "drained", "Undrained": "undrained"}

# Rasterio/GDAL settings for efficient remote COG reads
_REMOTE_READ_OPTIONS = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_TIMEOUT": "60",
    "GDAL_HTTP_CONNECTTIMEOUT": "15",
    "GDAL_HTTP_MAX_RETRY": "2",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": "26214400",
}

_APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
TILE_INDEX_PATH = _APP_DIR / "data" / "gcn10" / "gcn10_tile_index.gpkg"

# Substrings that identify TLS certificate failures. Corporate VPNs and
# firewalls that inspect HTTPS traffic re-sign it with their own root
# certificate, which the HTTP client used by GDAL may not trust.
_CERT_ERROR_MARKERS = ("schannel", "ssl", "certificate", "cert_trust", "cert ")


def _is_certificate_error(exc) -> bool:
    """Check whether a rasterio/GDAL error looks like a TLS certificate failure."""
    text = str(exc).lower()
    return any(marker in text for marker in _CERT_ERROR_MARKERS)


def _ca_bundle_options() -> dict:
    """Use a custom CA bundle file when one is configured in the environment."""
    for var in ("CN_CA_BUNDLE", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        path = os.environ.get(var)
        if path and Path(path).exists():
            return {"GDAL_CURL_CA_BUNDLE": path}
    return {}


def _insecure_ssl_forced() -> bool:
    """Check the CN_GCN10_INSECURE_SSL environment variable."""
    value = os.environ.get("CN_GCN10_INSECURE_SSL", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def variant_label(hydrologic_condition: str, arc: str, drainage: str) -> str:
    """Build a short human-readable label for a GCN10 variant."""
    return f"GCN10 ({hydrologic_condition}, {arc}, {drainage})"


def variant_slug(hydrologic_condition: str, arc: str, drainage: str) -> str:
    """Build a filename-safe slug for a GCN10 variant."""
    hc = HYDROLOGIC_CONDITIONS[hydrologic_condition]
    arc_code = ARC_CONDITIONS[arc]
    drain = DRAINAGE_CONDITIONS[drainage]
    return f"gcn10_{hc}_{arc_code}_{drain}"


def tile_url(hydrologic_condition: str, arc: str, drainage: str, block_fid: int) -> str:
    """Build the remote URL for one GCN10 tile."""
    hc = HYDROLOGIC_CONDITIONS[hydrologic_condition]
    arc_code = ARC_CONDITIONS[arc]
    folder = f"cn_rasters_{DRAINAGE_CONDITIONS[drainage]}"
    return f"{GCN10_BASE_URL}/{folder}/cn_{hc}_{arc_code}_{block_fid}.tif"


def load_tile_index() -> gpd.GeoDataFrame:
    """Load the bundled GCN10 tile index."""
    if not TILE_INDEX_PATH.exists():
        raise RuntimeError(
            "The GCN10 tile index file is missing from the app installation "
            f"(expected at {TILE_INDEX_PATH})."
        )
    return gpd.read_file(TILE_INDEX_PATH)


def find_block_fids(aoi_4326: gpd.GeoDataFrame) -> list:
    """Find GCN10 tile numbers that intersect the area of interest."""
    tile_index = load_tile_index()
    aoi_geom = aoi_4326.union_all()
    hits = tile_index[tile_index.intersects(aoi_geom)]
    return sorted(int(fid) for fid in hits["block_fid"])


def _create_gcn10_colormap():
    """Colormap for the GCN10 GeoTIFF, matching the app's CN color classes."""
    colormap = {}
    for cn in range(0, 101):
        if cn < 30:
            colormap[cn] = (0, 0, 255, 255)
        elif cn < 50:
            colormap[cn] = (100, 150, 255, 255)
        elif cn < 70:
            colormap[cn] = (255, 255, 0, 255)
        elif cn < 85:
            colormap[cn] = (255, 165, 0, 255)
        else:
            colormap[cn] = (255, 0, 0, 255)
    colormap[GCN10_NODATA] = (0, 0, 0, 0)
    return colormap


def fetch_gcn10_raster(
    aoi_gdf: gpd.GeoDataFrame,
    hydrologic_condition: str,
    arc: str,
    drainage: str,
    output_path: str,
    progress_callback=None,
    message_callback=None,
) -> dict:
    """
    Stream the GCN10 raster for the area of interest and save a clipped GeoTIFF.

    Only the pixel window covering the area of interest is read from each
    remote tile, so a typical watershed transfers a few megabytes instead of
    full tiles. The output keeps the native 10 m EPSG:4326 GCN10 grid with
    NoData 255 and is clipped to the area of interest boundary.

    If the server certificate cannot be verified, which happens on corporate
    VPNs and firewalls that inspect HTTPS traffic, the download is retried
    once with certificate verification turned off. This only affects the
    GCN10 read; it does not change any computed values.

    Parameters:
    -----------
    aoi_gdf : GeoDataFrame
        Area of interest polygons (any CRS with valid metadata).
    hydrologic_condition : str
        "Poor", "Fair", or "Good".
    arc : str
        "ARC I", "ARC II", or "ARC III".
    drainage : str
        "Drained" or "Undrained".
    output_path : str
        Path for the clipped output GeoTIFF.
    progress_callback : callable, optional
        Called as progress_callback(done_tiles, total_tiles).
    message_callback : callable, optional
        Called with plain-text status messages worth logging, such as the
        certificate verification fallback warning.

    Returns:
    --------
    dict with keys: path, label, block_fids, width, height, stats
    """
    if aoi_gdf is None or len(aoi_gdf) == 0:
        raise RuntimeError("GCN10 processing needs a boundary polygon to clip to.")
    if aoi_gdf.crs is None:
        raise RuntimeError(
            "The boundary layer has no coordinate system information, so it "
            "cannot be matched to the GCN10 grid. Please provide a layer with "
            "a defined CRS (for shapefiles, include the .prj file)."
        )

    aoi_4326 = aoi_gdf.to_crs(GCN10_CRS)
    block_fids = find_block_fids(aoi_4326)
    if not block_fids:
        raise RuntimeError(
            "The provided boundary does not overlap the GCN10 dataset tiles. "
            "GCN10 covers global land areas; please check the boundary layer."
        )

    minx, miny, maxx, maxy = aoi_4326.total_bounds
    label = variant_label(hydrologic_condition, arc, drainage)
    total = len(block_fids)

    def _stream_tiles(extra_options):
        """Read every tile window and mosaic it; returns the grid pieces."""
        mosaic = None
        out_transform = None
        aligned_bounds = None
        out_height = out_width = None
        with rasterio.Env(**{**_REMOTE_READ_OPTIONS, **extra_options}):
            for done, block_fid in enumerate(block_fids):
                url = f"/vsicurl/{tile_url(hydrologic_condition, arc, drainage, block_fid)}"
                with rasterio.open(url) as src:
                    if mosaic is None:
                        # Snap the AOI bounds outward to the GCN10 pixel grid
                        window = from_bounds(minx, miny, maxx, maxy, src.transform)
                        window = window.round_offsets(op="floor").round_lengths(op="ceil")
                        out_transform = src.window_transform(window)
                        aligned_bounds = window_bounds(window, src.transform)
                        out_height = int(window.height)
                        out_width = int(window.width)
                        mosaic = np.full(
                            (out_height, out_width), GCN10_NODATA, dtype=np.uint8
                        )
                    window = from_bounds(*aligned_bounds, src.transform)
                    data = src.read(
                        1,
                        window=window,
                        out_shape=(out_height, out_width),
                        boundless=True,
                        fill_value=GCN10_NODATA,
                    )
                fill = mosaic == GCN10_NODATA
                mosaic[fill] = data[fill]
                if progress_callback is not None:
                    progress_callback(done + 1, total)
        return mosaic, out_transform, out_height, out_width

    def _say(message):
        if message_callback is not None:
            message_callback(message)
        else:
            print(message)

    # First attempt verifies the server certificate normally. If the read
    # fails, retry once with certificate verification turned off. Corporate
    # VPNs and firewalls that inspect HTTPS traffic re-sign it with their own
    # root certificate, which GDAL's HTTP client rejects; depending on the
    # network, that failure can also surface as a generic "does not exist"
    # error. If there is truly no internet connection, the retry fails the
    # same way and the user still gets a clear message.
    # CPL_VSIL_CURL_NON_CACHED makes the retry re-request the tiles instead
    # of reusing GDAL's cached failure from the first attempt.
    base_options = _ca_bundle_options()
    insecure_options = {
        **base_options,
        "GDAL_HTTP_UNSAFESSL": "YES",
        "CPL_VSIL_CURL_NON_CACHED": f"/vsicurl/{GCN10_BASE_URL}",
    }
    if _insecure_ssl_forced():
        _say(
            "CN_GCN10_INSECURE_SSL is set: reading GCN10 with certificate "
            "verification turned off."
        )
        attempts = [insecure_options]
    else:
        attempts = [dict(base_options), insecure_options]

    mosaic = out_transform = out_height = out_width = None
    for attempt_index, options in enumerate(attempts):
        try:
            mosaic, out_transform, out_height, out_width = _stream_tiles(options)
            break
        except RasterioIOError as exc:
            if attempt_index + 1 < len(attempts):
                if _is_certificate_error(exc):
                    _say(
                        "The GCN10 server certificate could not be verified. "
                        "This usually happens on corporate VPNs or networks "
                        "that inspect secure traffic. Retrying the GCN10 "
                        "download with certificate verification turned off. "
                        "This only affects the GCN10 read; results are not "
                        "changed."
                    )
                else:
                    _say(
                        "The first GCN10 read attempt failed "
                        f"({exc}). Retrying once with relaxed certificate "
                        "verification in case a VPN or firewall is "
                        "interfering with the connection."
                    )
                continue
            raise RuntimeError(
                "Could not read GCN10 data from the server "
                f"({GCN10_BASE_URL}). Check your internet connection and try "
                "again, or turn off the GCN10 option to run without it. "
                f"Details: {exc}"
            ) from exc

    # Clip exactly to the actual boundary, not just its bounding box. A cell
    # is kept only when its center falls inside the boundary polygon, the
    # same rule a standard GIS raster clip (Extract by Mask) uses, so no
    # cell outside the boundary stays in the output raster.
    outside = geometry_mask(
        aoi_4326.geometry,
        out_shape=(out_height, out_width),
        transform=out_transform,
        invert=False,
        all_touched=False,
    )
    mosaic[outside] = GCN10_NODATA

    valid = mosaic[mosaic != GCN10_NODATA]
    if valid.size == 0:
        raise RuntimeError(
            "GCN10 returned no data cells inside the provided boundary. "
            "The area may fall entirely on GCN10 NoData (for example, open "
            "ocean)."
        )

    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=out_height,
        width=out_width,
        count=1,
        dtype=rasterio.uint8,
        crs=GCN10_CRS,
        transform=out_transform,
        nodata=GCN10_NODATA,
        compress="lzw",
    ) as dst:
        dst.write(mosaic, 1)
        dst.write_colormap(1, _create_gcn10_colormap())

    # Overall statistics for the whole area of interest, computed from exactly
    # the cells that survived the clip. This matches the per-watershed zonal
    # statistics, which use the same cell-center rule.
    stats = stats_from_values(valid)

    return {
        "path": output_path,
        "label": label,
        "block_fids": block_fids,
        "width": out_width,
        "height": out_height,
        "stats": stats,
    }


def read_display_image(raster_path: str, max_dimension: int = 2048):
    """
    Read a decimated copy of a clipped GCN10 raster for map display.

    This only affects how the map overlay is drawn. The downloadable GeoTIFF
    and all statistics keep the full native resolution.

    Returns:
    --------
    tuple : (uint8 array, (south, west, north, east) bounds)
    """
    with rasterio.open(raster_path) as src:
        scale = max(src.width, src.height) / float(max_dimension)
        if scale > 1:
            out_shape = (
                max(1, int(src.height / scale)),
                max(1, int(src.width / scale)),
            )
        else:
            out_shape = (src.height, src.width)
        data = src.read(1, out_shape=out_shape)
        bounds = src.bounds
    return data, (bounds.bottom, bounds.left, bounds.top, bounds.right)
