"""
Data Preparation - Preview Map
Interactive map showing the prepared NLCD land cover and soil hydrologic
group layers with the watershed boundary, each toggleable, using the same
size and styling as the results map.
"""

import folium
import numpy as np

from .nlcd import NLCD_CLASSES, NLCD_COLORS, NLCD_NODATA
from .soil import HSG_COLORS, HSG_LABELS, SOIL_NODATA


def _hex_to_rgb(hex_color):
    color = hex_color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _add_raster_overlay(map_obj, raster_path, lut, name, show, nodata):
    """Add a categorical raster as a color image overlay with its own toggle."""
    from src.visualization import read_cn_display_image

    image, (south, west, north, east) = read_cn_display_image(
        raster_path, nodata=nodata
    )
    rgba = lut[image]
    layer = folium.FeatureGroup(name=name, control=True, show=show)
    folium.raster_layers.ImageOverlay(
        image=rgba,
        bounds=[[south, west], [north, east]],
        opacity=0.8,
        mercator_project=True,
        origin="upper",
    ).add_to(layer)
    layer.add_to(map_obj)
    return image, (west, south, east, north)


def _legend_html(title, entries):
    """A small floating legend box; entries are (color, label) pairs."""
    rows = "".join(
        f'<div style="margin: 2px 0; white-space: nowrap;">'
        f'<span style="display: inline-block; width: 14px; height: 14px; '
        f'background: {color}; border: 1px solid #00000033; '
        f'vertical-align: middle; margin-right: 6px;"></span>'
        f'<span style="vertical-align: middle;">{label}</span></div>'
        for color, label in entries
    )
    return (
        f'<div style="background: #ffffff; color: #222222; padding: 8px 10px; '
        f'border: 1px solid #999999; border-radius: 6px; font-size: 12px; '
        f'font-family: Arial, sans-serif; margin-bottom: 8px;">'
        f'<div style="font-weight: bold; margin-bottom: 4px;">{title}</div>'
        f"{rows}</div>"
    )


def create_prep_map(
    watershed_gdf,
    watershed_field=None,
    nlcd_raster_path=None,
    nlcd_year=None,
    soil_raster_path=None,
    nlcd_summary=None,
    soil_summary=None,
):
    """
    Build the Data Preparation preview map as embeddable HTML.

    Parameters
    ----------
    watershed_gdf : GeoDataFrame
        Watershed boundaries (any CRS with metadata).
    watershed_field : str, optional
        Field with watershed names for the boundary tooltip.
    nlcd_raster_path : str, optional
        Clipped NLCD land cover GeoTIFF (EPSG:5070).
    nlcd_year : int, optional
        NLCD year for the layer name.
    soil_raster_path : str, optional
        Hydrologic soil group raster GeoTIFF (EPSG:5070).
    nlcd_summary : DataFrame, optional
        Class area summary; when given, the legend lists only classes present.
    soil_summary : DataFrame, optional
        Hydrologic group area summary for the soil legend.
    """
    display_gdf = watershed_gdf
    if display_gdf.crs is not None and not str(display_gdf.crs).startswith("EPSG:4326"):
        display_gdf = display_gdf.to_crs("EPSG:4326")

    bounds = display_gdf.total_bounds
    center_lat = (bounds[1] + bounds[3]) / 2
    center_lon = (bounds[0] + bounds[2]) / 2

    m = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles=None)
    folium.TileLayer(
        tiles="OpenStreetMap", name="OpenStreetMap",
        overlay=False, control=True, show=True,
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite Imagery",
        overlay=False, control=True, show=False,
    ).add_to(m)
    m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

    legends = []

    # NLCD land cover overlay with the official colors
    if nlcd_raster_path is not None:
        lut = np.zeros((256, 4), dtype=np.uint8)
        for code, hex_color in NLCD_COLORS.items():
            lut[code] = _hex_to_rgb(hex_color) + (255,)
        lut[NLCD_NODATA] = (0, 0, 0, 0)
        layer_name = f"NLCD {nlcd_year} Land Cover" if nlcd_year else "NLCD Land Cover"
        _add_raster_overlay(
            m, nlcd_raster_path, lut, layer_name, show=True, nodata=NLCD_NODATA
        )
        if nlcd_summary is not None and len(nlcd_summary) > 0:
            entries = [
                (NLCD_COLORS.get(int(row.gridcode), "#888888"),
                 f"{int(row.gridcode)} {row.landuse}")
                for row in nlcd_summary.itertuples()
            ]
        else:
            entries = [
                (color, f"{code} {NLCD_CLASSES[code]}")
                for code, color in NLCD_COLORS.items()
            ]
        legends.append(_legend_html(layer_name, entries))

    # Soil hydrologic group overlay
    if soil_raster_path is not None:
        lut = np.zeros((256, 4), dtype=np.uint8)
        for code, group in HSG_LABELS.items():
            lut[code] = _hex_to_rgb(HSG_COLORS[group]) + (255,)
        lut[SOIL_NODATA] = (0, 0, 0, 0)
        _add_raster_overlay(
            m, soil_raster_path, lut, "Soil Hydrologic Groups",
            show=(nlcd_raster_path is None), nodata=SOIL_NODATA,
        )
        if soil_summary is not None and len(soil_summary) > 0:
            groups_present = [
                g for g in soil_summary["hydrologic_group"] if g in HSG_COLORS
            ]
        else:
            groups_present = list(HSG_COLORS)
        entries = [(HSG_COLORS[g], f"Group {g}") for g in groups_present]
        legends.append(_legend_html("Soil Hydrologic Groups", entries))

    # Watershed boundary on top, toggleable
    boundary_layer = folium.FeatureGroup(name="Watersheds", control=True, show=True)
    tooltip = None
    keep = ["geometry"]
    if watershed_field and watershed_field in display_gdf.columns:
        keep.append(watershed_field)
        tooltip = folium.GeoJsonTooltip(
            fields=[watershed_field],
            aliases=["Watershed:"],
            labels=True,
            sticky=True,
            style=("background-color: white; color: #000000; "
                   "font-family: arial; font-size: 12px; padding: 10px;"),
        )
    folium.GeoJson(
        display_gdf[keep],
        style_function=lambda feature: {
            "color": "#000000",
            "weight": 2,
            "fillOpacity": 0,
            "opacity": 1,
            "dashArray": "5, 5",
        },
        tooltip=tooltip,
    ).add_to(boundary_layer)
    boundary_layer.add_to(m)

    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    map_html = m._repr_html_()
    legend_column = "".join(legends)
    legend_block = (
        f'<div style="position: absolute; bottom: 20px; left: 10px; '
        f'z-index: 1000; max-height: 60%; overflow-y: auto;">{legend_column}</div>'
        if legend_column
        else ""
    )

    return f'''
    <div style="max-width: 1000px; margin: 0 auto;">
        <div style="height: 800px; width: 100%; overflow: hidden; position: relative;">
            {map_html}{legend_block}
        </div>
        <div style="font-size: 12px; padding: 4px 2px; color: var(--body-text-color-subdued, #666);">
            Land cover: National Land Cover Database, USGS / MRLC Consortium.
            Soils: SSURGO Database, USDA-NRCS Soil Data Access.
        </div>
    </div>
    <style>
        .folium-map {{
            height: 800px !important;
            width: 100% !important;
        }}
        .leaflet-control-container {{
            z-index: 1000 !important;
        }}
    </style>
    '''
