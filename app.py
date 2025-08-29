"""
SCS Curve Number Generator - Gradio Interface
Web application for calculating SCS Curve Numbers with open-source tools
"""

import gradio as gr
import geopandas as gpd
import pandas as pd
import tempfile
import os
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
    use_parallel
):
    """Main processing function for Gradio interface."""
    
    start_time = time.time()
    
    try:
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
            use_parallel=use_parallel
        )
        
        # Load data
        print("Loading input data...")
        try:
            soil_gdf = gpd.read_file(soil_file.name)
        except Exception as e:
            return None, None, None, None, f"Error reading soil file: {str(e)}", ""
            
        try:
            landuse_gdf = gpd.read_file(landuse_file.name)
        except Exception as e:
            return None, None, None, None, f"Error reading land use file: {str(e)}", ""
        
        # Load lookup table
        if use_nlcd:
            lookup_df = calc.load_lookup_table(use_nlcd=True)
        else:
            if lookup_file is None:
                return None, None, None, None, "Please provide a lookup table or enable NLCD option", ""
            lookup_df = calc.load_lookup_table(lookup_path=lookup_file.name)
        
        # Preprocess data and track missing hydrogroup values
        print("Preprocessing data...")
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
        intersection_gdf = calc.compute_intersection(
            soil_gdf, landuse_gdf, hydgrp_field, code_field
        )
        
        # Assign curve numbers
        cn_gdf = calc.assign_curve_numbers(
            intersection_gdf, lookup_df, hydgrp_field, code_field
        )
        
        # Dissolve by CN
        dissolved_gdf = calc.dissolve_by_cn(cn_gdf)
        
        # Create raster - use a specific filename to avoid conflicts
        raster_filename = f"cn_raster_{os.getpid()}_{hash(str(dissolved_gdf.bounds.iloc[0]) if len(dissolved_gdf) > 0 else 'empty')}.tif"
        raster_path = os.path.join(tempfile.gettempdir(), raster_filename)
        
        raster_path = SpatialOperations.create_cn_raster(
            dissolved_gdf, cell_size, raster_path
        )
        
        # Calculate statistics
        global_stats = CNStatistics.calculate_global_stats(dissolved_gdf)
        # Add missing hydrogroup count to stats
        global_stats['missing_hydrogroup_count'] = missing_hydrogroup_count
        
        # Process watersheds if provided
        watershed_stats_df = None
        watershed_gdf = None
        excel_output = None
        if watershed_file is not None and watershed_field:
            try:
                watershed_gdf = gpd.read_file(watershed_file.name)
                watershed_stats_df = CNStatistics.calculate_zonal_statistics(
                    raster_path, watershed_gdf, watershed_field
                )
                # CSV download is handled in visualization.py
                excel_output = None
            except Exception as e:
                print(f"Warning: Could not process watershed file: {str(e)}")
        
        # Create visualizations - now returns HTML for leafmap
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
            dissolved_gdf.to_file(vector_path, driver='GPKG')
            print(f"Saved vector output to: {vector_path}")
        except Exception as e:
            print(f"Error saving vector file: {str(e)}")
            vector_path = None
        
        # Calculate total processing time
        end_time = time.time()
        processing_time = end_time - start_time
        time_display = f"Processing completed in {processing_time:.1f} seconds"
        
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
    body {font-family: Arial, sans-serif;}
    
    .map-container {
        height: 800px !important;
        overflow: hidden;
    }
    
    .coffee-button {
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 999;
        border-radius: 10px;
        transition: transform 0.2s;
    }
    
    .coffee-button:hover {
        transform: scale(1.05);
    }
    
    .coffee-button img {
        border-radius: 10px;
    }
    
    .developer-info {
        text-align: center;
        margin-top: 20px;
        padding: 15px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white !important;
        border-radius: 10px;
        border: none;
    }
    
    .developer-info a {
        color: #FFE701 !important;
        text-decoration: none;
        font-weight: bold;
    }
    
    .developer-info a:hover {
        text-decoration: underline;
    }
    
    .how-to-use {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 20px;
        border-radius: 10px;
        margin: 20px 0;
    }
    
    .how-to-use h3 {
        color: #FFE701;
        margin-top: 0;
        border-bottom: 2px solid #FFE701;
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
        background: rgba(255,231,1,0.2);
        border-radius: 8px;
        border: 1px solid #FFE701;
    }
    
    .processing-status {
        text-align: center;
        padding: 10px;
        margin: 10px 0;
        background: linear-gradient(135deg, #17a2b8, #138496);
        color: white;
        border-radius: 5px;
        font-weight: bold;
        font-size: 14px;
    }
    
    .processing-complete {
        background: linear-gradient(135deg, #28a745, #20c997);
    }
    
    .processing-error {
        background: linear-gradient(135deg, #dc3545, #c82333);
    }
    """
    
    with gr.Blocks(title="SCS Curve Number Generator", theme=gr.themes.Soft(), css=css) as demo:
        # Buy me a coffee button HTML with tooltip
        coffee_html = '''
        <div class="coffee-button">
            <a href="https://buymeacoffee.com/hydromohsen" target="_blank" 
               title="If you like the app and want to support the developer, consider clicking and buying Mohsen a coffee">
                <img src="https://cdn.buymeacoffee.com/buttons/v2/default-orange.png" 
                     alt="Buy Me A Coffee" 
                     style="height: 60px !important;width: 217px !important;">
            </a>
        </div>
        '''
        gr.HTML(coffee_html)
        
        gr.Markdown("""
        # 🟦🟥🟩🟨 SCS Curve Number Generator 🟦🟥🟩🟨 
        
        Calculate **SCS (Soil Conservation Service) Curve Numbers** for watershed runoff estimation using open-source geospatial tools.
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
                <strong>⚠️ Disclaimer:</strong><br>
                This app is provided as-is. The developer is not responsible for any claims or issues that may arise from its use. Please verify the results for accuracy before relying on them.
            </div>
        </div>
        ''')
        
        gr.Markdown("---")
        
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### Input Data")
                
                soil_file = gr.File(
                    label="Soil Shapefile Zip",
                    elem_id="soil_input"
                )
                
                landuse_file = gr.File(
                    label="Land Use Shapefile Zip", 
                    elem_id="landuse_input"
                )
                
                gr.Markdown("### Field Mapping")
                
                hydgrp_field = gr.Textbox(
                    label="Soil Hydrologic Group Field",
                    value="hydgrpdcd",
                    info="Field containing A, B, C, D soil groups (case sensitive)"
                )
                
                code_field = gr.Textbox(
                    label="Land Use Code Field",
                    value="gridcode",
                    info="Field containing numeric land use codes (case sensitive)"
                )
                
                gr.Markdown("### Lookup Table")
                
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
                
            with gr.Column(scale=1):
                gr.Markdown("### Processing Parameters")
                
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
                
                gr.Markdown("### Dual Hydrologic Group Replacements")
                
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
                
                gr.Markdown("### Watershed Analysis (Optional)")
                
                watershed_file = gr.File(
                    label="Watershed Boundaries (zip)",
                    elem_id="watershed_input"
                )
                
                watershed_field = gr.Textbox(
                    label="Watershed Name/ID Field",
                    placeholder="e.g., name, huc_id",
                    info="Field containing watershed identifiers (case sensitive)"
                )
                
                use_parallel = gr.Checkbox(
                    label="Use Parallel Processing",
                    value=True,
                    info="Speed up processing for large datasets"
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
        
        def update_outputs(*args):
            # Show processing status
            yield (
                gr.update(),  # vector_output
                gr.update(),  # raster_output  
                gr.update(),  # report_output
                gr.update(),  # map_output
                gr.update(),  # watershed_excel_output
                gr.update(value='<div class="processing-status">Processing... Please wait</div>', visible=True)  # status
            )
            
            # Run the actual processing
            results = process_curve_numbers(*args)
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
                watershed_file, watershed_field, use_parallel
            ],
            outputs=[
                vector_output, raster_output, report_output, map_output, watershed_excel_output, status_display
            ]
        )
        
        gr.Markdown("""
        ---
        ### 📘 About SCS Curve Numbers

        The SCS Curve Number method is a widely used approach to estimate direct runoff from rainfall events. It considers:

        - **🌱 Hydrologic Soil Groups (A-D)**: Soil infiltration capacity
        - **🌲 Land Use/Land Cover**: Surface conditions affecting runoff 
        - **💧 Antecedent Moisture**: Soil wetness before rainfall

        **CN Values**: Range from 30 (low runoff) to 100 (impervious surfaces)

        ### 📚 Helpful Resources

        **ArcGIS Pro Tutorial**  
        Learn how to calculate CN in ArcGIS Pro:
        - [Create Curve Number CN Raster Using ArcHydro Tools](https://www.hydromohsen.com/create-curve-number-cn-raster-for-a-watershed)

        ### 📝 References
        - [USDA Technical Release 55](https://www.nrcs.usda.gov/wps/portal/nrcs/detailfull/national/water/manage/hydrology/) - Official documentation
        - [National Land Cover Database](https://www.mrlc.gov/) - Land cover data
        - [HEC-HMS CN Grid Guide](https://www.hec.usace.army.mil/confluence/hmsdocs/hmsguides/gis-tools-and-terrain-data/gis-tutorials-and-guides/creating-a-curve-number-grid-and-computing-subbasin-average-curve-number-values) - Technical guide
        - [SSURGO Soil Data Downloader](https://www.arcgis.com/apps/View/index.html?appid=cdc49bd63ea54dd2977f3f2853e07fff) - Soil data source
        """)
        
        # Developer information
        gr.HTML('''
        <div class="developer-info">
            <h3>Developer Information</h3>
            <p><strong>Mohsen Tahmasebi Nasab, PhD</strong></p>
            <p>🌐 <a href="https://www.hydromohsen.com/" target="_blank">www.hydromohsen.com</a></p>
            <p>Water Resources Engineer</p>
        </div>
        ''')
    
    return demo

# Launch the app
if __name__ == "__main__":
    demo = create_interface()
    #demo.launch(server_name="127.0.0.1", server_port=7860, share=True, ssr_mode=False)
    demo.launch(share=True, ssr_mode=False)