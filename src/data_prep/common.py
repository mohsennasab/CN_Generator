"""
Data Preparation - Shared Helpers
Common utilities for the optional Data Preparation workflow: HTTP requests
with a corporate-VPN certificate fallback, area-of-interest handling, and
shapefile packaging.

All data preparation happens in EPSG:5070 (NAD83 Conus Albers), the native
projection of NLCD land cover. It is meter based and equal area, and it is
also the projection the app's Automatic CRS option picks for US data, so the
prepared layers flow into the CN workflow without any reprojection.
"""

import os
import warnings
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio import features
from rasterio.transform import from_origin

import requests

# Native NLCD projection and cell size; everything the tab produces uses them.
PREP_CRS = "EPSG:5070"
PREP_CELL_SIZE = 30.0  # meters, native NLCD resolution

# Exported layers keep a small buffer past the watershed boundary so the CN
# workflow's soil and land use intersection fully covers every boundary cell.
# The final CN raster is still clipped exactly to the boundary in tab 5.
BOUNDARY_BUFFER_M = 90.0  # three 30 m cells

# Guard rails for very large watersheds so the app degrades with a clear
# message instead of exhausting memory or hammering the public services.
MAX_RASTER_CELLS = 400_000_000  # uint8 grid cap (~570 km x 570 km at 30 m)
MAX_SOIL_POLYGONS = 60_000      # SSURGO polygons; beyond this SDA fetch is impractical

_SSL_WARNING = (
    "The server certificate could not be verified. This usually happens on "
    "corporate VPNs or networks that inspect secure traffic. Retrying with "
    "certificate verification turned off. This only affects the download; "
    "the data content is not changed."
)


def request_with_ssl_fallback(method, url, message_callback=None, **kwargs):
    """
    Perform an HTTP request, retrying once without certificate verification.

    Corporate VPNs and firewalls that inspect HTTPS traffic re-sign it with
    their own root certificate, which the requests library rejects. The same
    fallback the GCN10 reader uses is applied here: verify normally first,
    and on an SSL error retry once with verification turned off.
    """
    kwargs.setdefault("timeout", 120)
    try:
        return requests.request(method, url, **kwargs)
    except requests.exceptions.SSLError:
        if message_callback is not None:
            message_callback(_SSL_WARNING)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return requests.request(method, url, verify=False, **kwargs)


def say(message, message_callback=None):
    """Send a status message to the run log when available, else stdout."""
    if message_callback is not None:
        message_callback(message)
    else:
        print(message)


def prepare_aoi(watershed_gdf):
    """
    Build the area-of-interest geometries used by both data downloads.

    Returns a dict with:
    - ``aoi_5070``: buffered watershed outline as one (multi)polygon in
      EPSG:5070, used for clipping rasters and vectors.
    - ``aoi_4326``: the same buffered outline in EPSG:4326, used for the
      Soil Data Access spatial query.
    - ``bounds_5070``: (minx, miny, maxx, maxy) of the buffered outline.
    """
    if watershed_gdf is None or len(watershed_gdf) == 0:
        raise RuntimeError("Data preparation needs a watershed boundary layer.")
    if watershed_gdf.crs is None:
        raise RuntimeError(
            "The watershed boundary layer has no coordinate system "
            "information. Please provide a layer with a defined CRS (for "
            "shapefiles, include the .prj file)."
        )

    projected = watershed_gdf.to_crs(PREP_CRS)
    aoi_5070 = projected.union_all().buffer(BOUNDARY_BUFFER_M)
    aoi_4326 = (
        gpd.GeoSeries([aoi_5070], crs=PREP_CRS).to_crs("EPSG:4326").iloc[0]
    )
    return {
        "aoi_5070": aoi_5070,
        "aoi_4326": aoi_4326,
        "bounds_5070": aoi_5070.bounds,
    }


def simplify_for_query(geometry, max_wkt_chars=150_000):
    """
    Simplify a geometry until its WKT fits in a remote SQL query.

    The precise clip always happens locally afterwards, so simplification
    here only means slightly more candidate polygons are fetched, never that
    output data is lost.
    """
    wkt = geometry.wkt
    tolerance = 0.0001  # about 10 m in degrees
    simplified = geometry
    while len(wkt) > max_wkt_chars:
        simplified = geometry.simplify(tolerance, preserve_topology=True)
        wkt = simplified.wkt
        tolerance *= 2
        if tolerance > 0.5:
            # Fall back to the convex hull as the coarsest usable outline
            simplified = geometry.convex_hull
            wkt = simplified.wkt
            break
    return simplified


def aligned_grid(bounds, cell_size=PREP_CELL_SIZE, anchor=(0.0, 0.0)):
    """
    Snap bounds outward to a cell-size-aligned grid.

    Returns (transform, width, height, aligned_bounds). Aligning every
    request to one shared grid keeps downloaded tiles, rasterized soil, and
    the CN workflow's rasters consistent with each other.
    """
    minx, miny, maxx, maxy = bounds
    ax, ay = anchor
    minx = ax + np.floor((minx - ax) / cell_size) * cell_size
    miny = ay + np.floor((miny - ay) / cell_size) * cell_size
    maxx = ax + np.ceil((maxx - ax) / cell_size) * cell_size
    maxy = ay + np.ceil((maxy - ay) / cell_size) * cell_size
    width = int(round((maxx - minx) / cell_size))
    height = int(round((maxy - miny) / cell_size))
    transform = from_origin(minx, maxy, cell_size, cell_size)
    return transform, width, height, (minx, miny, maxx, maxy)


def clip_array_to_aoi(array, transform, aoi_geometry, nodata):
    """
    Set cells outside the area of interest to NoData (cell-center rule).

    The same rule the rest of the app uses for raster clipping: a cell keeps
    its value only when its center falls inside the boundary.
    """
    outside = features.geometry_mask(
        [aoi_geometry],
        out_shape=array.shape,
        transform=transform,
        invert=False,
        all_touched=False,
    )
    array[outside] = nodata
    return array


def write_raster(path, array, transform, crs=PREP_CRS, nodata=0, colormap=None):
    """Write a single-band uint8 GeoTIFF with LZW compression."""
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=rasterio.uint8,
        crs=crs,
        transform=transform,
        nodata=nodata,
        compress="lzw",
    ) as dst:
        dst.write(array, 1)
        if colormap is not None:
            dst.write_colormap(1, colormap)
    return str(path)


def polygonize_classified_raster(array, transform, nodata, crs=PREP_CRS,
                                 value_field="gridcode"):
    """
    Convert a classified (categorical) raster to polygons.

    Neighboring cells with the same class merge into one polygon, which is
    the standard raster-to-polygon conversion GIS tools perform.
    """
    from shapely.geometry import shape

    mask = array != nodata
    records = []
    geometries = []
    for geom, value in features.shapes(array, mask=mask, transform=transform):
        records.append(int(value))
        geometries.append(shape(geom))
    return gpd.GeoDataFrame(
        {value_field: records}, geometry=geometries, crs=crs
    )


def write_shapefile_zip(gdf, folder, layer_name):
    """
    Write a GeoDataFrame as a zipped shapefile ready to import in the CN
    workflow (contains .shp, .shx, .dbf, and .prj).

    Returns the path of the created zip file.
    """
    folder = Path(folder)
    shp_dir = folder / layer_name
    shp_dir.mkdir(parents=True, exist_ok=True)
    shp_path = shp_dir / f"{layer_name}.shp"
    gdf.to_file(str(shp_path), driver="ESRI Shapefile")

    zip_path = folder / f"{layer_name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for component in shp_dir.iterdir():
            zf.write(component, arcname=component.name)
    return str(zip_path)
