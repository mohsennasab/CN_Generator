"""
SCS Curve Number Generator - Gradio Interface
Web application for calculating SCS Curve Numbers with open-source tools
"""

import gradio as gr
import geopandas as gpd
import pandas as pd
import tempfile
import os
import base64
import socket
import sys
from pathlib import Path
from src.curve_number_calculator import CurveNumberCalculator
from src.spatial_operations import SpatialOperations
from src.cn_statistics import CNStatistics
from src.visualization import CNVisualization
import json
import zipfile
import shutil
import time

# Default configuration
DEFAULT_CRS = "EPSG:4326"
DEFAULT_CELL_SIZE = 10  # meters
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
LOGO_PATH = APP_DIR / "Logo" / "CN_Generator.png"
ICON_PATH = APP_DIR / "Logo" / "CN_Generator.ico"


def get_logo_data_uri():
    """Return the local app logo as an embeddable data URI."""
    if not LOGO_PATH.exists():
        return ""

    encoded_logo = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded_logo}"


def env_flag(name, default=False):
    """Parse a boolean flag from an environment variable."""
    value = os.environ.get(name)
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def find_available_port(preferred_port=7860, host="127.0.0.1"):
    """Use the preferred local port if available, otherwise pick the next open port."""
    for port in range(preferred_port, preferred_port + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            if sock.connect_ex((host, port)) != 0:
                return port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def update_progress(progress, value, message):
    """Update Gradio's progress display and mirror the message to the app log."""
    print(message)
    if progress is not None:
        progress(value, desc=message)


def get_column_options(file, preferred_names=None, fallback_value=None):
    """Read layer fields and update a field selector dropdown."""
    if file is None:
        choices = [fallback_value] if fallback_value else []
        return gr.update(choices=choices, value=fallback_value)

    preferred_names = {name.lower() for name in (preferred_names or [])}
    try:
        gdf = gpd.read_file(file.name)
        fields = [column for column in gdf.columns if column != "geometry"]
    except Exception:
        choices = [fallback_value] if fallback_value else []
        return gr.update(choices=choices, value=fallback_value)

    if not fields:
        choices = [fallback_value] if fallback_value else []
        return gr.update(choices=choices, value=fallback_value)

    default_field = next(
        (field for field in fields if field.lower() in preferred_names),
        fallback_value if fallback_value in fields else fields[0],
    )
    return gr.update(choices=fields, value=default_field)

def validate_shapefile_upload(file):
    """Validate that a shapefile upload contains required components."""
    if file is None:
        return False, "No file uploaded"
    
    try:
        # Check if it's a zip file containing shapefile components
        if file.name.endswith('.zip'):
            with zipfile.ZipFile(file.name, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                # Check for required shapefile components
                has_shp = any(f.endswith('.shp') for f in file_list)
                has_shx = any(f.endswith('.shx') for f in file_list)
                has_dbf = any(f.endswith('.dbf') for f in file_list)
                
                if has_shp and has_shx and has_dbf:
                    return True, "Valid shapefile archive"
                else:
                    missing = []
                    if not has_shp: missing.append('.shp')
                    if not has_shx: missing.append('.shx') 
                    if not has_dbf: missing.append('.dbf')
                    return False, f"Missing required shapefile components: {', '.join(missing)}"
        
        # For individual file uploads, provide guidance
        elif file.name.endswith(('.shp', '.gpkg', '.geojson')):
            if file.name.endswith('.shp'):
                return True, "Note: For shapefiles, ensure you also have .shx, .dbf, and .prj files. Consider uploading as a ZIP archive containing all components."
            else:
                return True, "Valid geospatial file format"
        
        # Try to read with geopandas to validate
        try:
            test_gdf = gpd.read_file(file.name)
            if len(test_gdf) > 0:
                return True, "Valid geospatial file"
            else:
                return False, "File appears to be empty"
        except:
            return False, "Unable to read as geospatial data"
            
    except Exception as e:
        return False, f"Error validating file: {str(e)}"

def process_curve_numbers(
    soil_file,
    landuse_file,
    hydgrp_field,
    code_field,
    lookup_file,
    use_nlcd,
    crs_epsg,
    cell_size,
    replacement_ad,
    replacement_bd,
    replacement_cd,
    watershed_file,
    watershed_field,
    progress=None
):
    """Main processing function for Gradio interface."""
    
    start_time = time.time()
    
    try:
        update_progress(progress, 0.03, "Validating uploaded files")
        # Validate inputs
        if soil_file is None:
            return None, None, None, None, "Please upload a soil shapefile", ""
        if landuse_file is None:
            return None, None, None, None, "Please upload a land use shapefile", ""
            
        # Validate shapefile uploads (only show warnings, don't block processing)
        soil_valid, soil_msg = validate_shapefile_upload(soil_file)
        landuse_valid, landuse_msg = validate_shapefile_upload(landuse_file)
        
        warning_messages = []
        if not soil_valid and "Missing required" in soil_msg:
            warning_messages.append(f"Soil file: {soil_msg}")
        if not landuse_valid and "Missing required" in landuse_msg:
            warning_messages.append(f"Land use file: {landuse_msg}")
            
        # Initialize calculator
        calc = CurveNumberCalculator(
            crs=f"EPSG:{crs_epsg}",
            use_parallel=True
        )
        
        # Load data
        update_progress(progress, 0.12, "Loading soil and land use layers")
        try:
            soil_gdf = gpd.read_file(soil_file.name)
        except Exception as e:
            return None, None, None, None, f"Error reading soil file: {str(e)}", ""
            
        try:
            landuse_gdf = gpd.read_file(landuse_file.name)
        except Exception as e:
            return None, None, None, None, f"Error reading land use file: {str(e)}", ""
        
        # Load lookup table
        update_progress(progress, 0.22, "Loading curve number lookup table")
        if use_nlcd:
            lookup_df = calc.load_lookup_table(use_nlcd=True)
        else:
            if lookup_file is None:
                return None, None, None, None, "Please provide a lookup table or enable NLCD option", ""
            lookup_df = calc.load_lookup_table(lookup_path=lookup_file.name)
        
        # Preprocess data and track missing hydrogroup values
        update_progress(progress, 0.32, "Preparing soil and land use attributes")
        replacements = {
            'A/D': replacement_ad,
            'B/D': replacement_bd,
            'C/D': replacement_cd
        }
        
        # Count missing hydrogroup values before preprocessing
        original_soil_gdf = soil_gdf.copy()
        valid_groups = ['A', 'B', 'C', 'D', 'A/D', 'B/D', 'C/D']
        missing_hydrogroup_count = (~original_soil_gdf[hydgrp_field].isin(valid_groups)).sum()
        
        soil_gdf = calc.preprocess_soil_data(soil_gdf, hydgrp_field, replacements)
        landuse_gdf = calc.preprocess_landuse_data(landuse_gdf, code_field)
        
        # Compute intersection
        update_progress(progress, 0.45, "Intersecting soil and land use polygons")
        intersection_gdf = calc.compute_intersection(
            soil_gdf, landuse_gdf, hydgrp_field, code_field
        )
        
        # Assign curve numbers
        update_progress(progress, 0.56, "Assigning curve numbers")
        cn_gdf = calc.assign_curve_numbers(
            intersection_gdf, lookup_df, hydgrp_field, code_field
        )
        
        # Dissolve by CN
        update_progress(progress, 0.64, "Dissolving polygons by curve number")
        dissolved_gdf = calc.dissolve_by_cn(cn_gdf)
        
        # Create raster - use a specific filename to avoid conflicts
        raster_filename = f"cn_raster_{os.getpid()}_{hash(str(dissolved_gdf.bounds.iloc[0]) if len(dissolved_gdf) > 0 else 'empty')}.tif"
        raster_path = os.path.join(tempfile.gettempdir(), raster_filename)
        
        update_progress(progress, 0.72, "Creating CN raster")
        raster_path = SpatialOperations.create_cn_raster(
            dissolved_gdf, cell_size, raster_path
        )
        
        # Calculate statistics
        update_progress(progress, 0.80, "Calculating summary statistics")
        global_stats = CNStatistics.calculate_global_stats(dissolved_gdf)
        # Add missing hydrogroup count to stats
        global_stats['missing_hydrogroup_count'] = missing_hydrogroup_count
        
        # Process watersheds if provided
        watershed_stats_df = None
        watershed_gdf = None
        excel_output = None
        if watershed_file is not None and watershed_field:
            try:
                update_progress(progress, 0.86, "Calculating watershed statistics")
                watershed_gdf = gpd.read_file(watershed_file.name)
                watershed_stats_df = CNStatistics.calculate_zonal_statistics(
                    raster_path, watershed_gdf, watershed_field
                )
                # CSV download is handled in visualization.py
                excel_output = None
            except Exception as e:
                print(f"Warning: Could not process watershed file: {str(e)}")
        
        # Create visualizations - now returns HTML for leafmap
        update_progress(progress, 0.92, "Building map and report")
        map_html = CNVisualization.create_leafmap(
            dissolved_gdf, raster_path, watershed_gdf, watershed_field, watershed_stats_df
        )
        
        # Create summary report
        report_html = CNVisualization.create_summary_report(
            dissolved_gdf, global_stats, watershed_stats_df, excel_output
        )
        
        # Save outputs - create unique filenames and ensure files are properly closed
        vector_filename = f"cn_polygons_{os.getpid()}_{hash(str(dissolved_gdf.bounds.iloc[0]) if len(dissolved_gdf) > 0 else 'empty')}.gpkg"
        vector_path = os.path.join(tempfile.gettempdir(), vector_filename)
        
        # Save the vector file and ensure it's closed properly
        try:
            update_progress(progress, 0.97, "Saving downloadable files")
            dissolved_gdf.to_file(vector_path, driver='GPKG')
            print(f"Saved vector output to: {vector_path}")
        except Exception as e:
            print(f"Error saving vector file: {str(e)}")
            vector_path = None
        
        # Calculate total processing time
        end_time = time.time()
        processing_time = end_time - start_time
        time_display = f"Processing completed in {processing_time:.1f} seconds"
        update_progress(progress, 1.0, "Processing complete")
        
        return vector_path, raster_path, report_html, map_html, excel_output, time_display
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        end_time = time.time()
        processing_time = end_time - start_time
        error_display = f"Error occurred after {processing_time:.1f} seconds: {str(e)}"
        return None, None, None, f"Error: {str(e)}", None, error_display

# Create Gradio interface
def create_interface():
    css = """
    body {
        font-family: "Segoe UI", Arial, sans-serif;
        background: var(--body-background-fill);
        color: var(--body-text-color);
    }

    .hero-card {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 20px;
        padding: 24px 22px;
        margin: 8px 0 18px 0;
        background: var(--block-background-fill);
        color: var(--body-text-color);
        border: 1px solid var(--border-color-primary);
        border-top: 4px solid var(--button-primary-background-fill, #2f766d);
        border-radius: 8px;
        box-shadow: var(--block-shadow);
        text-align: center;
    }

    .app-header {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        min-width: 0;
    }

    .app-logo {
        width: 78px;
        height: 78px;
        object-fit: contain;
        flex: 0 0 auto;
    }

    .app-title h1 {
        margin: 0 0 6px 0;
        font-size: 30px;
        line-height: 1.15;
        color: var(--body-text-color);
        letter-spacing: 0;
    }

    .app-title p {
        margin: 0;
        font-size: 15px;
        line-height: 1.45;
        color: var(--body-text-color-subdued, var(--body-text-color));
    }

    .developer-top {
        margin-top: 10px;
        font-size: 13px;
        color: var(--body-text-color-subdued, var(--body-text-color));
    }

    .developer-top strong {
        color: var(--body-text-color);
    }

    .developer-top a {
        color: var(--link-text-color, var(--body-text-color)) !important;
        text-decoration: none;
        font-weight: 600;
    }

    .hero-actions {
        display: flex;
        align-items: center;
        justify-content: center;
        flex: 0 0 auto;
    }

    .coffee-button {
        position: static;
        display: inline-flex;
        border-radius: 6px;
        transition: transform 0.15s ease;
    }

    .coffee-button:hover {
        transform: translateY(-1px);
    }

    .coffee-button img {
        height: 44px !important;
        width: 160px !important;
        border-radius: 6px;
    }

    @media (max-width: 640px) {
        .hero-card {
            padding: 16px;
        }

        .app-header {
            align-items: center;
            gap: 12px;
        }

        .app-logo {
            width: 64px;
            height: 64px;
        }

        .app-title h1 {
            font-size: 24px;
        }

        .hero-actions {
            width: 100%;
        }

        .coffee-button img {
            height: 40px !important;
            width: 146px !important;
        }
    }
    
    .map-container {
        height: 800px !important;
        overflow: hidden;
    }
    
    .developer-info {
        display: none;
    }
    
    .developer-info a {
        color: var(--link-text-color, var(--body-text-color)) !important;
        text-decoration: none;
        font-weight: bold;
    }
    
    .developer-info a:hover {
        text-decoration: underline;
    }
    
    .how-to-use {
        background: var(--block-background-fill);
        color: var(--body-text-color);
        padding: 20px;
        border-radius: 8px;
        border: 1px solid var(--border-color-primary);
        margin: 20px 0;
    }
    
    .how-to-use h3 {
        color: var(--body-text-color);
        margin-top: 0;
        border-bottom: 1px solid var(--border-color-primary);
        padding-bottom: 10px;
    }
    
    .how-to-use ul {
        padding-left: 20px;
    }
    
    .how-to-use li {
        margin-bottom: 8px;
        line-height: 1.4;
    }
    
    .disclaimer {
        margin-top: 15px;
        padding: 15px;
        background: var(--input-background-fill);
        color: var(--body-text-color);
        border-radius: 8px;
        border: 1px solid var(--border-color-primary);
        border-left: 4px solid var(--button-primary-background-fill, #2f766d);
    }
    
    .processing-status {
        text-align: center;
        padding: 12px;
        margin: 10px 0;
        background: var(--block-background-fill);
        color: var(--body-text-color);
        border: 1px solid var(--border-color-primary);
        border-radius: 8px;
        font-weight: bold;
        font-size: 14px;
    }
    
    .processing-complete {
        background: var(--block-background-fill);
        border-color: var(--button-primary-background-fill, var(--border-color-primary));
        color: var(--body-text-color);
    }
    
    .processing-error {
        background: var(--block-background-fill);
        border-color: var(--error-border-color, var(--border-color-primary));
        color: var(--body-text-color);
    }

    .workflow-row {
        align-items: stretch;
    }

    .workflow-column {
        display: flex;
        align-self: stretch;
        min-width: 0;
    }

    .workflow-card {
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        box-sizing: border-box;
        min-height: 720px;
        padding: 18px;
        background: var(--block-background-fill);
        color: var(--body-text-color);
        border: 1px solid var(--border-color-primary);
        border-radius: 8px;
        box-shadow: var(--block-shadow);
    }

    .workflow-card .gradio-group {
        border: none;
        padding: 0;
    }

    .workflow-heading {
        margin-bottom: 12px;
        padding-bottom: 12px;
        border-bottom: 1px solid var(--border-color-primary);
    }

    .workflow-heading .step-label {
        display: inline-block;
        margin-bottom: 8px;
        color: var(--body-text-color-subdued, var(--body-text-color));
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0;
        text-transform: uppercase;
    }

    .workflow-heading h3 {
        margin: 0 0 6px 0;
        color: var(--body-text-color);
        font-size: 20px;
        line-height: 1.25;
    }

    .workflow-heading p {
        margin: 0;
        color: var(--body-text-color-subdued, var(--body-text-color));
        font-size: 13px;
        line-height: 1.45;
    }

    .workflow-subhead {
        margin: 18px 0 8px 0;
        padding-top: 12px;
        border-top: 1px solid var(--border-color-primary);
        color: var(--body-text-color);
        font-size: 14px;
        font-weight: 700;
    }

    .workflow-hint {
        margin: 8px 0 14px 0;
        padding: 10px 12px;
        background: var(--input-background-fill);
        color: var(--body-text-color-subdued, var(--body-text-color));
        border: 1px solid var(--border-color-primary);
        border-left: 4px solid var(--button-primary-background-fill, #2f766d);
        border-radius: 8px;
        font-size: 13px;
        line-height: 1.45;
    }

    @media (max-width: 768px) {
        .workflow-card {
            min-height: 0;
        }
    }
    """
    
    with gr.Blocks(
        title="SCS Curve Number Generator",
        theme=gr.themes.Soft(primary_hue="teal", neutral_hue="gray"),
        css=css
    ) as demo:
        coffee_html = '''
        <a class="coffee-button" href="https://buymeacoffee.com/hydromohsen" target="_blank" 
           title="If you like the app and want to support the developer, consider clicking and buying Mohsen a coffee">
            <img src="https://cdn.buymeacoffee.com/buttons/v2/default-orange.png" 
                 alt="Buy Me A Coffee">
        </a>
        '''
        
        logo_data_uri = get_logo_data_uri()
        logo_html = (
            f'<img class="app-logo" src="{logo_data_uri}" alt="CN Generator logo">'
            if logo_data_uri
            else ""
        )
        gr.HTML(f"""
        <div class="hero-card">
            <div class="app-header">
                {logo_html}
                <div class="app-title">
                    <h1>SCS Curve Number Generator</h1>
                    <p>Calculate <strong>SCS Curve Numbers</strong> for watershed runoff estimation using open-source geospatial tools.</p>
                    <div class="developer-top">
                        <strong>Mohsen Tahmasebi Nasab, PhD</strong> | Water Resources Engineer |
                        <a href="https://www.hydromohsen.com/" target="_blank">hydromohsen.com</a>
                    </div>
                </div>
            </div>
            <div class="hero-actions">
                {coffee_html}
            </div>
        </div>
        """)
        
        # Add How to Use section directly in markdown
        gr.HTML('''
        <div class="how-to-use">
            <h3>How to Use</h3>
            <ol>
                <li><strong>Upload your soil and land use shapefiles</strong> (zip files)</li>
                <li><strong>Configure field mappings</strong> and parameters</li>
                <li><strong>Optionally add watershed boundaries</strong> for zonal statistics (zip file)</li>
                <li><strong>Click Calculate</strong> to generate curve numbers</li>
            </ol>
            
            <h3>Shapefile Upload Requirements</h3>
            <p>For shapefiles, ensure you upload ALL required components:</p>
            <ul>
                <li><code>.shp</code> (geometry)</li>
                <li><code>.shx</code> (index)</li>
                <li><code>.dbf</code> (attributes)</li>
                <li><code>.prj</code> (projection)</li>
            </ul>
            <p><strong>Tip:</strong> Upload shapefiles as a ZIP archive containing all components for best results</p>
            
            <div class="disclaimer">
                <strong>Disclaimer:</strong><br>
                This app is provided as-is. The developer is not responsible for any claims or issues that may arise from its use. Please verify the results for accuracy before relying on them.
            </div>
        </div>
        ''')
        
        gr.Markdown("---")
        
        with gr.Row(elem_classes=["workflow-row"]):
            with gr.Column(scale=1, elem_classes=["workflow-column"]):
                with gr.Group(elem_classes=["workflow-card"]):
                    gr.HTML("""
                    <div class="workflow-heading">
                        <span class="step-label">Step 1</span>
                        <h3>Input Data</h3>
                        <p>Upload the required soil and land use layers first. Field selectors update automatically after each upload.</p>
                    </div>
                    <div class="workflow-hint">
                        Start with ZIP shapefiles that include <code>.shp</code>, <code>.shx</code>, <code>.dbf</code>, and <code>.prj</code>, or upload GeoPackage/GeoJSON files.
                    </div>
                    """)
                
                    soil_file = gr.File(
                        label="1. Soil Layer",
                        elem_id="soil_input"
                    )
                    
                    landuse_file = gr.File(
                        label="2. Land Use Layer", 
                        elem_id="landuse_input"
                    )
                    
                    gr.HTML('<div class="workflow-subhead">Field Mapping</div>')
                    
                    hydgrp_field = gr.Dropdown(
                        label="Soil Hydrologic Group Field",
                        choices=["hydgrpdcd"],
                        value="hydgrpdcd",
                        allow_custom_value=True,
                        info="Select the soil attribute containing A, B, C, D soil groups."
                    )
                    
                    code_field = gr.Dropdown(
                        label="Land Use Code Field",
                        choices=["gridcode"],
                        value="gridcode",
                        allow_custom_value=True,
                        info="Select the land use attribute containing numeric land use codes."
                    )

                    soil_file.change(
                        fn=lambda file: get_column_options(
                            file,
                            preferred_names={"hydgrpdcd", "hydgrp", "hydgroup", "hydrologic_group", "soil_group"},
                            fallback_value="hydgrpdcd",
                        ),
                        inputs=[soil_file],
                        outputs=[hydgrp_field]
                    )

                    landuse_file.change(
                        fn=lambda file: get_column_options(
                            file,
                            preferred_names={"gridcode", "landuse", "land_use", "lucode", "lu_code", "nlcd", "code"},
                            fallback_value="gridcode",
                        ),
                        inputs=[landuse_file],
                        outputs=[code_field]
                    )
                    
                    gr.HTML('<div class="workflow-subhead">Curve Number Lookup</div>')
                    
                    use_nlcd = gr.Checkbox(
                        label="Use NLCD Lookup Table",
                        value=True,
                        info="Use built-in National Land Cover Database CN values. Uncheck to upload custom CSV lookup table."
                    )
                    
                    lookup_file = gr.File(
                        label="Custom Lookup Table (CSV)",
                        visible=False
                    )
                    
                    use_nlcd.change(
                        fn=lambda x: gr.update(visible=not x),
                        inputs=[use_nlcd],
                        outputs=[lookup_file]
                    )
                
            with gr.Column(scale=1, elem_classes=["workflow-column"]):
                with gr.Group(elem_classes=["workflow-card"]):
                    gr.HTML("""
                    <div class="workflow-heading">
                        <span class="step-label">Step 2</span>
                        <h3>Processing Parameters</h3>
                        <p>Confirm the coordinate system, raster resolution, dual soil-group handling, and optional watershed analysis.</p>
                    </div>
                    <div class="workflow-hint">
                        After required inputs are selected, review these defaults and then run the calculation below.
                    </div>
                    """)
                    
                    crs_epsg = gr.Number(
                        label="Coordinate System (EPSG Code)",
                        value=4326,
                        info="e.g., 4326 for WGS84, 3857 for Web Mercator"
                    )
                    
                    cell_size = gr.Number(
                        label="Raster Cell Size (map units)",
                        value=10,
                        info="Resolution for output raster"
                    )
                    
                    gr.HTML('<div class="workflow-subhead">Dual Hydrologic Group Replacements</div>')
                    
                    replacement_ad = gr.Dropdown(
                        label="Replace A/D with",
                        choices=["A", "B", "C", "D"],
                        value="D",
                        info="Replacement for dual group A/D soils"
                    )
                    
                    replacement_bd = gr.Dropdown(
                        label="Replace B/D with",
                        choices=["A", "B", "C", "D"],
                        value="D",
                        info="Replacement for dual group B/D soils"
                    )
                    
                    replacement_cd = gr.Dropdown(
                        label="Replace C/D with",
                        choices=["A", "B", "C", "D"],
                        value="D",
                        info="Replacement for dual group C/D soils"
                    )
                    
                    gr.HTML('<div class="workflow-subhead">Watershed Analysis (Optional)</div>')
                    
                    watershed_file = gr.File(
                        label="Watershed Boundaries",
                        elem_id="watershed_input"
                    )
                    
                    watershed_field = gr.Dropdown(
                        label="Watershed Name/ID Field",
                        choices=[],
                        value=None,
                        allow_custom_value=True,
                        info="Select the field that identifies each watershed. The list updates after upload."
                    )

                    watershed_file.change(
                        fn=lambda file: get_column_options(
                            file,
                            preferred_names={"name", "watershed", "watershed_id", "huc", "huc_id", "huc8", "id"},
                            fallback_value=None,
                        ),
                        inputs=[watershed_file],
                        outputs=[watershed_field]
                    )
        
        calculate_btn = gr.Button("Calculate Curve Numbers", variant="primary", size="lg")
        
        # Processing status display
        status_display = gr.HTML(visible=False, elem_classes="processing-status")
        
        gr.Markdown("---")
        gr.Markdown("### Outputs")
        
        with gr.Row():
            vector_output = gr.File(label="CN Polygons (GeoPackage)", visible=False)
            raster_output = gr.File(label="CN Raster (GeoTIFF)", visible=False)
            watershed_excel_output = gr.File(label="Watershed Statistics (Excel)", visible=False)
        
        # Report above map
        report_output = gr.HTML(label="Analysis Report", visible=False)
        
        # Map with increased height
        map_output = gr.HTML(label="Interactive Map", elem_classes="map-container", visible=False)
        
        def update_outputs(*args, progress=gr.Progress(track_tqdm=True)):
            # Show processing status
            yield (
                gr.update(),  # vector_output
                gr.update(),  # raster_output  
                gr.update(),  # report_output
                gr.update(),  # map_output
                gr.update(),  # watershed_excel_output
                gr.update(value='<div class="processing-status">Processing started. Progress details will appear above while the app runs.</div>', visible=True)  # status
            )
            
            # Run the actual processing
            results = process_curve_numbers(*args, progress=progress)
            vector_path, raster_path, report_html, map_html, excel_path, time_display = results
            
            # Show/hide Excel output based on whether watersheds were processed
            excel_visible = excel_path is not None
            
            # Determine status class based on results
            if vector_path is not None:
                status_class = "processing-status processing-complete"
            else:
                status_class = "processing-status processing-error"
            
            # Return final results
            yield (
                gr.update(value=vector_path, visible=True), 
                gr.update(value=raster_path, visible=True), 
                gr.update(value=report_html, visible=True), 
                gr.update(value=map_html, visible=True), 
                gr.update(value=excel_path, visible=excel_visible),
                gr.update(value=f'<div class="{status_class}">{time_display}</div>', visible=True)
            )
        
        calculate_btn.click(
            fn=update_outputs,
            inputs=[
                soil_file, landuse_file, hydgrp_field, code_field,
                lookup_file, use_nlcd, crs_epsg, cell_size,
                replacement_ad, replacement_bd, replacement_cd,
                watershed_file, watershed_field
            ],
            outputs=[
                vector_output, raster_output, report_output, map_output, watershed_excel_output, status_display
            ]
        )
        
        gr.Markdown("""
        ---
        ### About SCS Curve Numbers

        The SCS Curve Number method is a widely used approach to estimate direct runoff from rainfall events. It considers:

        - **Hydrologic Soil Groups (A-D)**: Soil infiltration capacity
        - **Land Use/Land Cover**: Surface conditions affecting runoff
        - **Antecedent Moisture**: Soil wetness before rainfall

        **CN Values**: Range from 30 (low runoff) to 100 (impervious surfaces)

        ### Helpful Resources

        **ArcGIS Pro Tutorial**  
        Learn how to calculate CN in ArcGIS Pro:
        - [Create Curve Number CN Raster Using ArcHydro Tools](https://www.hydromohsen.com/create-curve-number-cn-raster-for-a-watershed)

        ### References
        - [USDA Technical Release 55](https://www.nrcs.usda.gov/wps/portal/nrcs/detailfull/national/water/manage/hydrology/) - Official documentation
        - [National Land Cover Database](https://www.mrlc.gov/) - Land cover data
        - [HEC-HMS CN Grid Guide](https://www.hec.usace.army.mil/confluence/hmsdocs/hmsguides/gis-tools-and-terrain-data/gis-tutorials-and-guides/creating-a-curve-number-grid-and-computing-subbasin-average-curve-number-values) - Technical guide
        - [SSURGO Soil Data Downloader](https://www.arcgis.com/apps/View/index.html?appid=cdc49bd63ea54dd2977f3f2853e07fff) - Soil data source
        """)
    
    return demo

# Launch the app
if __name__ == "__main__":
    demo = create_interface()
    server_name = os.environ.get("CN_SERVER_NAME", "127.0.0.1")
    try:
        preferred_port = int(os.environ.get("CN_SERVER_PORT", "7860"))
    except ValueError:
        preferred_port = 7860
    port_check_host = "127.0.0.1" if server_name in {"0.0.0.0", "::"} else server_name
    server_port = (
        preferred_port
        if "CN_SERVER_PORT" in os.environ
        else find_available_port(preferred_port, port_check_host)
    )
    share = env_flag("CN_SHARE", default=False)
    open_browser = env_flag("CN_OPEN_BROWSER", default=True)
    favicon_path = str(ICON_PATH if ICON_PATH.exists() else LOGO_PATH) if LOGO_PATH.exists() else None

    print(f"Starting CN Generator locally at http://{server_name}:{server_port}")
    demo.launch(
        server_name=server_name,
        server_port=server_port,
        share=share,
        inbrowser=open_browser,
        favicon_path=favicon_path,
        ssr_mode=False,
    )
