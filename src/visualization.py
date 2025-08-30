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
    def create_leafmap(cn_gdf: gpd.GeoDataFrame, 
                      cn_raster_path: str,
                      watershed_gdf: Optional[gpd.GeoDataFrame] = None,
                      watershed_field: Optional[str] = None,
                      watershed_stats: Optional[pd.DataFrame] = None) -> str:
        """
        Create interactive map using folium with CN polygons, watersheds, and enhanced features.
        
        Parameters:
        -----------
        cn_gdf : GeoDataFrame
            GeoDataFrame with CN values
        cn_raster_path : str
            Path to CN raster file (for bounds reference)
        watershed_gdf : GeoDataFrame, optional
            Watershed boundaries
        watershed_field : str, optional
            Field name for watershed identifiers
        watershed_stats : DataFrame, optional
            Watershed statistics with mean CN values
            
        Returns:
        --------
        str : HTML content for the map
        """
        # Calculate center point from CN data bounds
        bounds = cn_gdf.total_bounds
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
        
        # Create colormap for CN values
        min_cn = cn_gdf['CN'].min()
        max_cn = cn_gdf['CN'].max()
        
        colormap = cm.LinearColormap(
            colors=['#0000FF', '#4169E1', '#00CED1', '#FFD700', '#FFA500', '#FF4500', '#DC143C', '#8B0000'],
            vmin=min_cn,
            vmax=max_cn,
            caption='Curve Number Values'
        )
        
        # Add CN polygons with color coding in a FeatureGroup for layer control
        def style_function(feature):
            cn_value = feature['properties']['CN']
            return {
                'fillColor': colormap(cn_value),
                'color': 'black',
                'weight': 0.5,
                'fillOpacity': 0.8,
                'opacity': 1
            }
        
        def highlight_function(feature):
            return {
                'fillOpacity': 1.0,
                'weight': 2,
                'color': 'white'
            }
        
        # Create FeatureGroup for CN polygons with layer control
        cn_layer = folium.FeatureGroup(name='CN Polygons', control=True, show=True)
        
        # Clean the GeoDataFrame to remove non-JSON serializable columns
        cn_gdf_clean = clean_gdf_for_folium(cn_gdf, ['geometry', 'CN'])
        
        # Remove area_ha from tooltip as it's showing 0
        folium.GeoJson(
            cn_gdf_clean,
            style_function=style_function,
            highlight_function=highlight_function,
            tooltip=folium.GeoJsonTooltip(
                fields=['CN'],
                aliases=['Curve Number:'],
                labels=True,
                sticky=True,
                style='background-color: white; color: #000000; font-family: arial; font-size: 12px; padding: 10px;'
            ),
            popup=folium.GeoJsonPopup(
                fields=['CN'],
                aliases=['CN:'],
                max_width=200
            )
        ).add_to(cn_layer)
        
        cn_layer.add_to(m)
        
        # Add watersheds as hollow polygons with labels if provided
        if watershed_gdf is not None and watershed_field is not None:
            # Ensure same CRS as CN data
            if watershed_gdf.crs != cn_gdf.crs:
                watershed_gdf = watershed_gdf.to_crs(cn_gdf.crs)
            
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
            
            # Add watershed labels with mean CN values - text only, no background
            if watershed_stats is not None:
                for idx, row in watershed_gdf.iterrows():
                    try:
                        watershed_name = row[watershed_field]
                        # Get centroid for label placement
                        centroid = row.geometry.centroid
                        
                        # Find corresponding mean CN from watershed_stats
                        mean_cn = "N/A"
                        if watershed_name in watershed_stats[watershed_field].values:
                            stats_row = watershed_stats[watershed_stats[watershed_field] == watershed_name]
                            if not stats_row.empty and 'mean' in stats_row.columns:
                                mean_cn = f"{stats_row['mean'].iloc[0]:.1f}"
                        
                        # Create label text in new format: CN={value}
                        label_text = f"CN={mean_cn}"
                        
                        # Add label as a DivIcon marker with no background, just text
                        folium.Marker(
                            location=[centroid.y, centroid.x],
                            icon=folium.DivIcon(
                                html=f'''<div class="watershed-label" style="
                                    font-size: 16px;
                                    font-weight: bold;
                                    color: white;
                                    text-shadow: 2px 2px 4px black;
                                    white-space: nowrap;
                                ">{label_text}</div>''',
                                class_name='watershed-label-marker',
                                icon_size=(0, 0),
                                icon_anchor=(0, 0)
                            )
                        ).add_to(watershed_layer)
                        
                    except Exception as e:
                        print(f"Warning: Could not add label for watershed {row.get(watershed_field, 'unknown')}: {e}")
                        continue
            
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
        
        # Wrap the map in a taller container (800px) with zoom script
        wrapped_html = f'''
        <div style="height: 800px; width: 100%; overflow: hidden; position: relative;">
            {map_html}
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
    def create_summary_report(cn_gdf: gpd.GeoDataFrame, 
                            stats: dict,
                            watershed_stats: Optional[pd.DataFrame] = None,
                            excel_path: Optional[str] = None) -> str:
        """
        Create HTML summary report with improved dark mode compatibility.
        Removes percentile_10 and percentile_75 from display.
        Adds missing hydrogroup count in red if > 0.
        
        Parameters:
        -----------
        cn_gdf : GeoDataFrame
            GeoDataFrame with CN values
        stats : dict
            Global statistics
        watershed_stats : DataFrame
            Optional watershed statistics
        excel_path : str
            Path to Excel file for download
            
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
                    background-color: var(--background-fill-primary);
                    color: var(--body-text-color);
                }
                h1 { 
                    color: #2c3e50; 
                    text-align: center;
                    margin-bottom: 30px;
                }
                h2 { 
                    color: #34495e; 
                    border-bottom: 2px solid #3498db; 
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
                    border: 1px solid #ddd; 
                    padding: 12px; 
                    text-align: left; 
                }
                th { 
                    background-color: #3498db; 
                    color: white; 
                    font-weight: bold;
                }
                tr:nth-child(even) { 
                    background-color: rgba(52, 152, 219, 0.1); 
                }
                tr:hover {
                    background-color: rgba(52, 152, 219, 0.2);
                }
                .stat-box { 
                    display: inline-block; 
                    padding: 12px 16px; 
                    margin: 8px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    color: white;
                    border-radius: 10px;
                    font-weight: 600;
                    box-shadow: 0 4px 8px rgba(0,0,0,0.2);
                    min-width: 120px;
                    text-align: center;
                }
                .stat-box.warning { 
                    background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%); 
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
                    color: #666;
                    margin-top: 10px;
                    font-style: italic;
                }
                .download-button {
                    display: inline-block;
                    background: linear-gradient(135deg, #28a745, #20c997);
                    color: white !important;
                    padding: 8px 16px;
                    text-decoration: none;
                    border-radius: 5px;
                    font-weight: bold;
                    margin-left: 15px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                    transition: transform 0.2s;
                    font-size: 14px;
                }
                .download-button:hover {
                    transform: translateY(-2px);
                    text-decoration: none;
                    color: white !important;
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
        html += "<h2>Global Statistics</h2>"
        html += '<div class="stats-container">'
        
        # Define which statistics to exclude
        excluded_stats = {'percentile_10', 'percentile_75', 'count', 'missing_hydrogroup_count'}
        
        for key, value in stats.items():
            if key not in excluded_stats and isinstance(value, (int, float)):
                display_key = key.replace("_", " ").title()
                html += f'<div class="stat-box"><strong>{display_key}</strong><br>{value:.2f}</div>'
        
        # Add missing hydrogroup count in red if > 0
        if 'missing_hydrogroup_count' in stats and stats['missing_hydrogroup_count'] > 0:
            html += f'<div class="stat-box warning"><strong>Missing Hydrogroups</strong><br>{stats["missing_hydrogroup_count"]}</div>'
            
        html += "</div>"
        
        # Add footnote for weighted mean
        html += '<div class="footnote">* Weighted Mean is calculated using polygon areas as weights, providing a more representative average for the study area.</div>'
        
        # Add warning footnote if there are missing hydrogroups
        if 'missing_hydrogroup_count' in stats and stats['missing_hydrogroup_count'] > 0:
            html += f'<div class="footnote" style="color: #e74c3c; font-weight: bold;">** {stats["missing_hydrogroup_count"]} soil polygons have missing or invalid hydrologic group values and were excluded from analysis.</div>'
        
        # Watershed Statistics (if provided)
        if watershed_stats is not None and not watershed_stats.empty:
            # Create CSV download
            csv_b64, csv_filename = create_csv_download_link(watershed_stats, "watershed_statistics.csv")
            
            # Header with download button
            html += '<div class="section-header">'
            html += '<h2 style="margin: 0; border: none; padding: 0;">Watershed Statistics (First 5 Rows)</h2>'
            
            if csv_b64:
                html += f'''
                <a href="data:text/csv;base64,{csv_b64}" 
                   download="{csv_filename}" class="download-button">
                   Download Complete CSV ({len(watershed_stats)} rows)
                </a>
                '''
            
            html += '</div>'
            
            # Show only first 5 rows
            display_stats = watershed_stats.head(5).copy()
            
            # Format the watershed stats table
            watershed_html = display_stats.to_html(
                index=False, 
                classes='watershed-table',
                table_id='watershed-stats',
                float_format=lambda x: '{:.2f}'.format(x) if pd.notna(x) else 'N/A'
            )
            html += watershed_html
            
            html += '<p><em>The table above shows the first 5 rows. Use the download button to get all watershed statistics.</em></p>'
        
        html += """
        </body>
        </html>
        """
        
        return html