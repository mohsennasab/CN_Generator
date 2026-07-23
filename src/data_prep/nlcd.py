"""
Data Preparation - NLCD Land Cover (official MRLC and USGS services)
Download National Land Cover Database land cover for a watershed, ready to
import into the CN workflow.

Two official, anonymous, free services are used, both on the native 30 m
EPSG:5070 (Conus Albers) NLCD grid for the conterminous United States:

- Epoch NLCD releases (2001-2021): the MRLC GeoServer Web Coverage Service
  at https://www.mrlc.gov/geoserver/wcs, one coverage per release year.
- Annual NLCD Collection 1 (1985 onward, including the most recent years):
  the USGS EROS time-enabled Web Coverage Service behind the official MRLC
  viewer at https://dmsdata.cr.usgs.gov/geoserver/, one coverage with a
  yearly time axis selected through the WCS 1.0.0 TIME parameter.

Years 2001-2021 use the epoch releases; every other year comes from Annual
NLCD, and the year dropdown labels which product a year comes from. When
the primary service for a year cannot be reached and the other service also
offers that year, the download falls back to it with a log message.
Available years are discovered live from both services so newly published
years appear automatically, with built-in fallback lists used offline.

Large watersheds are downloaded as a grid of small tiles instead of one
giant request, so each transfer stays a few megabytes, progress is visible,
and a single failed request does not lose the whole download.

Credit: U.S. Geological Survey / Multi-Resolution Land Characteristics
(MRLC) Consortium, National Land Cover Database. https://www.mrlc.gov/
"""

import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rasterio
from rasterio.io import MemoryFile

from .common import (
    MAX_RASTER_CELLS,
    PREP_CELL_SIZE,
    PREP_CRS,
    aligned_grid,
    clip_array_to_aoi,
    polygonize_classified_raster,
    prepare_aoi,
    request_with_ssl_fallback,
    say,
    write_raster,
    write_shapefile_zip,
)

WCS_URL = "https://www.mrlc.gov/geoserver/wcs"
NLCD_ATTRIBUTION = (
    "National Land Cover Database, U.S. Geological Survey / MRLC Consortium"
)
NLCD_DATASET_URL = "https://www.mrlc.gov/"

NLCD_NODATA = 0
# The NLCD EPSG:5070 grid has cell edges at odd multiples of 15 m; anchoring
# requests to that grid keeps downloaded cells identical to the source cells.
NLCD_GRID_ANCHOR = (15.0, 15.0)

# Annual NLCD Collection 1 time-enabled coverage (USGS EROS GeoServer).
# WCS 2.0.1 GetCoverage is broken on this mosaic server-side, so tiles are
# requested through WCS 1.0.0 with the TIME parameter, which works.
ANNUAL_WCS_URL = (
    "https://dmsdata.cr.usgs.gov/geoserver/"
    "mrlc_Land-Cover-Native_conus_year_data/wcs"
)
ANNUAL_COVERAGE = (
    "mrlc_Land-Cover-Native_conus_year_data:Land-Cover-Native_conus_year_data"
)
# Annual NLCD uses 250 as its background value; it is remapped to the
# app-wide NLCD NoData (0) as tiles arrive so both products behave the same.
ANNUAL_SOURCE_NODATA = 250

# Tiles of at most this many cells per side are requested from the WCS
TILE_CELLS = 2048
MAX_WORKERS = 4

# Years always offered when the live capabilities checks are unavailable
FALLBACK_YEARS = [2021, 2019, 2016, 2013, 2011, 2008, 2006, 2004, 2001]
ANNUAL_FALLBACK_YEARS = list(range(2025, 1984, -1))

# Official NLCD legend: class code -> name (CONUS classes)
NLCD_CLASSES = {
    11: "Open Water",
    12: "Perennial Ice/Snow",
    21: "Developed, Open Space",
    22: "Developed, Low Intensity",
    23: "Developed, Medium Intensity",
    24: "Developed, High Intensity",
    31: "Barren Land (Rock/Sand/Clay)",
    41: "Deciduous Forest",
    42: "Evergreen Forest",
    43: "Mixed Forest",
    52: "Shrub/Scrub",
    71: "Grassland/Herbaceous",
    81: "Pasture/Hay",
    82: "Cultivated Crops",
    90: "Woody Wetlands",
    95: "Emergent Herbaceous Wetlands",
}

# Official NLCD display colors, class code -> hex
NLCD_COLORS = {
    11: "#466b9f",
    12: "#d1def8",
    21: "#dec5c5",
    22: "#d99282",
    23: "#eb0000",
    24: "#ab0000",
    31: "#b3ac9f",
    41: "#68ab5f",
    42: "#1c5f2c",
    43: "#b5c58f",
    52: "#ccb879",
    71: "#dfdfc2",
    81: "#dcd939",
    82: "#ab6c28",
    90: "#b8d9eb",
    95: "#6c9fb8",
}

_epoch_years_cache = None
_annual_years_cache = None


def coverage_id(year):
    """WCS coverage ID for one NLCD land cover epoch (conterminous US)."""
    return f"mrlc_download__NLCD_{year}_Land_Cover_L48"


def product_label(year, source):
    """Human-readable product name for one year, shown in the UI and logs."""
    if source == "annual":
        return f"Annual NLCD {year}"
    return f"NLCD {year} release"


def official_colormap():
    """Official NLCD colors as a rasterio colormap, NoData transparent."""
    colormap = {NLCD_NODATA: (0, 0, 0, 0)}
    for code, hex_color in NLCD_COLORS.items():
        color = hex_color.lstrip("#")
        colormap[code] = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    return colormap


def _epoch_years(message_callback=None, refresh=False):
    """Epoch NLCD years offered by the MRLC WCS, cached per session."""
    global _epoch_years_cache
    if _epoch_years_cache is not None and not refresh:
        return _epoch_years_cache
    try:
        response = request_with_ssl_fallback(
            "GET",
            WCS_URL,
            message_callback=message_callback,
            params={
                "service": "WCS",
                "version": "2.0.1",
                "request": "GetCapabilities",
            },
            timeout=20,
        )
        response.raise_for_status()
        years = {
            int(match)
            for match in re.findall(
                r"mrlc_download__NLCD_(\d{4})_Land_Cover_L48", response.text
            )
        }
        if years:
            _epoch_years_cache = sorted(years, reverse=True)
            return _epoch_years_cache
    except Exception as exc:  # capabilities check is best effort only
        say(
            "NLCD: could not read the live epoch year list from MRLC "
            f"({exc}); using the built-in list.",
            message_callback,
        )
    return list(FALLBACK_YEARS)


def _annual_years(message_callback=None, refresh=False):
    """Annual NLCD years offered by the USGS time mosaic, cached per session."""
    global _annual_years_cache
    if _annual_years_cache is not None and not refresh:
        return _annual_years_cache
    try:
        response = request_with_ssl_fallback(
            "GET",
            ANNUAL_WCS_URL,
            message_callback=message_callback,
            params={
                "service": "WCS",
                "version": "2.0.1",
                "request": "DescribeCoverage",
                "coverageId": ANNUAL_COVERAGE.replace(":", "__"),
            },
            timeout=20,
        )
        response.raise_for_status()
        years = {
            int(match)
            for match in re.findall(
                r"<gml:timePosition>(\d{4})", response.text
            )
        }
        if years:
            _annual_years_cache = sorted(years, reverse=True)
            return _annual_years_cache
    except Exception as exc:  # capabilities check is best effort only
        say(
            "NLCD: could not read the live Annual NLCD year list from USGS "
            f"({exc}); using the built-in list.",
            message_callback,
        )
    return list(ANNUAL_FALLBACK_YEARS)


def available_nlcd_years(message_callback=None, refresh=False):
    """
    List all NLCD land cover years, newest first, as (year, source) pairs.

    Years available as an epoch NLCD release (2001-2021) use the ``epoch``
    source; every other year comes from Annual NLCD (``annual``). The live
    services are checked once per app session so newly published years show
    up automatically; built-in lists cover the offline case.
    """
    epoch = set(_epoch_years(message_callback, refresh))
    annual = set(_annual_years(message_callback, refresh))
    return [
        (year, "epoch" if year in epoch else "annual")
        for year in sorted(epoch | annual, reverse=True)
    ]


def year_choices(message_callback=None, refresh=False):
    """Dropdown entries as (label, value) pairs, newest year first."""
    return [
        (product_label(year, source), str(year))
        for year, source in available_nlcd_years(message_callback, refresh)
    ]


def fallback_year_choices():
    """Dropdown entries from the built-in year lists, no network needed."""
    epoch = set(FALLBACK_YEARS)
    years = sorted(epoch | set(ANNUAL_FALLBACK_YEARS), reverse=True)
    return [
        (product_label(year, "epoch" if year in epoch else "annual"), str(year))
        for year in years
    ]


def _fetch_tile(year, bounds, source, message_callback=None):
    """Download one WCS tile and return (array, transform)."""
    minx, miny, maxx, maxy = bounds
    if source == "annual":
        url = ANNUAL_WCS_URL
        width = int(round((maxx - minx) / PREP_CELL_SIZE))
        height = int(round((maxy - miny) / PREP_CELL_SIZE))
        params = {
            "service": "WCS",
            "version": "1.0.0",
            "request": "GetCoverage",
            "coverage": ANNUAL_COVERAGE,
            "bbox": f"{minx},{miny},{maxx},{maxy}",
            "crs": "EPSG:5070",
            "format": "GeoTIFF",
            "width": str(width),
            "height": str(height),
            "TIME": f"{year}-01-01",
        }
    else:
        url = WCS_URL
        params = {
            "service": "WCS",
            "version": "2.0.1",
            "request": "GetCoverage",
            "coverageId": coverage_id(year),
            "subset": [f"X({minx},{maxx})", f"Y({miny},{maxy})"],
            "format": "image/geotiff",
        }
    last_error = None
    for _attempt in range(3):
        try:
            response = request_with_ssl_fallback(
                "GET", url, message_callback=message_callback,
                params=params, timeout=180,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "tif" not in content_type and "image" not in content_type:
                raise RuntimeError(
                    "The land cover service returned an unexpected response "
                    f"({content_type}): {response.text[:300]}"
                )
            with MemoryFile(response.content) as memfile:
                with memfile.open() as src:
                    if src.crs is not None and src.crs.to_epsg() != 5070:
                        raise RuntimeError(
                            f"Unexpected tile CRS {src.crs}, expected EPSG:5070"
                        )
                    data = src.read(1)
                    if source == "annual":
                        # Annual NLCD background value -> app-wide NoData
                        data[data == ANNUAL_SOURCE_NODATA] = NLCD_NODATA
                    return data, src.transform
        except Exception as exc:
            last_error = exc
    raise RuntimeError(
        f"Could not download a {product_label(year, source)} tile after 3 "
        f"attempts. Details: {last_error}"
    )


def fetch_nlcd_data(
    watershed_gdf,
    year,
    output_dir,
    progress_callback=None,
    message_callback=None,
):
    """
    Download NLCD land cover for a watershed and write the outputs.

    Parameters
    ----------
    watershed_gdf : GeoDataFrame
        Watershed or subbasin boundary polygons (any CRS with metadata).
    year : int
        NLCD land cover year (see :func:`available_nlcd_years`).
    output_dir : Path or str
        Folder that receives the outputs.
    progress_callback : callable, optional
        Called as progress_callback(fraction, description) with fraction in
        [0, 1] covering this land cover download only.
    message_callback : callable, optional
        Receives plain-text log messages.

    Returns
    -------
    dict with keys: zip_path, raster_path, summary (DataFrame with area by
    class), year, cell_count, polygon_count.
    """
    year = int(year)

    def _progress(fraction, description):
        if progress_callback is not None:
            progress_callback(fraction, description)

    aoi = prepare_aoi(watershed_gdf)
    transform, width, height, aligned_bounds = aligned_grid(
        aoi["bounds_5070"], anchor=NLCD_GRID_ANCHOR
    )
    if width * height > MAX_RASTER_CELLS:
        raise RuntimeError(
            f"The watershed needs a {width:,} x {height:,} cell NLCD grid, "
            "which is beyond the app's limit. Please prepare data for a "
            "smaller watershed, or download NLCD directly from mrlc.gov."
        )

    # Split the request into aligned tiles
    tiles = []
    minx, miny, maxx, maxy = aligned_bounds
    for row_off in range(0, height, TILE_CELLS):
        for col_off in range(0, width, TILE_CELLS):
            tile_h = min(TILE_CELLS, height - row_off)
            tile_w = min(TILE_CELLS, width - col_off)
            tile_minx = minx + col_off * PREP_CELL_SIZE
            tile_maxx = tile_minx + tile_w * PREP_CELL_SIZE
            tile_maxy = maxy - row_off * PREP_CELL_SIZE
            tile_miny = tile_maxy - tile_h * PREP_CELL_SIZE
            tiles.append((row_off, col_off, (tile_minx, tile_miny, tile_maxx, tile_maxy)))

    # Pick the product for this year: epoch releases for 2001-2021, Annual
    # NLCD otherwise. When both services offer the year, the other one is
    # kept as a fallback in case the primary cannot be reached.
    epoch_set = set(_epoch_years(message_callback))
    annual_set = set(_annual_years(message_callback))
    if year in epoch_set:
        sources = ["epoch"] + (["annual"] if year in annual_set else [])
    elif year in annual_set:
        sources = ["annual"]
    else:
        raise RuntimeError(
            f"NLCD land cover is not available for the year {year}. "
            "Pick one of the years offered in the dropdown."
        )

    total = len(tiles)

    def _download_all(source):
        """Download every tile from one service and return the mosaic."""
        label = product_label(year, source)
        say(
            f"{label}: downloading {width:,} x {height:,} cells in "
            f"{total} tile(s)",
            message_callback,
        )
        _progress(0.02, f"{label}: requesting land cover tiles")
        grid = np.full((height, width), NLCD_NODATA, dtype=np.uint8)
        done = 0

        def _one(tile):
            row_off, col_off, bounds = tile
            data, tile_transform = _fetch_tile(year, bounds, source, message_callback)
            return data, tile_transform

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for data, tile_transform in pool.map(_one, tiles):
                # Place the tile by its own georeferencing so a one-cell
                # shift in the service response cannot misalign the mosaic.
                col_start = int(round((tile_transform.c - transform.c) / PREP_CELL_SIZE))
                row_start = int(round((transform.f - tile_transform.f) / PREP_CELL_SIZE))
                rows = slice(max(row_start, 0), min(row_start + data.shape[0], height))
                cols = slice(max(col_start, 0), min(col_start + data.shape[1], width))
                src_rows = slice(rows.start - row_start, rows.stop - row_start)
                src_cols = slice(cols.start - col_start, cols.stop - col_start)
                grid[rows, cols] = data[src_rows, src_cols]
                done += 1
                _progress(
                    0.02 + 0.63 * (done / total),
                    f"{label}: downloading tiles ({done} of {total})",
                )
        return grid

    mosaic = None
    source_used = None
    for index, source in enumerate(sources):
        try:
            mosaic = _download_all(source)
            source_used = source
            break
        except RuntimeError as exc:
            if index + 1 < len(sources):
                say(
                    f"{product_label(year, source)} could not be downloaded "
                    f"({exc}). Trying {product_label(year, sources[index + 1])} "
                    "instead.",
                    message_callback,
                )
                continue
            raise
    label = product_label(year, source_used)

    # Clip to the buffered watershed with the cell-center rule
    _progress(0.68, f"{label}: clipping to the watershed")
    mosaic = clip_array_to_aoi(mosaic, transform, aoi["aoi_5070"], NLCD_NODATA)
    valid = mosaic[mosaic != NLCD_NODATA]
    if valid.size == 0:
        raise RuntimeError(
            f"{label} has no land cover cells inside this watershed. "
            "The MRLC L48 products cover the conterminous United States; "
            "check that the boundary is inside that area."
        )

    # Class area summary (30 m cells in an equal-area CRS: areas are exact)
    import pandas as pd

    codes, counts = np.unique(valid, return_counts=True)
    cell_acres = (PREP_CELL_SIZE * PREP_CELL_SIZE) / 4046.86
    summary = pd.DataFrame({
        "gridcode": codes.astype(int),
        "landuse": [NLCD_CLASSES.get(int(c), f"Unknown ({int(c)})") for c in codes],
        "area_acres": counts * cell_acres,
    })
    summary["percent_area"] = 100 * summary["area_acres"] / summary["area_acres"].sum()
    summary = summary.sort_values("area_acres", ascending=False).reset_index(drop=True)

    # Write the clipped GeoTIFF with the official color table
    _progress(0.75, f"{label}: writing the land cover raster")
    raster_path = write_raster(
        str(output_dir) + f"/nlcd_{year}_landcover.tif",
        mosaic,
        transform,
        nodata=NLCD_NODATA,
        colormap=official_colormap(),
    )
    say(f"{label}: raster saved: {raster_path}", message_callback)

    # Convert to polygons for the CN workflow
    _progress(0.82, f"{label}: converting land cover to polygons")
    landuse_gdf = polygonize_classified_raster(
        mosaic, transform, NLCD_NODATA, crs=PREP_CRS, value_field="gridcode"
    )
    landuse_gdf["landuse"] = landuse_gdf["gridcode"].map(
        lambda code: NLCD_CLASSES.get(int(code), f"Unknown ({int(code)})")
    )
    say(
        f"{label}: {len(landuse_gdf):,} land use polygons created",
        message_callback,
    )

    _progress(0.92, f"{label}: writing the land use shapefile")
    zip_path = write_shapefile_zip(
        landuse_gdf, output_dir, f"nlcd_{year}_landuse_polygons"
    )
    say(f"{label}: shapefile saved: {zip_path}", message_callback)
    _progress(1.0, f"{label}: done")

    return {
        "zip_path": zip_path,
        "raster_path": raster_path,
        "summary": summary,
        "year": year,
        "source": source_used,
        "product": label,
        "cell_count": int(valid.size),
        "polygon_count": len(landuse_gdf),
    }
