"""
SCS Curve Number Generator - Gradio Interface
Web application for calculating SCS Curve Numbers with open-source tools
"""

import gradio as gr
import geopandas as gpd
import pandas as pd
import os
import base64
import socket
import sys
from pathlib import Path
from src.curve_number_calculator import CurveNumberCalculator
from src.spatial_operations import SpatialOperations
from src.cn_statistics import CNStatistics
from src.visualization import CNVisualization
from src import gcn10
import json
import zipfile
import time
from datetime import datetime

# Default configuration
DEFAULT_CRS = "EPSG:4326"
DEFAULT_CELL_SIZE = 30  # meters, matches the native NLCD land cover resolution
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
LOGO_PATH = APP_DIR / "Logo" / "CN_Generator.png"
ICON_PATH = APP_DIR / "Logo" / "CN_Generator.ico"


def get_app_base_dir():
    """Folder the app runs from: the exe folder when packaged, the source folder otherwise."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


RESULTS_ROOT = get_app_base_dir() / "Results"


class RunLogger:
    """Write timestamped run messages to a log file and mirror them to the console."""

    def __init__(self, log_path):
        self.log_path = Path(log_path)
        self.start_time = time.time()

    def log(self, message):
        elapsed = time.time() - self.start_time
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{stamp}] [+{elapsed:7.1f}s] {message}"
        print(line)
        try:
            with open(self.log_path, "a", encoding="utf-8") as log_file:
                log_file.write(line + "\n")
        except OSError:
            pass


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


def update_progress(progress, value, message, logger=None):
    """Update Gradio's progress display and mirror the message to the run log."""
    if logger is not None:
        logger.log(message)
    else:
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
        elif file.name.endswith(('.shp', '.gpkg', '.geojson', '.json')):
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

def build_result(vector_path=None, raster_path=None, report_html=None, map_html=None,
                 excel_output=None, gcn10_raster_path=None, gcn10_csv_path=None,
                 status_message=""):
    """Assemble the fixed-order result tuple returned to the interface."""
    return (vector_path, raster_path, report_html, map_html, excel_output,
            gcn10_raster_path, gcn10_csv_path, status_message)


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
    run_user_cn,
    use_gcn10,
    gcn10_hc,
    gcn10_arc,
    gcn10_drainage,
    progress=None
):
    """Main processing function for Gradio interface."""

    start_time = time.time()

    # Every run gets its own folder inside Results, next to the app
    run_stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = RESULTS_ROOT / f"Run_{run_stamp}"
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return build_result(status_message=(
            f"Could not create the results folder at {run_dir}: {e}"))

    logger = RunLogger(run_dir / f"model_run_log_{run_stamp}.txt")
    logger.log("CN Generator model run started")
    logger.log(f"Results folder: {run_dir}")

    try:
        update_progress(progress, 0.03, "Validating inputs", logger)
        logger.log(f"User CN workflow enabled: {run_user_cn}")
        logger.log(f"GCN10 workflow enabled: {use_gcn10}")

        if not run_user_cn and not use_gcn10:
            logger.log("Nothing to process: both workflows are disabled")
            return build_result(status_message=(
                "Nothing to process. Enable at least one workflow: generate CN "
                "from your own soil and land use data (tab 2), or include the "
                "GCN10 global dataset (tab 3)."))

        # Validate inputs for the user CN workflow
        if run_user_cn:
            if soil_file is None:
                logger.log("Run stopped: no soil layer uploaded")
                return build_result(status_message="Please upload a soil layer in tab 2")
            if landuse_file is None:
                logger.log("Run stopped: no land use layer uploaded")
                return build_result(status_message="Please upload a land use layer in tab 2")

            # Validate shapefile uploads (only show warnings, don't block processing)
            soil_valid, soil_msg = validate_shapefile_upload(soil_file)
            landuse_valid, landuse_msg = validate_shapefile_upload(landuse_file)

            warning_messages = []
            if not soil_valid and "Missing required" in soil_msg:
                warning_messages.append(f"Soil file: {soil_msg}")
            if not landuse_valid and "Missing required" in landuse_msg:
                warning_messages.append(f"Land use file: {landuse_msg}")

        if use_gcn10 and not run_user_cn and watershed_file is None:
            logger.log("Run stopped: GCN10-only run without a watershed boundary")
            return build_result(status_message=(
                "GCN10 needs a boundary to clip to. Upload a watershed boundary "
                "layer in the Input Data tab (tab 1), or also enable CN "
                "generation from your own data (tab 2)."))

        # Load the watershed layer once; both workflows can use it
        watershed_gdf = None
        if watershed_file is not None:
            try:
                logger.log(f"Reading watershed boundary layer: {watershed_file.name}")
                watershed_gdf = gpd.read_file(watershed_file.name)
                logger.log(f"Watershed layer loaded: {len(watershed_gdf)} polygons")
            except Exception as e:
                logger.log(f"ERROR reading watershed file: {str(e)}")
                return build_result(status_message=f"Error reading watershed file: {str(e)}")

        # ---------- User CN workflow ----------
        dissolved_gdf = None
        raster_path = None
        vector_path = None
        global_stats = None
        watershed_stats_df = None
        excel_output = None

        if run_user_cn:
            # Initialize calculator
            calc = CurveNumberCalculator(
                crs=f"EPSG:{crs_epsg}",
                use_parallel=True
            )

            # Load data
            update_progress(progress, 0.10, "Loading soil and land use layers", logger)
            try:
                logger.log(f"Reading soil layer: {soil_file.name}")
                soil_gdf = gpd.read_file(soil_file.name)
                logger.log(f"Soil layer loaded: {len(soil_gdf)} polygons")
            except Exception as e:
                logger.log(f"ERROR reading soil file: {str(e)}")
                return build_result(status_message=f"Error reading soil file: {str(e)}")

            try:
                logger.log(f"Reading land use layer: {landuse_file.name}")
                landuse_gdf = gpd.read_file(landuse_file.name)
                logger.log(f"Land use layer loaded: {len(landuse_gdf)} polygons")
            except Exception as e:
                logger.log(f"ERROR reading land use file: {str(e)}")
                return build_result(status_message=f"Error reading land use file: {str(e)}")

            # Load lookup table
            update_progress(progress, 0.18, "Loading curve number lookup table", logger)
            if use_nlcd:
                lookup_df = calc.load_lookup_table(use_nlcd=True)
            else:
                if lookup_file is None:
                    logger.log("Run stopped: no lookup table provided")
                    return build_result(status_message="Please provide a lookup table or enable NLCD option")
                lookup_df = calc.load_lookup_table(lookup_path=lookup_file.name)

            # Preprocess data and track missing hydrogroup values
            update_progress(progress, 0.26, "Preparing soil and land use attributes", logger)
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
            update_progress(progress, 0.36, "Intersecting soil and land use polygons", logger)
            intersection_gdf = calc.compute_intersection(
                soil_gdf, landuse_gdf, hydgrp_field, code_field
            )

            # Assign curve numbers
            update_progress(progress, 0.46, "Assigning curve numbers", logger)
            cn_gdf = calc.assign_curve_numbers(
                intersection_gdf, lookup_df, hydgrp_field, code_field
            )

            # Dissolve by CN
            update_progress(progress, 0.52, "Dissolving polygons by curve number", logger)
            dissolved_gdf = calc.dissolve_by_cn(cn_gdf)

            # Create raster in this run's results folder
            raster_path = str(run_dir / "cn_raster.tif")

            update_progress(progress, 0.58, "Creating CN raster", logger)
            raster_path = SpatialOperations.create_cn_raster(
                dissolved_gdf, cell_size, raster_path
            )
            logger.log(f"CN raster saved: {raster_path}")

            # Calculate statistics
            update_progress(progress, 0.64, "Calculating summary statistics", logger)
            global_stats = CNStatistics.calculate_global_stats(dissolved_gdf)
            # Add missing hydrogroup count to stats
            global_stats['missing_hydrogroup_count'] = missing_hydrogroup_count

            # Process watersheds if provided
            if watershed_gdf is not None and watershed_field:
                try:
                    update_progress(progress, 0.68, "Calculating watershed statistics", logger)
                    watershed_stats_df = CNStatistics.calculate_zonal_statistics(
                        raster_path, watershed_gdf, watershed_field
                    )
                    # Save the per-watershed table with the other results
                    excel_output = str(run_dir / "watershed_statistics.csv")
                    watershed_stats_df.to_csv(excel_output, index=False)
                    logger.log(f"Watershed statistics saved: {excel_output}")
                except Exception as e:
                    logger.log(f"Warning: Could not process watershed file: {str(e)}")

        # ---------- GCN10 workflow ----------
        gcn10_info = None
        gcn10_raster_path = None
        gcn10_csv_path = None
        gcn10_watershed_stats = None
        comparison_df = None
        gcn10_label = None

        if use_gcn10:
            # Clip to the watershed when available, otherwise to the CN polygons
            gcn10_aoi = watershed_gdf if watershed_gdf is not None else dissolved_gdf
            if gcn10_aoi is None or len(gcn10_aoi) == 0:
                logger.log("Run stopped: GCN10 had no boundary to clip to")
                return build_result(status_message=(
                    "GCN10 needs a boundary to clip to, but no watershed layer or "
                    "generated CN polygons were available."))

            update_progress(progress, 0.72, "Reading GCN10 data from the online dataset", logger)

            def gcn10_progress(done, total):
                fraction = 0.72 + 0.10 * (done / max(total, 1))
                update_progress(progress, fraction, f"Reading GCN10 tile {done} of {total}", logger)

            gcn10_slug = gcn10.variant_slug(gcn10_hc, gcn10_arc, gcn10_drainage)
            gcn10_out_path = str(run_dir / f"{gcn10_slug}.tif")
            gcn10_info = gcn10.fetch_gcn10_raster(
                gcn10_aoi, gcn10_hc, gcn10_arc, gcn10_drainage,
                gcn10_out_path, progress_callback=gcn10_progress,
                message_callback=logger.log
            )
            gcn10_raster_path = gcn10_info["path"]
            gcn10_label = gcn10_info["label"]
            logger.log(f"GCN10 raster saved: {gcn10_raster_path}")

            # GCN10 zonal statistics per watershed on its native grid
            if watershed_gdf is not None and watershed_field:
                try:
                    update_progress(progress, 0.84, "Calculating GCN10 watershed statistics", logger)
                    gcn10_watershed_stats = CNStatistics.calculate_zonal_statistics(
                        gcn10_raster_path, watershed_gdf, watershed_field,
                        nodata=gcn10.GCN10_NODATA
                    )
                    gcn10_csv_path = str(run_dir / f"{gcn10_slug}_watershed_statistics.csv")
                    gcn10_watershed_stats.to_csv(gcn10_csv_path, index=False)
                    logger.log(f"GCN10 watershed statistics saved: {gcn10_csv_path}")
                except Exception as e:
                    logger.log(f"Warning: Could not compute GCN10 watershed statistics: {str(e)}")

            # Comparison table when both sources were processed
            if watershed_stats_df is not None and gcn10_watershed_stats is not None:
                comparison_df = CNStatistics.build_comparison_table(
                    watershed_stats_df, gcn10_watershed_stats, watershed_field
                )

        # ---------- Map and report ----------
        update_progress(progress, 0.90, "Building map and report", logger)

        map_html = CNVisualization.create_leafmap(
            dissolved_gdf, raster_path, watershed_gdf, watershed_field,
            watershed_stats_df,
            gcn10_raster_path=gcn10_raster_path,
            gcn10_label=gcn10_label,
            gcn10_watershed_stats=gcn10_watershed_stats,
        )

        # Create summary report
        report_html = CNVisualization.create_summary_report(
            dissolved_gdf, global_stats, watershed_stats_df, excel_output,
            gcn10_info=gcn10_info,
            gcn10_watershed_stats=gcn10_watershed_stats,
            comparison_stats=comparison_df,
            watershed_field=watershed_field,
        )

        # The summary report is shown in the app only; it is not saved to disk

        # Save the CN polygons in the run's results folder
        if dissolved_gdf is not None:
            vector_path = str(run_dir / "cn_polygons.gpkg")
            try:
                update_progress(progress, 0.97, "Saving downloadable files", logger)
                dissolved_gdf.to_file(vector_path, driver='GPKG')
                logger.log(f"CN polygons saved: {vector_path}")
            except Exception as e:
                logger.log(f"Error saving vector file: {str(e)}")
                vector_path = None

        # Calculate total processing time
        end_time = time.time()
        processing_time = end_time - start_time
        time_display = (
            f"Processing completed in {processing_time:.1f} seconds. "
            f"Results saved to: {run_dir}"
        )
        update_progress(progress, 1.0, "Processing complete", logger)
        logger.log(f"Model run finished in {processing_time:.1f} seconds")
        logger.log(f"All results saved to: {run_dir}")

        return build_result(
            vector_path=vector_path,
            raster_path=raster_path,
            report_html=report_html,
            map_html=map_html,
            excel_output=excel_output,
            gcn10_raster_path=gcn10_raster_path,
            gcn10_csv_path=gcn10_csv_path,
            status_message=time_display,
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        end_time = time.time()
        processing_time = end_time - start_time
        logger.log(f"ERROR after {processing_time:.1f} seconds: {str(e)}")
        logger.log(traceback.format_exc())
        error_display = (
            f"Error occurred after {processing_time:.1f} seconds: {str(e)}. "
            f"See the run log in: {run_dir}"
        )
        return build_result(status_message=error_display)

# Create Gradio interface
def create_interface():
    css = """
    body {
        font-family: Arial, Helvetica, sans-serif;
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
    }

    .map-container {
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

    .workflow-subhead {
        margin: 14px 0 6px 0;
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

    .tip-line {
        margin: 2px 0 10px 0;
        font-size: 13px;
        font-style: italic;
        color: var(--body-text-color-subdued, var(--body-text-color));
    }

    /* Compact upload boxes: smaller drop zone that fits the single-column layout */
    .compact-upload {
        max-width: 560px;
        margin-left: 0 !important;
        margin-right: auto !important;
    }

    .compact-upload button.center {
        min-height: 0 !important;
        padding: 30px 12px 10px !important;
        font-size: 13px;
        align-items: flex-start !important;
        text-align: left !important;
    }

    .compact-upload button.center .wrap {
        min-height: 0 !important;
        font-size: 13px;
        align-items: flex-start !important;
        text-align: left !important;
    }

    .compact-upload button.center:hover {
        border-color: var(--button-primary-background-fill, #2f766d);
        background: var(--input-background-fill);
    }

    .compact-upload .icon-wrap {
        width: 24px !important;
        height: 24px !important;
        margin-bottom: 0 !important;
    }

    .next-row {
        margin-top: 18px;
        display: flex;
        justify-content: flex-end;
    }

    .next-row button {
        max-width: 320px;
    }

    /* Tab styling: clear progression, no wasted vertical space */
    .workflow-tabs .tab-nav button,
    .workflow-tabs button[role="tab"] {
        font-weight: 600;
        font-size: 15px;
    }

    .workflow-tabs .tabitem {
        padding: 16px 14px;
        border: 1px solid var(--border-color-primary);
        border-top: none;
        border-radius: 0 0 8px 8px;
        background: var(--block-background-fill);
    }

    """
    
    with gr.Blocks(
        title="SCS Curve Number Generator",
        theme=gr.themes.Soft(
            primary_hue="teal",
            neutral_hue="gray",
            font=["Arial", "Helvetica", "sans-serif"],
        ),
        css=css
    ) as demo:
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
        </div>
        """)
        
        # Tabbed workflow: numbered tabs make the progression clear
        with gr.Tabs(elem_classes=["workflow-tabs"]) as workflow_tabs:
            with gr.Tab("How to Use", id="howto") as tab_howto:
                gr.HTML('''
                <div class="how-to-use">
                    <h3>How to Use</h3>
                    <ol>
                        <li><strong>Input Data:</strong> upload your watershed or subbasin boundaries. This single layer is shared by both workflows below: per-basin statistics for your own CN results and the clipping boundary for GCN10</li>
                        <li><strong>CN from Soil &amp; Land Use (optional):</strong> upload your soil and land use layers, check the field mappings, and set the processing parameters (coordinate system, cell size, dual soil-group handling)</li>
                        <li><strong>GCN10 Global Dataset (optional):</strong> add the global 10 m Curve Number dataset to view, download, and compare. It is on by default and needs internet; turn it off in tab 3 to run fully offline</li>
                        <li><strong>Run &amp; Results:</strong> click Calculate Curve Numbers and review the report, map, and downloads. All output files are also saved to a Results folder next to the app, along with a model run log</li>
                    </ol>
                    <p>Steps 2 and 3 are independent: run either one alone or both together to compare them. Enable at least one before calculating. Running GCN10 alone requires the watershed boundary from step 1.</p>

                    <h3>Supported Upload Formats</h3>
                    <p>Every layer upload accepts a ZIP shapefile archive, a GeoPackage (<code>.gpkg</code>), or a GeoJSON (<code>.geojson</code>/<code>.json</code>) file.</p>
                    <p>For shapefiles, the ZIP archive must include ALL required components:</p>
                    <ul>
                        <li><code>.shp</code> (geometry)</li>
                        <li><code>.shx</code> (index)</li>
                        <li><code>.dbf</code> (attributes)</li>
                        <li><code>.prj</code> (projection)</li>
                    </ul>

                    <div class="disclaimer">
                        <strong>Disclaimer:</strong><br>
                        This app is provided as-is. The developer is not responsible for any claims or issues that may arise from its use. Please verify the results for accuracy before relying on them.
                    </div>
                </div>
                ''')

            with gr.Tab("1. Input Data", id="inputs") as tab_inputs:
                gr.HTML("""
                <div class="workflow-hint">
                    Upload your watershed or subbasin boundaries here. This is the one shared input for
                    both optional workflows: it provides per-basin CN statistics for your own soil and
                    land use data (tab 2) and the clipping boundary for the GCN10 global dataset (tab 3).
                    Accepted formats: ZIP shapefile archive (<code>.shp</code>, <code>.shx</code>,
                    <code>.dbf</code>, <code>.prj</code>), GeoPackage (<code>.gpkg</code>), or GeoJSON
                    (<code>.geojson</code>/<code>.json</code>).
                </div>
                """)

                gr.HTML('<div class="workflow-subhead">1. Watershed / Subbasin Boundaries</div>')
                gr.HTML('<div class="tip-line">Tip: this can be a single polygon for the whole watershed, or one layer with multiple polygons covering many subbasins.</div>')

                watershed_file = gr.File(
                    label="Watershed Boundaries (ZIP shapefile, GeoPackage, or GeoJSON)",
                    file_types=[".zip", ".gpkg", ".geojson", ".json"],
                    elem_id="watershed_input",
                    elem_classes=["compact-upload"],
                    height=150,
                )

                gr.HTML('<div class="workflow-subhead">2. Boundary Attributes</div>')

                watershed_field = gr.Dropdown(
                    label="Watershed Name/ID Field",
                    choices=[],
                    value=None,
                    allow_custom_value=True,
                    info="Select the field that identifies each watershed or subbasin. The list updates after upload."
                )

                with gr.Row(elem_classes=["next-row"]):
                    next_btn_inputs = gr.Button("Next: CN from Soil & Land Use", variant="secondary")

                watershed_file.change(
                    fn=lambda file: get_column_options(
                        file,
                        preferred_names={"name", "watershed", "watershed_id", "huc", "huc_id", "huc8", "id"},
                        fallback_value=None,
                    ),
                    inputs=[watershed_file],
                    outputs=[watershed_field]
                )

            with gr.Tab("2. CN from Soil & Land Use (Optional)", id="usercn") as tab_usercn:
                gr.HTML("""
                <div class="workflow-hint">
                    Generate Curve Numbers from your own soil and land use layers. This workflow is
                    optional and independent of GCN10 (tab 3): enable either one or both.
                </div>
                """)

                run_user_cn = gr.Checkbox(
                    label="Generate CN from my soil and land use data",
                    value=True,
                    info="Uncheck to skip this workflow, e.g. to run only the GCN10 global dataset (tab 3). GCN10-only runs need the watershed boundary from tab 1."
                )

                with gr.Group(visible=True) as user_cn_options:
                    gr.HTML('<div class="workflow-subhead">1. Data Layers</div>')
                    gr.HTML('<div class="tip-line">Upload ZIP shapefiles that include .shp, .shx, .dbf, and .prj, or GeoPackage/GeoJSON files. Field selectors update automatically after each upload.</div>')

                    soil_file = gr.File(
                        label="Soil Layer",
                        file_types=[".zip", ".gpkg", ".geojson", ".json"],
                        elem_id="soil_input",
                        elem_classes=["compact-upload"],
                        height=150,
                    )

                    landuse_file = gr.File(
                        label="Land Use Layer",
                        file_types=[".zip", ".gpkg", ".geojson", ".json"],
                        elem_id="landuse_input",
                        elem_classes=["compact-upload"],
                        height=150,
                    )

                    gr.HTML('<div class="workflow-subhead">2. Field Mapping</div>')

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

                    gr.HTML('<div class="workflow-subhead">3. Curve Number Lookup</div>')

                    use_nlcd = gr.Checkbox(
                        label="Use NLCD Lookup Table",
                        value=True,
                        info="Use built-in National Land Cover Database CN values. Uncheck to upload custom CSV lookup table."
                    )

                    lookup_file = gr.File(
                        label="Custom Lookup Table (CSV)",
                        visible=False,
                        elem_classes=["compact-upload"],
                        height=150,
                    )

                    gr.HTML('<div class="workflow-subhead">4. Raster Settings</div>')

                    crs_epsg = gr.Number(
                        label="Coordinate System (EPSG Code)",
                        value=4326,
                        info="e.g., 4326 for WGS84, 3857 for Web Mercator"
                    )

                    cell_size = gr.Number(
                        label="Raster Cell Size (meters)",
                        value=30,
                        info="Output raster resolution. The default of 30 meters matches the native resolution of NLCD land cover. For EPSG:4326 the value is converted to degrees automatically; for other coordinate systems it is used directly in their map units."
                    )

                    gr.HTML('<div class="workflow-subhead">5. Dual Hydrologic Group Replacements</div>')

                    with gr.Row():
                        replacement_ad = gr.Dropdown(
                            label="Replace A/D with",
                            choices=["A", "B", "C", "D"],
                            value="D",
                            info="For dual group A/D soils"
                        )

                        replacement_bd = gr.Dropdown(
                            label="Replace B/D with",
                            choices=["A", "B", "C", "D"],
                            value="D",
                            info="For dual group B/D soils"
                        )

                        replacement_cd = gr.Dropdown(
                            label="Replace C/D with",
                            choices=["A", "B", "C", "D"],
                            value="D",
                            info="For dual group C/D soils"
                        )

                with gr.Row(elem_classes=["next-row"]):
                    next_btn_usercn = gr.Button("Next: GCN10 Global Dataset", variant="secondary")

                run_user_cn.change(
                    fn=lambda enabled: gr.update(visible=enabled),
                    inputs=[run_user_cn],
                    outputs=[user_cn_options]
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

                use_nlcd.change(
                    fn=lambda x: gr.update(visible=not x),
                    inputs=[use_nlcd],
                    outputs=[lookup_file]
                )

            with gr.Tab("3. GCN10 Global Dataset (Optional)", id="gcn10") as tab_gcn10:
                gr.HTML("""
                <div class="workflow-hint">
                    GCN10 is a global 10 m Curve Number dataset by Azzam and Cho (2026), built from ESA WorldCover 2021 land cover and HYSOGs250m soil groups. Enable it to view the GCN10 raster on the map, download it for your watershed, and compare it with your own results. It is clipped to the watershed boundary uploaded in tab 1 (or, if none is uploaded, to the CN polygons generated in tab 2). This workflow is independent of tab 2: enable either one or both. The app streams only the data covering your area, so a typical run adds a few seconds. Needs an internet connection during processing.
                </div>
                """)

                use_gcn10 = gr.Checkbox(
                    label="Include GCN10 global Curve Number data",
                    value=True,
                    info="On by default. Turn it off if you are offline or do not need the global dataset."
                )

                with gr.Group(visible=True) as gcn10_options:
                    with gr.Row():
                        gcn10_hc = gr.Dropdown(
                            label="Hydrologic Condition",
                            choices=list(gcn10.HYDROLOGIC_CONDITIONS.keys()),
                            value="Fair",
                            info="Vegetative cover condition assumed in the GCN10 lookup"
                        )

                        gcn10_arc = gr.Dropdown(
                            label="Antecedent Runoff Condition",
                            choices=list(gcn10.ARC_CONDITIONS.keys()),
                            value="ARC II",
                            info="ARC II is the standard average condition"
                        )

                        gcn10_drainage = gr.Dropdown(
                            label="Dual Soil Group Drainage",
                            choices=list(gcn10.DRAINAGE_CONDITIONS.keys()),
                            value="Undrained",
                            info="How GCN10 interprets dual groups such as A/D: Drained uses the first letter, Undrained uses D"
                        )

                gr.HTML(f"""
                <div style="font-size: 12px; margin-top: 10px; color: var(--body-text-color-subdued, #666);">
                    Data credit: <a href="{gcn10.GCN10_DATASET_URL}" target="_blank">{gcn10.GCN10_ATTRIBUTION}</a>, ODbL v1.0 license.
                </div>
                """)

                with gr.Row(elem_classes=["next-row"]):
                    next_btn_gcn10 = gr.Button("Next: Run & Results", variant="secondary")

                use_gcn10.change(
                    fn=lambda enabled: gr.update(visible=enabled),
                    inputs=[use_gcn10],
                    outputs=[gcn10_options]
                )

            with gr.Tab("4. Run & Results", id="results") as tab_results:
                gr.HTML("""
                <div class="workflow-hint">
                    Set up tabs 1 to 3, then click Calculate Curve Numbers below. The report, map, and download files appear here when processing finishes, and every output is also saved to a Results folder next to the app.
                </div>
                """)

                calculate_btn = gr.Button(
                    "Calculate Curve Numbers",
                    variant="primary",
                    size="lg",
                )

                # Processing status display
                status_display = gr.HTML(visible=False, elem_classes="processing-status")

                with gr.Row():
                    vector_output = gr.File(label="CN Polygons (GeoPackage)", visible=False)
                    raster_output = gr.File(label="CN Raster (GeoTIFF)", visible=False)
                    watershed_excel_output = gr.File(label="Watershed Statistics (CSV)", visible=False)
                    gcn10_raster_output = gr.File(label="GCN10 Raster (GeoTIFF)", visible=False)
                    gcn10_csv_output = gr.File(label="GCN10 Watershed Statistics (CSV)", visible=False)

                # Report above map
                report_output = gr.HTML(label="Analysis Report", visible=False)

                # Map with increased height
                map_output = gr.HTML(label="Interactive Map", elem_classes="map-container", visible=False)

            with gr.Tab("About & References", id="about") as tab_about:
                gr.Markdown("""
                ### About SCS Curve Numbers

                The SCS Curve Number method is a widely used approach to estimate direct runoff from rainfall events. It considers:

                - **Hydrologic Soil Groups (A-D)**: Soil infiltration capacity
                - **Land Use/Land Cover**: Surface conditions affecting runoff
                - **Antecedent Moisture**: Soil wetness before rainfall

                **CN Values**: Range from 30 (low runoff) to 100 (impervious surfaces)

                ### About the GCN10 Dataset

                The optional GCN10 layer comes from the Global Curve Number 10m dataset by Muhammad Abdullah Azzam and Huidae Cho
                (New Mexico State University). It combines ESA WorldCover 2021 land cover with HYSOGs250m hydrologic soil groups
                to produce global 10 m Curve Number rasters for multiple hydrologic conditions, antecedent runoff conditions, and
                drainage assumptions. The data is distributed under the Open Data Commons Open Database License (ODbL) v1.0.

                - Dataset: [GCN10 -- Global 10 m Curve Number Dataset (Azzam et al.)](https://hydro.nmsu.edu/datasets/gcn10/)
                - Citation: Azzam, M. A., Cho, H., 2026. GCN10: An MPI-parallelized framework for processing global curve number
                  rasters for hydrologic modeling. SoftwareX 34, 102725. [doi:10.1016/j.softx.2026.102725](https://doi.org/10.1016/j.softx.2026.102725)
                - Software: [github.com/clawrim/gcn10](https://github.com/clawrim/gcn10)

                ### Helpful Resources

                **ArcGIS Pro Tutorial**
                Learn how to calculate CN in ArcGIS Pro:
                - [Create Curve Number CN Raster Using ArcHydro Tools](https://www.hydromohsen.com/create-curve-number-cn-raster-for-a-watershed)

                ### References
                - [USDA Technical Release 55](https://www.hydrocad.net/pdf/TR-55%20Manual.pdf) - Official documentation
                - [National Land Cover Database](https://www.mrlc.gov/) - Land cover data
                - [HEC-HMS CN Grid Guide](https://www.hec.usace.army.mil/confluence/hmsdocs/hmsguides/gis-tools-and-terrain-data/gis-tutorials-and-guides/creating-a-curve-number-grid-and-computing-subbasin-average-curve-number-values) - Technical guide
                - [SSURGO Soil Data Downloader](https://www.arcgis.com/apps/View/index.html?appid=cdc49bd63ea54dd2977f3f2853e07fff) - Soil data source
                """)

        # Next buttons walk the user through the setup tabs in order
        next_btn_inputs.click(
            fn=lambda: gr.Tabs(selected="usercn"),
            outputs=[workflow_tabs],
        )
        next_btn_usercn.click(
            fn=lambda: gr.Tabs(selected="gcn10"),
            outputs=[workflow_tabs],
        )
        next_btn_gcn10.click(
            fn=lambda: gr.Tabs(selected="results"),
            outputs=[workflow_tabs],
        )

        def update_outputs(*args, progress=gr.Progress(track_tqdm=True)):
            # Jump to the Results tab and show the processing status
            yield (
                gr.update(),  # vector_output
                gr.update(),  # raster_output
                gr.update(),  # report_output
                gr.update(),  # map_output
                gr.update(),  # watershed_excel_output
                gr.update(),  # gcn10_raster_output
                gr.update(),  # gcn10_csv_output
                gr.update(value='<div class="processing-status">Processing started. Progress details will appear at the top right while the app runs.</div>', visible=True),  # status
                gr.Tabs(selected="results"),  # switch to the Results tab
            )

            # Run the actual processing
            results = process_curve_numbers(*args, progress=progress)
            (vector_path, raster_path, report_html, map_html, excel_path,
             gcn10_raster_path, gcn10_csv_path, time_display) = results

            # Anything produced this run gets shown; the rest stays hidden
            succeeded = vector_path is not None or gcn10_raster_path is not None
            status_class = "processing-status processing-complete" if succeeded else "processing-status processing-error"

            # Return final results
            yield (
                gr.update(value=vector_path, visible=vector_path is not None),
                gr.update(value=raster_path, visible=raster_path is not None),
                gr.update(value=report_html, visible=report_html is not None),
                gr.update(value=map_html, visible=map_html is not None),
                gr.update(value=excel_path, visible=excel_path is not None),
                gr.update(value=gcn10_raster_path, visible=gcn10_raster_path is not None),
                gr.update(value=gcn10_csv_path, visible=gcn10_csv_path is not None),
                gr.update(value=f'<div class="{status_class}">{time_display}</div>', visible=True),
                gr.update(),  # keep the current tab selection
            )

        calculate_btn.click(
            fn=update_outputs,
            inputs=[
                soil_file, landuse_file, hydgrp_field, code_field,
                lookup_file, use_nlcd, crs_epsg, cell_size,
                replacement_ad, replacement_bd, replacement_cd,
                watershed_file, watershed_field,
                run_user_cn, use_gcn10, gcn10_hc, gcn10_arc, gcn10_drainage
            ],
            outputs=[
                vector_output, raster_output, report_output, map_output,
                watershed_excel_output, gcn10_raster_output, gcn10_csv_output,
                status_display, workflow_tabs
            ]
        )
    
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
