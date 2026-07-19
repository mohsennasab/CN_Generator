"""
Area-weighted (coverage fraction) zonal statistics.

The default zonal method used by most GIS tools keeps a raster cell for a zone
only when the cell center falls inside the zone polygon. That rule drops cells
along the border, and a zone thinner than one cell can capture nothing at all.

This module weights each cell by the fraction of its area that falls inside the
zone polygon instead. A cell fully inside gets a weight of 1.0, a cell that the
boundary cuts in half gets 0.5, and a cell outside gets 0.0. Border cells are
therefore always included, but only in proportion to how much of the cell the
zone actually covers. A cell that two neighboring subbasins share is split
between them by area, so nothing is double counted.

The coverage fractions are exact. Cells fully inside the polygon get 1.0
directly, and only the cells the polygon boundary passes through are clipped
against the polygon with Shapely to measure the covered area. This keeps the
work proportional to the length of the border rather than the whole zone.

Only rasterio, shapely, and numpy are used, so no extra dependency is needed.
"""

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.windows import from_bounds, Window
from shapely.geometry import box

_STAT_KEYS = ["min", "max", "mean", "median", "std", "count"]


def cell_coverage_fractions(geometry, transform, height, width):
    """
    Return an array of per-cell coverage fractions for one geometry.

    Parameters
    ----------
    geometry : shapely geometry
        Zone polygon (or multipolygon) in the raster CRS.
    transform : affine.Affine
        Transform of the array grid the fractions are computed on.
    height, width : int
        Shape of the array grid.

    Returns
    -------
    numpy.ndarray of float64, shape (height, width)
        Fraction of each cell covered by the geometry, from 0.0 to 1.0.
    """
    if height <= 0 or width <= 0:
        return np.zeros((max(height, 0), max(width, 0)), dtype="float64")

    # Cells the polygon overlaps at all (any touch).
    touched = rasterize(
        [(geometry, 1)],
        out_shape=(height, width),
        transform=transform,
        all_touched=True,
        fill=0,
        dtype="uint8",
    ).astype(bool)

    frac = np.zeros((height, width), dtype="float64")
    if not touched.any():
        return frac

    # Cells the polygon boundary passes through are the only partial cells.
    # A touched cell the boundary does not cross is fully inside the polygon.
    boundary_cells = rasterize(
        [(geometry.boundary, 1)],
        out_shape=(height, width),
        transform=transform,
        all_touched=True,
        fill=0,
        dtype="uint8",
    ).astype(bool)

    full = touched & ~boundary_cells
    frac[full] = 1.0

    partial = touched & boundary_cells
    cell_area = abs(transform.a) * abs(transform.e)
    if cell_area <= 0:
        return frac

    rows, cols = np.nonzero(partial)
    for r, c in zip(rows.tolist(), cols.tolist()):
        # Cell corner coordinates from the affine transform.
        x0, y0 = transform * (c, r)
        x1, y1 = transform * (c + 1, r + 1)
        cell = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        inter = cell.intersection(geometry)
        if not inter.is_empty:
            frac[r, c] = min(1.0, inter.area / cell_area)
    return frac


def _weighted_median(values, weights):
    """Weighted median: the value where cumulative weight reaches half."""
    order = np.argsort(values, kind="mergesort")
    v = values[order]
    w = weights[order]
    cumulative = np.cumsum(w)
    half = 0.5 * cumulative[-1]
    idx = int(np.searchsorted(cumulative, half))
    idx = min(idx, len(v) - 1)
    return float(v[idx])


def weighted_stats_from_arrays(values, fractions, nodata):
    """
    Compute area-weighted statistics from a value array and a fraction array.

    Parameters
    ----------
    values : numpy.ndarray
        Raster values for the window.
    fractions : numpy.ndarray
        Per-cell coverage fractions, same shape as values.
    nodata : float or None
        NoData value to exclude, or None to keep every finite cell.

    Returns
    -------
    dict with keys min, max, mean, median, std, count.
        count is the effective covered cell area in whole-cell units
        (the sum of the fractions of the included cells). Values are NaN
        and count is 0.0 when no covered cells hold data.
    """
    values = values.astype("float64")
    valid = np.isfinite(values)
    if nodata is not None:
        valid &= values != nodata

    # A cell contributes only when it holds data and the zone covers part of it.
    member = valid & (fractions > 0)
    if not member.any():
        result = {key: float("nan") for key in _STAT_KEYS}
        result["count"] = 0.0
        return result

    v = values[member]
    w = fractions[member]
    total = float(w.sum())
    mean = float(np.average(v, weights=w))
    variance = float(np.average((v - mean) ** 2, weights=w))
    return {
        # Min and max are taken over the membership set, so border cells that
        # coverage weighting includes also count toward the range.
        "min": float(v.min()),
        "max": float(v.max()),
        "mean": mean,
        "median": _weighted_median(v, w),
        "std": float(np.sqrt(variance)),
        "count": total,
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


def coverage_weighted_zonal_stats(raster_path, geometries, nodata):
    """
    Area-weighted zonal statistics for a list of geometries over a raster.

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
                empty = {key: float("nan") for key in _STAT_KEYS}
                empty["count"] = 0.0
                results.append(empty)
                continue
            data, transform = _read_window_for_geometry(src, geometry)
            if data is None:
                empty = {key: float("nan") for key in _STAT_KEYS}
                empty["count"] = 0.0
                results.append(empty)
                continue
            fractions = cell_coverage_fractions(
                geometry, transform, data.shape[0], data.shape[1]
            )
            results.append(weighted_stats_from_arrays(data, fractions, nodata))
    return results
