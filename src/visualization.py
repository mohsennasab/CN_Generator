"""
Visualization Module
Create plots and visual outputs for CN analysis
"""

import matplotlib.pyplot as plt
import seaborn as sns
import geopandas as gpd
import pandas as pd
import numpy as np
from typing import Optional
import io
import base64
import folium
import tempfile
import os
import branca.colormap as cm
import json
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling

def get_file_as_base64(file_path):
    """Convert file to base64 for inline download."""
    try:
        with open(file_path, 'rb') as f:
            return base64.b64encode(f.read()).decode()
    except:
        return ""

def create_csv_download_link(df, filename="watershed_statistics.csv"):
    """Create a CSV download link from DataFrame."""
    try:
        # Create CSV string
        csv_string = df.to_csv(index=False)
        # Convert to base64
        csv_b64 = base64.b64encode(csv_string.encode()).decode()
        return csv_b64, filename
    except:
        return None, None

def read_cn_display_image(raster_path, max_dimension=2048, nodata=0):
    """
    Read the user CN raster as a decimated EPSG:4326 image for map display.

    This only affects how the map overlay is drawn. The downloadable GeoTIFF
    and all statistics keep the full native resolution and CRS.

    Returns:
    --------
    tuple : (uint8 array, (south, west, north, east) bounds)
    """
    with rasterio.open(raster_path) as src:
        needs_warp = src.crs is not None and src.crs.to_epsg() != 4326
        vrt = None
        try:
            if needs_warp:
                vrt = WarpedVRT(
                    src,
                    crs="EPSG:4326",
                    resampling=Resampling.nearest,
                    src_nodata=nodata,
                    nodata=nodata,
                )
            dataset = vrt if vrt is not None else src
            scale = max(dataset.width, dataset.height) / float(max_dimension)
            if scale > 1:
                out_shape = (
                    max(1, int(dataset.height / scale)),
                    max(1, int(dataset.width / scale)),
                )
            else:
                out_shape = (dataset.height, dataset.width)
            data = dataset.read(1, out_shape=out_shape)
            bounds = dataset.bounds
        finally:
            if vrt is not None:
                vrt.close()
    return data, (bounds.bottom, bounds.left, bounds.top, bounds.right)


def add_watershed_cn_labels(layer, watershed_gdf, watershed_field, stats_df,
                            prefix, position="center"):
    """
    Add per-watershed mean CN text labels to a map layer.

    The labels live inside the raster layer's FeatureGroup, so toggling the
    layer on or off also toggles its labels. When two raster layers are shown
    at once, "above"/"below" offsets keep both labels readable.
    """
    if watershed_gdf is None or watershed_field is None or stats_df is None:
        return

    offsets = {
        "above": "translate(0, -120%)",
        "below": "translate(0, 25%)",
        "center": "none",
    }
    transform = offsets.get(position, "none")

    for idx, row in watershed_gdf.iterrows():
        try:
            watershed_name = row[watershed_field]
            centroid = row.geometry.centroid

            mean_cn = "N/A"
            if watershed_name in stats_df[watershed_field].values:
                stats_row = stats_df[stats_df[watershed_field] == watershed_name]
                if not stats_row.empty and 'mean' in stats_row.columns:
                    mean_cn = f"{stats_row['mean'].iloc[0]:.1f}"

            label_text = f"{prefix}={mean_cn}"

            folium.Marker(
                location=[centroid.y, centroid.x],
                icon=folium.DivIcon(
                    html=f'''<div class="watershed-label" style="
                        font-size: 16px;
                        font-weight: bold;
                        color: white;
                        text-shadow: 2px 2px 4px black;
                        white-space: nowrap;
                        transform: {transform};
                    ">{label_text}</div>''',
                    class_name='watershed-label-marker',
                    icon_size=(0, 0),
                    icon_anchor=(0, 0)
                )
            ).add_to(layer)
        except Exception as e:
            print(f"Warning: Could not add label for watershed {row.get(watershed_field, 'unknown')}: {e}")
            continue


def clean_gdf_for_folium(gdf, keep_columns=None):
    """Clean GeoDataFrame for Folium visualization by removing problematic columns."""
    if keep_columns is None:
        keep_columns = ['geometry']
        # Keep only numeric/string columns that aren't datetime
        for col in gdf.columns:
            if col != 'geometry':
                col_type = str(gdf[col].dtype).lower()
                if not any(x in col_type for x in ['datetime', 'timestamp', 'period']):
                    keep_columns.append(col)
    
    # Only keep columns that exist in the GeoDataFrame
    keep_columns = [col for col in keep_columns if col in gdf.columns]
    clean_gdf = gdf[keep_columns].copy()
    
    # Convert any remaining problematic columns to strings
    for col in clean_gdf.columns:
        if col != 'geometry':
            try:
                # Test if column can be JSON serialized
                if len(clean_gdf) > 0:
                    json.dumps(clean_gdf[col].iloc[0], default=str)
            except (TypeError, ValueError):
                clean_gdf[col] = clean_gdf[col].astype(str)
    
    return clean_gdf

class CNVisualization:
    """Create visualizations for Curve Number analysis."""
    
    @staticmethod
    def create_leafmap(cn_gdf: Optional[gpd.GeoDataFrame],
                      cn_raster_path: Optional[str],
                      watershed_gdf: Optional[gpd.GeoDataFrame] = None,
                      watershed_field: Optional[str] = None,
                      watershed_stats: Optional[pd.DataFrame] = None,
                      gcn10_raster_path: Optional[str] = None,
                      gcn10_label: Optional[str] = None,
                      gcn10_watershed_stats: Optional[pd.DataFrame] = None) -> str:
        """
        Create an interactive folium map. Both CN sources are drawn as raster
        image overlays, which keeps the map clean and fast to load.

        Parameters:
        -----------
        cn_gdf : GeoDataFrame, optional
            GeoDataFrame with CN values, used for the shared color scale
            (None when only GCN10 is processed)
        cn_raster_path : str, optional
            Path to the user CN raster shown as an image overlay
        watershed_gdf : GeoDataFrame, optional
            Watershed boundaries
        watershed_field : str, optional
            Field name for watershed identifiers
        watershed_stats : DataFrame, optional
            Watershed statistics for the user CN raster (mean CN labels)
        gcn10_raster_path : str, optional
            Path to a clipped GCN10 raster (EPSG:4326) to show as an overlay
        gcn10_label : str, optional
            Layer name for the GCN10 overlay
        gcn10_watershed_stats : DataFrame, optional
            Watershed statistics for the GCN10 raster (GCN10 labels)

        Returns:
        --------
        str : HTML content for the map
        """
        # Folium works in geographic coordinates, so reproject display copies
        if cn_gdf is not None and cn_gdf.crs is not None and not cn_gdf.crs.to_string().startswith('EPSG:4326'):
            cn_gdf = cn_gdf.to_crs('EPSG:4326')
        if watershed_gdf is not None and watershed_gdf.crs is not None and not watershed_gdf.crs.to_string().startswith('EPSG:4326'):
            watershed_gdf = watershed_gdf.to_crs('EPSG:4326')

        # Read the user CN raster as a display image (reprojected to EPSG:4326)
        cn_image = None
        cn_bounds = None
        if cn_raster_path is not None:
            try:
                cn_image, cn_bounds = read_cn_display_image(cn_raster_path)
            except Exception as e:
                print(f"Warning: Could not read the CN raster for map display: {e}")

        # Read the GCN10 display image so it can define map bounds too
        gcn10_image = None
        gcn10_bounds = None
        if gcn10_raster_path is not None:
            from src.gcn10 import read_display_image, GCN10_NODATA
            gcn10_image, gcn10_bounds = read_display_image(gcn10_raster_path)

        # Calculate map extent from whichever layers are available
        if cn_bounds is not None:
            south, west, north, east = cn_bounds
            bounds = (west, south, east, north)
        elif cn_gdf is not None:
            bounds = cn_gdf.total_bounds
        elif watershed_gdf is not None:
            bounds = watershed_gdf.total_bounds
        elif gcn10_bounds is not None:
            south, west, north, east = gcn10_bounds
            bounds = (west, south, east, north)
        else:
            bounds = (-180, -90, 180, 90)
        center_lat = (bounds[1] + bounds[3]) / 2
        center_lon = (bounds[0] + bounds[2]) / 2
        
        # Create folium map with no default tiles (we'll add basemaps manually)
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=10,
            tiles=None
        )
        
        # Add basemap options
        # OpenStreetMap (default, checked)
        folium.TileLayer(
            tiles='OpenStreetMap',
            name='OpenStreetMap',
            overlay=False,
            control=True,
            show=True
        ).add_to(m)
        
        # ESRI World Imagery (satellite, unchecked by default)
        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attr='Esri',
            name='Satellite Imagery',
            overlay=False,
            control=True,
            show=False
        ).add_to(m)
        
        # Fit map bounds to CN data extent
        m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
        
        # Create one shared colormap so CN polygons and GCN10 use the same scale
        value_mins = []
        value_maxs = []
        if cn_gdf is not None:
            value_mins.append(float(cn_gdf['CN'].min()))
            value_maxs.append(float(cn_gdf['CN'].max()))
        if gcn10_image is not None:
            gcn10_valid = gcn10_image[gcn10_image != GCN10_NODATA]
            if gcn10_valid.size > 0:
                value_mins.append(float(gcn10_valid.min()))
                value_maxs.append(float(gcn10_valid.max()))
        min_cn = min(value_mins) if value_mins else 30
        max_cn = max(value_maxs) if value_maxs else 100
        if max_cn <= min_cn:
            max_cn = min_cn + 1

        colormap = cm.LinearColormap(
            colors=['#0000FF', '#4169E1', '#00CED1', '#FFD700', '#FFA500', '#FF4500', '#DC143C', '#8B0000'],
            vmin=min_cn,
            vmax=max_cn,
            caption='Curve Number Values'
        )

        # When both rasters are shown, offset their labels so they can be
        # read at the same time (CN above the centroid, GCN10 below it)
        both_label_sets = watershed_stats is not None and gcn10_watershed_stats is not None

        # Add the user CN raster as a toggleable image overlay
        if cn_image is not None:
            # Build an RGBA image from the shared colormap, NoData (0) transparent
            lut = np.zeros((256, 4), dtype=np.uint8)
            for cn in range(1, 101):
                rgba = colormap.rgba_bytes_tuple(min(max(cn, min_cn), max_cn))
                lut[cn] = (rgba[0], rgba[1], rgba[2], 255)
            rgba_image = lut[cn_image]

            south, west, north, east = cn_bounds
            cn_layer = folium.FeatureGroup(name='CN Raster (Your Data)', control=True, show=True)
            folium.raster_layers.ImageOverlay(
                image=rgba_image,
                bounds=[[south, west], [north, east]],
                opacity=0.8,
                mercator_project=True,
                origin='upper',
            ).add_to(cn_layer)

            # Mean CN labels travel with this layer's on/off toggle
            add_watershed_cn_labels(
                cn_layer, watershed_gdf, watershed_field, watershed_stats,
                prefix='CN', position='above' if both_label_sets else 'center'
            )

            cn_layer.add_to(m)

        # Add the GCN10 raster as a toggleable image overlay
        if gcn10_image is not None:
            # Build an RGBA image from the shared colormap, NoData transparent
            lut = np.zeros((256, 4), dtype=np.uint8)
            for cn in range(0, 101):
                rgba = colormap.rgba_bytes_tuple(min(max(cn, min_cn), max_cn))
                lut[cn] = (rgba[0], rgba[1], rgba[2], 255)
            lut[GCN10_NODATA] = (0, 0, 0, 0)
            rgba_image = lut[gcn10_image]

            south, west, north, east = gcn10_bounds
            gcn10_layer = folium.FeatureGroup(
                name=gcn10_label or 'GCN10',
                control=True,
                show=(cn_image is None)
            )
            folium.raster_layers.ImageOverlay(
                image=rgba_image,
                bounds=[[south, west], [north, east]],
                opacity=0.8,
                mercator_project=True,
                origin='upper',
            ).add_to(gcn10_layer)

            # GCN10 mean labels travel with this layer's on/off toggle
            add_watershed_cn_labels(
                gcn10_layer, watershed_gdf, watershed_field, gcn10_watershed_stats,
                prefix='GCN10', position='below' if both_label_sets else 'center'
            )

            gcn10_layer.add_to(m)
        
        # Add watersheds as hollow polygons with labels if provided
        # (both layers were already reprojected to EPSG:4326 above)
        if watershed_gdf is not None and watershed_field is not None:
            # Create FeatureGroup for watersheds with layer control
            watershed_layer = folium.FeatureGroup(name='Watersheds', control=True, show=True)
            
            def watershed_style(feature):
                return {
                    'color': '#000000',
                    'weight': 2,
                    'fillOpacity': 0,
                    'opacity': 1,
                    'dashArray': '5, 5'
                }
            
            # Clean watershed GeoDataFrame
            watershed_clean = clean_gdf_for_folium(watershed_gdf, ['geometry', watershed_field])
            
            # Add watershed polygons
            folium.GeoJson(
                watershed_clean,
                style_function=watershed_style,
                tooltip=folium.GeoJsonTooltip(
                    fields=[watershed_field],
                    aliases=['Watershed:'],
                    labels=True,
                    sticky=True,
                    style='background-color: white; color: #000000; font-family: arial; font-size: 12px; padding: 10px;'
                )
            ).add_to(watershed_layer)

            watershed_layer.add_to(m)
        
        # Add colormap legend to map
        colormap.add_to(m)
        
        # REMOVED: Runoff potential legend (as requested)
        
        # Add layer control
        folium.LayerControl(
            position='topright',
            collapsed=False
        ).add_to(m)
        
        # Add JavaScript for dynamic text scaling based on zoom level
        zoom_script = '''
        <script>
            // Wait for the map to be fully loaded
            window.addEventListener('load', function() {
                // Get the leaflet map instance
                var maps = window[Object.keys(window).find(key => key.startsWith('map_'))];
                if (maps) {
                    // Function to update watershed label sizes based on zoom
                    function updateLabelSizes() {
                        var currentZoom = maps.getZoom();
                        var fontSize;
                        
                        // Scale font size based on zoom level
                        if (currentZoom <= 8) {
                            fontSize = '12px';
                        } else if (currentZoom <= 10) {
                            fontSize = '14px';
                        } else if (currentZoom <= 12) {
                            fontSize = '16px';
                        } else if (currentZoom <= 14) {
                            fontSize = '18px';
                        } else if (currentZoom <= 16) {
                            fontSize = '20px';
                        } else {
                            fontSize = '22px';
                        }
                        
                        // Update all watershed labels
                        var labels = document.querySelectorAll('.watershed-label');
                        labels.forEach(function(label) {
                            label.style.fontSize = fontSize;
                        });
                    }
                    
                    // Update on zoom end
                    maps.on('zoomend', updateLabelSizes);
                    
                    // Initial update
                    setTimeout(updateLabelSizes, 1000);
                }
            });
        </script>
        '''
        
        # Convert to HTML string and wrap with taller container
        map_html = m._repr_html_()

        # Dataset credit shown under the map when the GCN10 layer is included
        gcn10_credit = ''
        if gcn10_image is not None:
            from src.gcn10 import GCN10_ATTRIBUTION, GCN10_DATASET_URL
            gcn10_credit = f'''
        <div style="font-size: 12px; padding: 4px 2px; color: var(--body-text-color-subdued, #666);">
            GCN10 layer: <a href="{GCN10_DATASET_URL}" target="_blank">{GCN10_ATTRIBUTION}</a>, ODbL v1.0
        </div>'''

        # Wrap the map in a tall container, kept narrower than the page and
        # centered so scrolling past it is easier
        wrapped_html = f'''
        <div style="max-width: 1000px; margin: 0 auto;">
            <div style="height: 800px; width: 100%; overflow: hidden; position: relative;">
                {map_html}
            </div>{gcn10_credit}
        </div>
        <style>
            .folium-map {{
                height: 800px !important;
                width: 100% !important;
            }}
            .leaflet-control-container {{
                z-index: 1000 !important;
            }}
            .watershed-label-marker {{
                pointer-events: none;
            }}
        </style>
        {zoom_script}
        '''
        
        return wrapped_html
    
    @staticmethod
    def create_summary_report(cn_gdf: Optional[gpd.GeoDataFrame] = None,
                            stats: Optional[dict] = None,
                            watershed_stats: Optional[pd.DataFrame] = None,
                            excel_path: Optional[str] = None,
                            gcn10_info: Optional[dict] = None,
                            gcn10_watershed_stats: Optional[pd.DataFrame] = None,
                            comparison_stats: Optional[pd.DataFrame] = None,
                            watershed_field: Optional[str] = None) -> str:
        """
        Create HTML summary report with improved dark mode compatibility.
        Removes percentile_10 and percentile_75 from display.
        Adds missing hydrogroup count in red if > 0.

        Parameters:
        -----------
        cn_gdf : GeoDataFrame, optional
            GeoDataFrame with CN values (None when only GCN10 is processed)
        stats : dict, optional
            Global statistics for the user-generated CN data
        watershed_stats : DataFrame, optional
            Watershed statistics for the user-generated CN raster
        excel_path : str, optional
            Path to Excel file for download
        gcn10_info : dict, optional
            Result dictionary from gcn10.fetch_gcn10_raster
        gcn10_watershed_stats : DataFrame, optional
            Watershed statistics for the GCN10 raster
        comparison_stats : DataFrame, optional
            Side-by-side comparison table from build_comparison_table
        watershed_field : str, optional
            Field with watershed names/IDs

        Returns:
        --------
        str : HTML report content
        """
        html = """
        <html>
        <head>
            <style>
                body { 
                    font-family: Arial, sans-serif; 
                    margin: 20px; 
                    background-color: transparent;
                    color: var(--body-text-color);
                }
                h1 { 
                    color: var(--body-text-color); 
                    text-align: center;
                    margin-bottom: 30px;
                }
                h2 { 
                    color: var(--body-text-color); 
                    border-bottom: 1px solid var(--border-color-primary); 
                    padding-bottom: 10px; 
                    margin-top: 30px;
                }
                table { 
                    border-collapse: collapse; 
                    width: 100%; 
                    margin: 20px 0; 
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                }
                th, td { 
                    border: 1px solid var(--border-color-primary); 
                    padding: 12px; 
                    text-align: left; 
                }
                th { 
                    background-color: var(--button-primary-background-fill, #2f766d); 
                    color: var(--button-primary-text-color, #ffffff); 
                    font-weight: bold;
                }
                tr:nth-child(even) { 
                    background-color: var(--input-background-fill); 
                }
                tr:hover {
                    background-color: var(--block-background-fill);
                }
                .stat-box { 
                    display: inline-block; 
                    padding: 12px 16px; 
                    margin: 8px;
                    background: var(--block-background-fill); 
                    color: var(--body-text-color);
                    border: 1px solid var(--border-color-primary);
                    border-radius: 8px;
                    font-weight: 600;
                    min-width: 120px;
                    text-align: center;
                }
                .stat-box.warning { 
                    background: var(--block-background-fill);
                    border-color: var(--error-border-color, var(--border-color-primary));
                    color: var(--body-text-color);
                }
                .stats-container {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 10px;
                    margin: 20px 0;
                    justify-content: center;
                }
                .footnote {
                    font-size: 12px;
                    color: var(--body-text-color-subdued, var(--body-text-color));
                    margin-top: 10px;
                    font-style: italic;
                }
                .download-button {
                    display: inline-block;
                    background: var(--button-primary-background-fill, #2f766d);
                    color: var(--button-primary-text-color, #ffffff) !important;
                    padding: 8px 16px;
                    text-decoration: none;
                    border-radius: 6px;
                    font-weight: bold;
                    margin-left: 15px;
                    transition: transform 0.2s;
                    font-size: 14px;
                }
                .download-button:hover {
                    transform: translateY(-2px);
                    text-decoration: none;
                    color: var(--button-primary-text-color, #ffffff) !important;
                }
                .section-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                }
            </style>
        </head>
        <body>
            <h1>SCS Curve Number Analysis Report</h1>
        """
        
        # Global Statistics Section - excluding percentile_10 and percentile_75
        if stats is not None:
            user_stats_heading = "Global Statistics" if gcn10_info is None else "Your Generated CN: Summary Statistics"
            html += f"<h2>{user_stats_heading}</h2>"
            html += '<div class="stats-container">'

            # Define which statistics to exclude
            excluded_stats = {'percentile_10', 'percentile_75', 'count', 'unique_values', 'missing_hydrogroup_count'}
            labels = {
                'min': 'Minimum CN',
                'max': 'Maximum CN',
                'mean': 'Mean CN',
                'weighted_mean': 'Weighted Mean CN',
                'median': 'Median CN',
                'std': 'Std. Dev.',
                'percentile_25': '25th Percentile',
                'percentile_50': '50th Percentile',
                'percentile_90': '90th Percentile',
            }

            for key, value in stats.items():
                if key not in excluded_stats and isinstance(value, (int, float)):
                    display_key = labels.get(key, key.replace("_", " ").title())
                    html += f'<div class="stat-box"><strong>{display_key}</strong><br>{value:.2f}</div>'

            # Add missing hydrogroup count in red if > 0
            if 'missing_hydrogroup_count' in stats and stats['missing_hydrogroup_count'] > 0:
                html += f'<div class="stat-box warning"><strong>Missing Hydrogroups</strong><br>{stats["missing_hydrogroup_count"]}</div>'

            html += "</div>"

            # Add footnote for weighted mean
            html += '<div class="footnote">* Weighted Mean is calculated using polygon areas as weights, providing a more representative average for the study area.</div>'

            # Add warning footnote if there are missing hydrogroups
            if 'missing_hydrogroup_count' in stats and stats['missing_hydrogroup_count'] > 0:
                html += f'<div class="footnote" style="font-weight: bold;">** {stats["missing_hydrogroup_count"]} soil polygons have missing or invalid hydrologic group values and were excluded from analysis.</div>'

        # GCN10 summary statistics
        if gcn10_info is not None:
            gcn10_label = gcn10_info.get('label', 'GCN10')
            html += f"<h2>{gcn10_label}: Summary Statistics</h2>"
            html += '<div class="stats-container">'
            gcn10_labels = [
                ('min', 'Minimum CN'),
                ('max', 'Maximum CN'),
                ('mean', 'Mean CN'),
                ('median', 'Median CN'),
                ('std', 'Std. Dev.'),
            ]
            gcn10_stats = gcn10_info.get('stats', {})
            for key, display_key in gcn10_labels:
                if key in gcn10_stats:
                    html += f'<div class="stat-box"><strong>{display_key}</strong><br>{gcn10_stats[key]:.2f}</div>'
            html += "</div>"
            html += ('<div class="footnote">GCN10 values are read from the global 10 m dataset on its '
                     'native EPSG:4326 grid, clipped to your boundary. Statistics are computed from all '
                     'valid cells inside the boundary.</div>')
        
        # Watershed Statistics (if provided)
        if watershed_stats is not None and not watershed_stats.empty:
            display_columns = [
                col for col in [watershed_stats.columns[0], 'mean', 'min', 'max', 'median', 'std', 'cv', 'range']
                if col in watershed_stats.columns
            ]
            report_stats = watershed_stats[display_columns].copy()
            report_stats = report_stats.rename(columns={
                'mean': 'Mean CN',
                'min': 'Minimum CN',
                'max': 'Maximum CN',
                'median': 'Median CN',
                'std': 'Std. Dev.',
                'cv': 'Coeff. Variation (%)',
                'range': 'CN Range',
            })

            # Create CSV download
            csv_b64, csv_filename = create_csv_download_link(report_stats, "watershed_statistics.csv")
            
            # Header with download button
            ws_heading = "Watershed Statistics (First 5 Rows)" if gcn10_info is None else "Watershed Statistics, Your CN (First 5 Rows)"
            html += '<div class="section-header">'
            html += f'<h2 style="margin: 0; border: none; padding: 0;">{ws_heading}</h2>'
            
            if csv_b64:
                html += f'''
                <a href="data:text/csv;base64,{csv_b64}" 
                   download="{csv_filename}" class="download-button">
                   Download Complete CSV ({len(report_stats)} rows)
                </a>
                '''
            
            html += '</div>'
            
            # Show only first 5 rows
            display_stats = report_stats.head(5).copy()
            
            # Format the watershed stats table
            watershed_html = display_stats.to_html(
                index=False, 
                classes='watershed-table',
                table_id='watershed-stats',
                float_format=lambda x: '{:.2f}'.format(x) if pd.notna(x) else 'N/A'
            )
            html += watershed_html
            
            html += '<p><em>The table above shows the first 5 rows. Use the download button to get all watershed statistics.</em></p>'

        # GCN10 watershed statistics
        if gcn10_watershed_stats is not None and not gcn10_watershed_stats.empty:
            gcn10_label = gcn10_info.get('label', 'GCN10') if gcn10_info else 'GCN10'
            display_columns = [
                col for col in [gcn10_watershed_stats.columns[0], 'mean', 'min', 'max', 'median', 'std', 'cv', 'range']
                if col in gcn10_watershed_stats.columns
            ]
            gcn10_report_stats = gcn10_watershed_stats[display_columns].copy()
            gcn10_report_stats = gcn10_report_stats.rename(columns={
                'mean': 'Mean CN',
                'min': 'Minimum CN',
                'max': 'Maximum CN',
                'median': 'Median CN',
                'std': 'Std. Dev.',
                'cv': 'Coeff. Variation (%)',
                'range': 'CN Range',
            })

            csv_b64, csv_filename = create_csv_download_link(gcn10_report_stats, "gcn10_watershed_statistics.csv")

            html += '<div class="section-header">'
            html += f'<h2 style="margin: 0; border: none; padding: 0;">Watershed Statistics, {gcn10_label} (First 5 Rows)</h2>'
            if csv_b64:
                html += f'''
                <a href="data:text/csv;base64,{csv_b64}"
                   download="{csv_filename}" class="download-button">
                   Download Complete CSV ({len(gcn10_report_stats)} rows)
                </a>
                '''
            html += '</div>'

            html += gcn10_report_stats.head(5).to_html(
                index=False,
                classes='watershed-table',
                float_format=lambda x: '{:.2f}'.format(x) if pd.notna(x) else 'N/A'
            )
            html += '<p><em>The table above shows the first 5 rows. Use the download button to get the full table.</em></p>'

        # Side-by-side comparison of the two CN sources
        if comparison_stats is not None and not comparison_stats.empty:
            comparison_display = comparison_stats.rename(columns={
                'user_mean': 'Mean (Yours)',
                'gcn10_mean': 'Mean (GCN10)',
                'mean_diff': 'Mean Difference',
                'user_median': 'Median (Yours)',
                'gcn10_median': 'Median (GCN10)',
                'user_min': 'Min (Yours)',
                'gcn10_min': 'Min (GCN10)',
                'user_max': 'Max (Yours)',
                'gcn10_max': 'Max (GCN10)',
            })

            csv_b64, csv_filename = create_csv_download_link(comparison_display, "cn_comparison.csv")

            html += '<div class="section-header">'
            html += '<h2 style="margin: 0; border: none; padding: 0;">Comparison: Your CN vs GCN10 (First 5 Rows)</h2>'
            if csv_b64:
                html += f'''
                <a href="data:text/csv;base64,{csv_b64}"
                   download="{csv_filename}" class="download-button">
                   Download Complete CSV ({len(comparison_display)} rows)
                </a>
                '''
            html += '</div>'

            html += comparison_display.head(5).to_html(
                index=False,
                classes='watershed-table',
                float_format=lambda x: '{:.2f}'.format(x) if pd.notna(x) else 'N/A'
            )
            html += ('<div class="footnote">Each product is summarized on its own grid over the same watershed '
                     'polygons, so differences reflect the underlying data sources rather than resampling. '
                     'Mean Difference is your mean CN minus the GCN10 mean CN.</div>')

        # GCN10 credit and citation (required by the dataset license)
        if gcn10_info is not None:
            from src.gcn10 import (GCN10_ATTRIBUTION, GCN10_CITATION,
                                   GCN10_LICENSE_NOTE, GCN10_DATASET_URL)
            html += '<h2>GCN10 Data Credit</h2>'
            html += (f'<p>GCN10 data source: <a href="{GCN10_DATASET_URL}" target="_blank">'
                     f'{GCN10_ATTRIBUTION}</a>. {GCN10_LICENSE_NOTE}</p>')
            html += f'<p class="footnote">Citation: {GCN10_CITATION}</p>'

        html += """
        </body>
        </html>
        """

        return html
