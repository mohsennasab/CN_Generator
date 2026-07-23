"""
Data Preparation - Soil Data (USDA SSURGO via Soil Data Access)
Download SSURGO soil map unit polygons with hydrologic soil groups for a
watershed, ready to import into the CN workflow.

Data source: USDA-NRCS Soil Data Access (SDA), the official live query
service for the SSURGO database. Polygons come from the ``mupolygon`` table
and the dominant-condition hydrologic soil group (``hydgrpdcd``, values A,
B, C, D, A/D, B/D, C/D) from the ``muaggatt`` table, joined on the map unit
key. This is the same data the familiar "SSURGO Soil Data Downloader" tools
deliver, fetched only for the watershed area.

Large watersheds are handled by fetching polygon geometries in small chunks
over several requests instead of one giant response, with progress reported
per chunk. The number of polygons is capped so the public service is not
overwhelmed and the app stays responsive.

Citation: Soil Survey Staff. Soil Survey Geographic (SSURGO) Database.
USDA Natural Resources Conservation Service. https://sdmdataaccess.sc.egov.usda.gov
"""

from concurrent.futures import ThreadPoolExecutor

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt as shapely_wkt

from .common import (
    MAX_SOIL_POLYGONS,
    PREP_CELL_SIZE,
    PREP_CRS,
    aligned_grid,
    clip_array_to_aoi,
    prepare_aoi,
    request_with_ssl_fallback,
    say,
    simplify_for_query,
    write_raster,
    write_shapefile_zip,
)

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
SDA_ATTRIBUTION = "USDA-NRCS Soil Survey Geographic (SSURGO) Database"
SDA_DATASET_URL = "https://sdmdataaccess.nrcs.usda.gov/"

# Chunk sizes keep each SDA response comfortably small
GEOMETRY_CHUNK = 200
TABLE_CHUNK = 1000
MAX_WORKERS = 4

SOIL_NODATA = 0
# Hydrologic soil group -> raster code, in CN-method order
HSG_CODES = {"A": 1, "B": 2, "C": 3, "D": 4, "A/D": 5, "B/D": 6, "C/D": 7}
HSG_LABELS = {code: group for group, code in HSG_CODES.items()}
# Display colors: single groups run green (high infiltration) to red (low),
# dual drained/undrained groups use distinct blue-purple tones.
HSG_COLORS = {
    "A": "#33a02c",
    "B": "#b2df8a",
    "C": "#fdbf6f",
    "D": "#e31a1c",
    "A/D": "#a6cee3",
    "B/D": "#1f78b4",
    "C/D": "#6a3d9a",
}


def _run_sda_query(query, message_callback=None):
    """POST one SQL query to Soil Data Access and return the result rows."""
    response = request_with_ssl_fallback(
        "POST",
        SDA_URL,
        message_callback=message_callback,
        json={"query": query, "format": "JSON+COLUMNNAME"},
        timeout=180,
    )
    response.raise_for_status()
    table = response.json().get("Table", [])
    if not table:
        return [], []
    return table[0], table[1:]


def _chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def fetch_soil_data(
    watershed_gdf,
    output_dir,
    progress_callback=None,
    message_callback=None,
):
    """
    Download SSURGO soil polygons with hydrologic soil groups for a watershed.

    Parameters
    ----------
    watershed_gdf : GeoDataFrame
        Watershed or subbasin boundary polygons (any CRS with metadata).
    output_dir : Path or str
        Folder that receives the outputs.
    progress_callback : callable, optional
        Called as progress_callback(fraction, description) with fraction in
        [0, 1] covering this soil download only.
    message_callback : callable, optional
        Receives plain-text log messages.

    Returns
    -------
    dict with keys: zip_path, raster_path, gdf, summary (DataFrame with area
    by hydrologic group), polygon_count, missing_hsg_count.
    """
    def _progress(fraction, description):
        if progress_callback is not None:
            progress_callback(fraction, description)

    aoi = prepare_aoi(watershed_gdf)
    say("Soil: querying Soil Data Access for SSURGO map units", message_callback)
    _progress(0.02, "Soil: finding SSURGO polygons for the watershed")

    query_geom = simplify_for_query(aoi["aoi_4326"])
    key_query = (
        "SELECT mupolygonkey, mukey FROM mupolygon WHERE "
        "mupolygongeo.STIntersects(geometry::STGeomFromText("
        f"'{query_geom.wkt}', 4326)) = 1"
    )
    _, key_rows = _run_sda_query(key_query, message_callback)
    if not key_rows:
        raise RuntimeError(
            "Soil Data Access returned no SSURGO soil polygons for this "
            "watershed. SSURGO covers the United States and territories; "
            "check that the boundary is inside SSURGO coverage."
        )

    polygon_keys = [row[0] for row in key_rows]
    mukeys = sorted({row[1] for row in key_rows})
    say(
        f"Soil: {len(polygon_keys)} SSURGO polygons across "
        f"{len(mukeys)} map units intersect the watershed",
        message_callback,
    )
    if len(polygon_keys) > MAX_SOIL_POLYGONS:
        raise RuntimeError(
            f"The watershed intersects {len(polygon_keys):,} SSURGO soil "
            f"polygons, which is beyond the app's limit of "
            f"{MAX_SOIL_POLYGONS:,}. Please prepare data for a smaller "
            "watershed, or download soil data with the NRCS tools directly."
        )

    # Fetch the hydrologic group table for the map units (small, chunked)
    _progress(0.08, "Soil: reading hydrologic soil groups")
    attribute_rows = []
    for chunk in _chunks(mukeys, TABLE_CHUNK):
        keys = ",".join(f"'{key}'" for key in chunk)
        table_query = (
            "SELECT mukey, musym, muname, hydgrpdcd FROM muaggatt "
            f"WHERE mukey IN ({keys})"
        )
        _, rows = _run_sda_query(table_query, message_callback)
        attribute_rows.extend(rows)
    attributes = pd.DataFrame(
        attribute_rows, columns=["mukey", "musym", "muname", "hydgrpdcd"]
    )

    # Fetch polygon geometries in chunks, a few requests at a time
    chunks = list(_chunks(polygon_keys, GEOMETRY_CHUNK))
    total_chunks = len(chunks)
    say(
        f"Soil: downloading polygon geometries in {total_chunks} chunks",
        message_callback,
    )

    def _fetch_chunk(chunk):
        keys = ",".join(chunk)
        geometry_query = (
            "SELECT mupolygonkey, mukey, mupolygongeo.STAsText() AS geom "
            f"FROM mupolygon WHERE mupolygonkey IN ({keys})"
        )
        _, rows = _run_sda_query(geometry_query, message_callback)
        return rows

    geometry_rows = []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for rows in pool.map(_fetch_chunk, chunks):
            geometry_rows.extend(rows)
            done += 1
            _progress(
                0.10 + 0.60 * (done / total_chunks),
                f"Soil: downloading polygons (chunk {done} of {total_chunks})",
            )

    _progress(0.72, "Soil: building the soil layer")
    records = pd.DataFrame(
        geometry_rows, columns=["mupolygonkey", "mukey", "geom"]
    )
    geometries = [shapely_wkt.loads(text) for text in records["geom"]]
    soil_gdf = gpd.GeoDataFrame(
        records[["mukey"]].copy(), geometry=geometries, crs="EPSG:4326"
    )
    soil_gdf = soil_gdf.merge(attributes, on="mukey", how="left")

    # Project to the preparation CRS and clip to the buffered watershed
    soil_gdf = soil_gdf.to_crs(PREP_CRS)
    soil_gdf = gpd.clip(soil_gdf, aoi["aoi_5070"], keep_geom_type=True)
    soil_gdf = soil_gdf[~soil_gdf.geometry.is_empty].reset_index(drop=True)
    if len(soil_gdf) == 0:
        raise RuntimeError(
            "No SSURGO soil polygons remained after clipping to the "
            "watershed boundary."
        )

    missing_hsg = soil_gdf["hydgrpdcd"].isna() | (soil_gdf["hydgrpdcd"] == "")
    missing_hsg_count = int(missing_hsg.sum())
    if missing_hsg_count:
        say(
            f"Soil: {missing_hsg_count} polygons have no hydrologic group "
            "in SSURGO (often water or urban land); they are kept in the "
            "layer and reported by the CN workflow as missing hydrogroups.",
            message_callback,
        )

    # Area summary by hydrologic group (equal-area CRS, so areas are exact)
    summary_gdf = soil_gdf.copy()
    summary_gdf["hsg"] = summary_gdf["hydgrpdcd"].fillna("No data").replace("", "No data")
    summary_gdf["area_acres"] = summary_gdf.geometry.area / 4046.86
    summary = (
        summary_gdf.groupby("hsg", as_index=False)["area_acres"].sum()
        .rename(columns={"hsg": "hydrologic_group"})
    )
    summary["percent_area"] = (
        100 * summary["area_acres"] / summary["area_acres"].sum()
    )
    summary = summary.sort_values("area_acres", ascending=False).reset_index(drop=True)

    # Write the zipped shapefile the CN workflow imports directly
    _progress(0.82, "Soil: writing the soil shapefile")
    export_gdf = soil_gdf[["mukey", "musym", "muname", "hydgrpdcd", "geometry"]].copy()
    zip_path = write_shapefile_zip(export_gdf, output_dir, "soil_hsg_polygons")
    say(f"Soil: shapefile saved: {zip_path}", message_callback)

    # Rasterize the hydrologic groups for the downloadable soil raster
    _progress(0.90, "Soil: writing the hydrologic soil group raster")
    from rasterio import features as rio_features

    transform, width, height, _ = aligned_grid(aoi["bounds_5070"])
    codes = soil_gdf["hydgrpdcd"].map(HSG_CODES).fillna(SOIL_NODATA).astype(int)
    shapes = [
        (geom, code)
        for geom, code in zip(soil_gdf.geometry, codes)
        if code != SOIL_NODATA
    ]
    raster = np.full((height, width), SOIL_NODATA, dtype=np.uint8)
    if shapes:
        raster = rio_features.rasterize(
            shapes,
            out_shape=(height, width),
            transform=transform,
            fill=SOIL_NODATA,
            dtype="uint8",
        )
    raster = clip_array_to_aoi(raster, transform, aoi["aoi_5070"], SOIL_NODATA)

    colormap = {SOIL_NODATA: (0, 0, 0, 0)}
    for group, code in HSG_CODES.items():
        color = HSG_COLORS[group].lstrip("#")
        colormap[code] = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    raster_path = write_raster(
        str(output_dir) + "/soil_hsg_raster.tif",
        raster,
        transform,
        nodata=SOIL_NODATA,
        colormap=colormap,
    )
    say(
        f"Soil: hydrologic group raster saved ({PREP_CELL_SIZE:.0f} m cells, "
        "codes 1=A 2=B 3=C 4=D 5=A/D 6=B/D 7=C/D): " + raster_path,
        message_callback,
    )
    _progress(1.0, "Soil: done")

    return {
        "zip_path": zip_path,
        "raster_path": raster_path,
        "gdf": soil_gdf,
        "summary": summary,
        "polygon_count": len(soil_gdf),
        "missing_hsg_count": missing_hsg_count,
    }
