"""
Exact-clip zonal statistics.

A raster cell belongs to a zone when the cell center falls inside the zone
polygon. This is the same rule a standard GIS raster clip (Extract by Mask)
uses, so the statistics for each zone are computed over exactly the cells
that an exact clip of the raster to that zone would keep. Every kept cell
counts once with equal weight, and cells whose center falls outside the
boundary are never included.

A zone that is thinner than one raster cell can capture no cell centers at
all. In that case the zone's statistics are reported as empty (NaN with a
count of zero) rather than guessed from nearby cells.

Only rasterio and numpy are used, so no extra dependency is needed.
"""

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds, Window

_STAT_KEYS = ["min", "max", "mean", "median", "std", "count"]


def _empty_stats():
    result = {key: float("nan") for key in _STAT_KEYS}
    result["count"] = 0
    return result


def stats_from_values(values):
    """
    Compute summary statistics from a 1-D array of raster values.

    Returns a dict with min, max, mean, median, std, count. Values are NaN
    and count is 0 when the array is empty.
    """
    if values.size == 0:
        return _empty_stats()
    v = values.astype("float64")
    return {
        "min": float(v.min()),
        "max": float(v.max()),
        "mean": float(v.mean()),
        "median": float(np.median(v)),
        "std": float(v.std()),
        "count": int(v.size),
    }


def _read_window_for_geometry(src, geometry, pad=1):
    """Read the smallest raster window that covers a geometry, with padding."""
    minx, miny, maxx, maxy = geometry.bounds
    window = from_bounds(minx, miny, maxx, maxy, src.transform)
    window = window.round_offsets(op="floor").round_lengths(op="ceil")

    # Pad by a cell so a boundary sitting on a cell edge is not clipped away.
    col_off = int(window.col_off) - pad
    row_off = int(window.row_off) - pad
    win_width = int(window.width) + 2 * pad
    win_height = int(window.height) + 2 * pad

    # Clip the window to the raster extent.
    col_off_clipped = max(col_off, 0)
    row_off_clipped = max(row_off, 0)
    col_end = min(col_off + win_width, src.width)
    row_end = min(row_off + win_height, src.height)
    win_width = col_end - col_off_clipped
    win_height = row_end - row_off_clipped
    if win_width <= 0 or win_height <= 0:
        return None, None

    window = Window(col_off_clipped, row_off_clipped, win_width, win_height)
    data = src.read(1, window=window)
    transform = src.window_transform(window)
    return data, transform


def exact_zonal_stats(raster_path, geometries, nodata):
    """
    Exact-clip zonal statistics for a list of geometries over a raster.

    A cell is assigned to a zone when its center falls inside the zone
    polygon, exactly matching a raster clipped to that polygon. Cells
    holding the NoData value are excluded.

    Parameters
    ----------
    raster_path : str
        Path to the raster to summarize.
    geometries : iterable of shapely geometries
        Zone polygons in the same CRS as the raster.
    nodata : float or None
        NoData value to exclude from the statistics.

    Returns
    -------
    list of dict
        One statistics dict per geometry, in the same order as the input.
    """
    results = []
    with rasterio.open(raster_path) as src:
        for geometry in geometries:
            if geometry is None or geometry.is_empty:
                results.append(_empty_stats())
                continue
            data, transform = _read_window_for_geometry(src, geometry)
            if data is None:
                results.append(_empty_stats())
                continue
            # True where the cell center falls inside the zone polygon.
            inside = geometry_mask(
                [geometry],
                out_shape=data.shape,
                transform=transform,
                invert=True,
                all_touched=False,
            )
            values = data.astype("float64")
            member = inside & np.isfinite(values)
            if nodata is not None:
                member &= values != nodata
            results.append(stats_from_values(values[member]))
    return results
