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

class CNVisualization:
    """Create visualizations for Curve Number analysis."""
    
    @staticmethod
    def create_leafmap(cn_gdf: gpd.GeoDataFrame, 
                      cn_raster_path: str,
                      watershed_gdf: Optional[gpd.GeoDataFrame] = None) -> str:
        """
        Create interactive map using folium with CN polygons and watersheds.
        
        Parameters:
        -----------
        cn_gdf : GeoDataFrame
            GeoDataFrame with CN values
        cn_raster_path : str
            Path to CN raster file (for bounds reference)
        watershed_gdf : GeoDataFrame, optional
            Watershed boundaries
            
        Returns:
        --------
        str : HTML content for the map
        """
        # Calculate center point from CN data bounds
        bounds = cn_gdf.total_bounds
        center_lat = (bounds[1] + bounds[3]) / 2
        center_lon = (bounds[0] + bounds[2]) / 2
        
        # Create folium map with increased height
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=10,
            tiles='OpenStreetMap'
        )
        
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
        
        # Add CN polygons with color coding
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
        
        # Add CN polygons to map
        folium.GeoJson(
            cn_gdf,
            style_function=style_function,
            highlight_function=highlight_function,
            tooltip=folium.GeoJsonTooltip(
                fields=['CN', 'area_ha'],
                aliases=['Curve Number:', 'Area (ha):'],
                labels=True,
                sticky=True,
                style='background-color: white; color: #000000; font-family: arial; font-size: 12px; padding: 10px;'
            ),
            popup=folium.GeoJsonPopup(
                fields=['CN', 'area_ha'],
                aliases=['CN:', 'Area (ha):'],
                max_width=200
            )
        ).add_to(m)
        
        # Add watersheds as hollow polygons if provided
        if watershed_gdf is not None:
            # Ensure same CRS as CN data
            if watershed_gdf.crs != cn_gdf.crs:
                watershed_gdf = watershed_gdf.to_crs(cn_gdf.crs)
            
            def watershed_style(feature):
                return {
                    'color': '#000000',
                    'weight': 2,
                    'fillOpacity': 0,
                    'opacity': 1,
                    'dashArray': '5, 5'
                }
            
            folium.GeoJson(
                watershed_gdf,
                style_function=watershed_style
            ).add_to(m)
        
        # Add colormap legend to map
        colormap.add_to(m)
        
        # Runoff potential legend positioned for taller map
        legend_html = '''
        <div style="position: fixed; 
                    bottom: 60px; left: 10px; width: 200px; height: 160px; 
                    background-color: rgba(255, 255, 255, 0.95); 
                    border: 2px solid grey; z-index: 9999; 
                    font-size: 12px; padding: 10px; border-radius: 5px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.3);">
        <p style="margin: 0 0 10px 0; font-weight: bold; text-align: center; color: #333;">Runoff Potential</p>
        <p style="margin: 3px 0; color: #333;"><span style="color:#0000FF; font-size: 16px;">&#9632;</span> &lt; 40: Very Low</p>
        <p style="margin: 3px 0; color: #333;"><span style="color:#00CED1; font-size: 16px;">&#9632;</span> 40-60: Low-Moderate</p>
        <p style="margin: 3px 0; color: #333;"><span style="color:#FFD700; font-size: 16px;">&#9632;</span> 60-70: Moderate</p>
        <p style="margin: 3px 0; color: #333;"><span style="color:#FFA500; font-size: 16px;">&#9632;</span> 70-80: High</p>
        <p style="margin: 3px 0; color: #333;"><span style="color:#FF4500; font-size: 16px;">&#9632;</span> 80-90: Very High</p>
        <p style="margin: 3px 0; color: #333;"><span style="color:#8B0000; font-size: 16px;">&#9632;</span> &gt; 90: Extreme</p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        # Convert to HTML string and wrap with taller container
        map_html = m._repr_html_()
        
        # Wrap the map in a taller container (800px)
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
        </style>
        '''
        
        return wrapped_html
    
    @staticmethod
    def create_summary_report(cn_gdf: gpd.GeoDataFrame, 
                            stats: dict,
                            watershed_stats: Optional[pd.DataFrame] = None,
                            excel_path: Optional[str] = None) -> str:
        """
        Create HTML summary report with improved dark mode compatibility.
        
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
        
        # Global Statistics Section
        html += "<h2>Global Statistics</h2>"
        html += '<div class="stats-container">'
        for key, value in stats.items():
            if isinstance(value, (int, float)) and key != 'count':
                display_key = key.replace("_", " ").title()
                html += f'<div class="stat-box"><strong>{display_key}</strong><br>{value:.2f}</div>'
        html += "</div>"
        
        # Add footnote for weighted mean
        html += '<div class="footnote">* Weighted Mean is calculated using polygon areas as weights, providing a more representative average for the study area.</div>'
        
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