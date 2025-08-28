---
title: SCS Curve Number Generator
emoji: 🌧️
colorFrom: indigo
colorTo: green
sdk: gradio
sdk_version: 4.0.0
python_version: 3.10
app_file: app.py
pinned: false
---

# SCS Curve Number Generator

A simple, open-source tool for creating SCS Curve Number (CN) maps and summary statistics from **soil** and **land use** data. The app includes an optional watershed analysis for zonal statistics and an interactive map.

> **Live demo:** *(placeholder)* > **Hugging Face Space:** https://huggingface.co/spaces/YOUR-USERNAME/YOUR-SPACE

---

## Features

- Upload soil and land use datasets and compute CN polygons and a CN raster
- Use the built-in **NLCD** lookup or provide your own CSV lookup table
- Automatically fix common issues like CRS mismatch and dual hydrologic groups (A/D, B/D, C/D) via user-defined replacements
- Optional **watershed** upload to compute zonal stats per basin
- Interactive **map** and a clean **HTML report** with global and per‑watershed stats
- Exports: GeoPackage of CN polygons, GeoTIFF raster, and optional Excel of watershed stats

---

## Project structure

```
.
├── app.py                 # Gradio web app
├── requirements.txt       # Python dependencies
└── src/
    ├── curve_number_calculator.py   # Core CN workflow
    ├── spatial_operations.py        # Rasterization and CRS helpers
    ├── cn_statistics.py             # Global and zonal statistics
    └── visualization.py             # Report and folium map
```

---

## Installation

Use Python 3.10+ and a clean virtual environment.

```bash
# 1) Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 2) Install dependencies
pip install -r requirements.txt
```

---

## Run the app locally

```bash
python app.py
```
The app starts a local web interface in your browser. If you plan to deploy to Hugging Face Spaces, keep the same entry point and ensure `gradio` is listed in `requirements.txt`.

---

## Input data requirements

- **Soil**: vector dataset with a hydrologic soil group field containing values A, B, C, D, or dual forms such as A/D, B/D, C/D.
- **Land use**: vector dataset with a numeric land use code field. The built‑in NLCD option expects **NLCD class codes** if you use the default lookup.
- Accepted formats: zip-compressed Shapefile set, GeoPackage, or GeoJSON. For Shapefiles upload a `.zip` that includes `.shp`, `.shx`, `.dbf`, and `.prj`.

**Key parameters in the UI**
- **Hydrologic Group field** (e.g., `hydgrpdcd`)
- **Land Use code field** (e.g., `gridcode`)
- **Use NLCD Lookup** or **Custom CSV** lookup
- **CRS (EPSG)** used for processing (default 4326)
- **Raster Cell Size** for the CN raster
- **Dual group replacements** for A/D, B/D, C/D
- *(Optional)* **Watershed file** and **Watershed ID field** for zonal statistics

---

## How the code processes your data (step by step)

Below is the end‑to‑end pipeline the app runs after you click **Calculate**.

1. **Validate uploads**
   - Checks that Shapefile uploads are complete when zipped. Non‑blocking warnings are shown for missing components.

2. **Load geospatial data**
   - Reads soil and land use layers using GeoPandas.
   - Loads a **CN lookup table**:
     - If *Use NLCD* is selected, the app uses a built‑in NLCD mapping of land‑use codes to CN values for soil groups A–D.
     - Otherwise, it reads your custom CSV with columns like `LUValue, A, B, C, D`.

3. **Preprocess soil data**
   - Reprojects soil layer to the chosen **EPSG** if needed.
   - Replaces **dual hydrologic groups** based on your selections, for example converting `A/D` to `D`.
   - Flags any unexpected group codes that are not A, B, C, or D.

4. **Preprocess land use data**
   - Reprojects to the same CRS as the soil layer if needed.
   - Casts the land‑use code field to integer when possible and warns if some rows cannot be converted.

5. **Spatial intersection**
   - Performs a polygon‑on‑polygon **intersection** between soil and land use to create combined segments that carry both attributes. This step is the heavy geometry operation and may take time on large datasets.

6. **Assign Curve Numbers**
   - For each intersected polygon, the app looks up a CN value using the land‑use code and the soil group as a key pair.
   - Polygons that do not find a match are reported with their land‑use and soil pair so you can update the lookup or data.

7. **Dissolve by CN**
   - Removes features with missing CN.
   - Computes each feature’s area and converts it to **hectares**.
   - **Dissolves** all features by their CN value and sums the areas. The output is a compact CN polygon layer with one row per CN.

8. **Create CN raster**
   - Rasterizes the dissolved polygons at the chosen **cell size**.
   - If the working CRS is WGS84 (EPSG:4326), the cell size is converted from meters to **degrees** so the output resolution is sensible at that latitude.
   - Writes a GeoTIFF with a simple colormap and NoData set to zero.

9. **Statistics**
   - **Global stats** are computed from the dissolved CN polygons, including weighted mean by area, min, max, median, standard deviation, and percentiles.
   - *(Optional)* **Zonal stats** are computed per watershed by sampling the CN raster. The app reprojects watersheds to match the raster CRS, then computes mean, min, max, median, standard deviation, coefficient of variation, and range per basin. An optional Excel file is produced.

10. **Outputs and report**
    - Saves **CN polygons** to GeoPackage, **CN raster** to GeoTIFF.
    - Builds an **HTML report** showing global numbers and the first five rows of watershed stats, with a full CSV download button.
    - Renders an **interactive folium map** with tooltips and a legend for runoff potential.

---

## Flow chart

```mermaid
flowchart TD
    A[User uploads soil and land use data] --> B[Validate uploads]
    B --> C[Load layers and CN lookup]
    C --> D[Preprocess soil: CRS fix, dual-group replacements]
    C --> E[Preprocess land use: CRS fix, code casting]
    D --> F[Spatial intersection (soil and land use)]
    E --> F
    F --> G[Assign Curve Numbers (lookup by LU code + soil group)]
    G --> H[Dissolve by CN and compute area_ha]
    H --> I[Create CN raster (cell size, CRS-aware)]
    I --> J[Global statistics from polygons]
    I --> K{Watersheds provided?}
    K -- Yes --> L[Zonal statistics per watershed]
    K -- No --> M[Skip zonal stats]
    J --> N[Generate HTML report]
    L --> N
    N --> O[Interactive map + downloads]

```

---

## Tips for successful runs

- Use reasonable **cell sizes** for your study area and CRS. Very small cells can lead to large rasters and slow runs.
- If you work in geographic CRS (EPSG:4326), remember that cell size is converted to degrees internally.
- Keep the **lookup table** aligned with your land‑use codes and soil group values. Missing pairs will be listed for quick fixes.

---

## Development notes

- The code is modular so you can import the processing pieces in other scripts:
  - `CurveNumberCalculator` for preprocessing, intersection, CN assignment, dissolve
  - `SpatialOperations` for rasterization
  - `CNStatistics` for global and zonal stats
  - `CNVisualization` for the report and map

---

## License and disclaimer

This software is provided **as is**, without warranty of any kind. The developer is **not liable** for any claims, damages, or other liabilities arising from use of this software or any outputs. Always **verify the results for accuracy** before using them in analysis, design, or decision making.

---

## References 

- USDA NRCS SCS Curve Number method
- USACE HEC‑HMS guidance for CN grids
- National Land Cover Database (NLCD)
- The open‑source geospatial ecosystem: GeoPandas, Rasterio, rasterstats, and Folium
