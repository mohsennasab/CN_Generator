<p align="center">
  <img src="Logo/CN_Generator.png" alt="Curve Number Studio logo" width="180">
</p>

# Curve Number Studio

Curve Number Studio is a local tool for creating SCS Curve Number maps and summary statistics from soil and land use data. It runs in your browser, but the processing happens on your own computer.

The app can be used in two ways:

1. Download the Windows zip package if you only want to run the tool.
2. Clone the source code if you want to inspect, modify, or develop the app.

## Option 1: Windows Zip Package

This is the easiest option for most users. It does not require installing Python.

1. Go to the GitHub Releases page for this repository.
2. Download `Curve_Number_Studio_Windows_<version>.zip`.
3. Right-click the zip file and choose **Extract All**.
4. Open the extracted folder.
5. Double-click `Curve_Number_Studio.exe`.
6. Keep the Curve Number Studio window open while using the app.

If Windows SmartScreen appears, choose **More info**, then **Run anyway** if you trust the download.

The package includes:

- `Curve_Number_Studio.exe`, the main app launcher.
- `README.txt`, a short guide for zip users.
- `Sample Data\HUC10 Example`, example files for testing.
- `_internal`, bundled runtime files used by the app. This folder is hidden because most users do not need it.

## Option 2: Source Code For Developers

Use this option if you want to review the code, customize the app, or build a new release package.

Requirements:

- Windows, macOS, or Linux for development.
- Python 3.10 or newer. Python 3.11 is recommended.
- A clean virtual environment.

Setup:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

On Windows, you can also double-click:

```text
Curve_Number_Studio.bat
```

The batch launcher creates `.venv`, installs dependencies, handles proxy prompts when needed, and starts the local app.

## Sample Data

Example files are included in:

```text
data/HUC10 Example/
```

Suggested test inputs:

- Soil layer: `SoilData_SandCreek.zip`
- Land use layer: `NLCD2024_SandCreek.zip`
- Optional watershed layer: `SandCreek_HUC10.zip`

The folder also includes a spreadsheet and verification notes to help check expected results.

A second example, `data/Local Drainage Example.zip`, holds a subbasin boundary layer you can use on its own with the GCN10 workflow.

## Building The Windows Package

Install the developer/build dependencies:

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Build the package:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows_package.ps1 -Version 0.5.0
```

The build creates:

```text
release/Curve_Number_Studio_Windows_0.5.0/
release/Curve_Number_Studio_Windows_0.5.0.zip
```

The script zips the package with .NET so that the hidden `_internal` folder is included, then verifies that the zip holds the same number of files as the package folder. Upload the zip file to a GitHub Release so non-developer users can download it.

## Features

- Optionally download and prepare the input data automatically: SSURGO soil polygons with hydrologic soil groups from USDA Soil Data Access, and Annual NLCD land cover (any year from 1985 to the most recent release) from the official USGS service, clipped to your watershed and ready to use.
- Upload soil and land use datasets and compute CN polygons and a CN raster.
- Use the built-in NLCD lookup or provide a custom CSV lookup table.
- Automatically handle CRS mismatch and dual hydrologic groups such as `A/D`, `B/D`, and `C/D`.
- Optionally upload watershed boundaries to clip the rasters and compute zonal statistics per basin.
- Optionally view, download, and compare against the GCN10 global 10 m Curve Number dataset.
- View an interactive map and HTML report inside the app.
- Export CN polygons as GeoPackage and CN raster as GeoTIFF.
- Save every run's GIS outputs and statistics tables, plus a dated model run log, to a Results folder next to the app. The report and map are shown in the app and are not written to the Results folder.

## Data Preparation (Optional)

The Data Preparation tab (tab 2) can download and process the soil and land use inputs for you, using only the watershed boundary uploaded in tab 1. It is optional: if you already have your own layers, skip it and upload them in tab 3 as before.

What it does:

- **Soil data**: queries USDA-NRCS Soil Data Access, the official live service for the SSURGO database, and downloads the soil map unit polygons that intersect your watershed together with the dominant-condition hydrologic soil group field (`hydgrpdcd`: A, B, C, D, and dual groups such as A/D). The polygons are saved as a zipped shapefile and also rasterized to a 30 m hydrologic soil group GeoTIFF you can download.
- **Land use data**: downloads Annual NLCD Collection 1 land cover from the official USGS service behind the MRLC viewer, on its native 30 m Conus Albers grid, clipped to your watershed, with the official NLCD colors embedded in the GeoTIFF. The grid is also converted to land use polygons with the standard NLCD codes (`gridcode`) and saved as a zipped shapefile. The year is picked from a dropdown covering 1985 through the most recent release (currently 2025). Annual NLCD maps every year with one consistent method, so any two years can be compared directly, and it uses the same 16-class legend and class codes as all earlier NLCD products. The year list is read live from the service when the app starts, so new releases appear automatically.
- Both layers are clipped to the watershed plus a small 90 m buffer, so the soil and land use intersection in the CN workflow fully covers every boundary cell. The final CN raster is still clipped exactly to the boundary.
- When preparation finishes, the two zipped shapefiles are loaded into the CN workflow (tab 3) automatically, the field mappings are already correct (`hydgrpdcd` and `gridcode`), and a preview map shows the land cover, the soil groups, and the watershed boundary as toggleable layers.
- All prepared files, plus a dated log, are saved to a `DataPrep` subfolder inside `Results` so you can reuse them later without downloading again.

A few things worth knowing:

- Data preparation needs an internet connection. Soil data covers the United States and territories (SSURGO); Annual NLCD land cover covers the conterminous United States.
- Large watersheds are downloaded in small chunks with visible progress, so the app stays responsive. Very large areas are refused with a clear message instead of exhausting memory; the practical limits are far beyond a typical HUC8 watershed.
- On corporate VPNs that inspect secure traffic, downloads retry once with certificate verification turned off, the same fallback the GCN10 reader uses, and the retry is recorded in the log.
- Some SSURGO map units (often water bodies, urban land, or pits) have no hydrologic group. They are kept in the soil layer and reported by the CN workflow as missing hydrogroups, never guessed.

## GCN10 Global Dataset (Optional)

The app can read the GCN10 global 10 m Curve Number dataset for your watershed. GCN10 was built by Muhammad Abdullah Azzam and Huidae Cho at New Mexico State University from ESA WorldCover 2021 land cover and HYSOGs250m hydrologic soil groups.

The GCN10 option lives in tab 4 of the app and is on by default. Turn it off there if you are offline or do not need the global dataset. With GCN10 enabled you can:

- Pick the hydrologic condition (Poor, Fair, Good), antecedent runoff condition (ARC I, II, III), and drainage assumption (Drained, Undrained). The defaults are Fair, ARC II, Undrained.
- See the GCN10 raster on the interactive map and turn it on or off with the layer control.
- Download the GCN10 raster clipped exactly to your watershed as a GeoTIFF.
- Download GCN10 watershed statistics as a CSV file.
- Compare your generated CN values with GCN10 side by side, per watershed, with a mean difference column.

You can also run GCN10 alone without soil and land use data. Uncheck the box at the top of tab 3, upload a watershed boundary in tab 1, and keep GCN10 enabled in tab 4.

A few things worth knowing:

- The GCN10 option needs an internet connection while processing. The app streams only the small window of data that covers your watershed, so a typical run transfers a few megabytes and takes a few seconds. Everything else in the app works offline.
- On corporate VPNs or networks that inspect secure traffic, the normal certificate check on the GCN10 server can fail. When that happens, the app retries the GCN10 download once with certificate verification turned off and records this in the run log. This only affects how the GCN10 file is downloaded; the data and results are unchanged. If your organization provides a certificate bundle file, you can point the app at it by setting the `CN_CA_BUNDLE`, `CURL_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`, or `SSL_CERT_FILE` environment variable to its path.
- The GCN10 raster keeps its native 10 m grid in EPSG:4326 with NoData 255, clipped exactly to your boundary: a cell is kept only when its center falls inside the boundary. Statistics for each product are computed on its own grid over the same watershed polygons, so nothing is resampled for the comparison.
- GCN10 data is distributed under the Open Data Commons Open Database License (ODbL) v1.0. Public use of the data or products derived from it must credit "GCN10 -- Global 10 m Curve Number Dataset (Azzam et al.)".

Dataset page: https://hydro.nmsu.edu/datasets/gcn10/

Citation: Azzam, M. A., Cho, H., 2026. GCN10: An MPI-parallelized framework for processing global curve number rasters for hydrologic modeling. SoftwareX 34, 102725. https://doi.org/10.1016/j.softx.2026.102725

## Input Data Requirements

- Soil: vector dataset with a hydrologic soil group field containing values `A`, `B`, `C`, `D`, or dual forms such as `A/D`, `B/D`, `C/D`.
- Land use: vector dataset with a numeric land use code field. The built-in NLCD option expects NLCD class codes.
- Accepted formats: zip-compressed Shapefile set, GeoPackage, or GeoJSON.
- For Shapefiles, upload a `.zip` that includes `.shp`, `.shx`, `.dbf`, and `.prj`.

## Processing Overview

0. Optional: download and prepare the soil and land use layers automatically in the Data Preparation tab (SSURGO soils via Soil Data Access, Annual NLCD land cover via the official USGS service), clipped to the watershed plus a 90 m buffer.
1. Validate uploaded soil, land use, and optional watershed files.
2. Load geospatial layers with GeoPandas.
3. Load the built-in NLCD lookup table or a custom CSV lookup.
4. Reproject data to the selected EPSG code when needed.
5. Replace dual hydrologic soil groups using the selected UI choices.
6. Intersect soil and land use polygons.
7. Assign Curve Numbers from the lookup table.
8. Dissolve polygons by CN value and calculate area.
9. Rasterize the CN polygons to GeoTIFF, then clip the raster exactly to the watershed boundary when one is uploaded.
10. Compute global and optional watershed zonal statistics. Zonal statistics use exactly the cells clipped to each watershed: a cell counts when its center falls inside the boundary.
11. When the GCN10 option is on, stream the GCN10 window covering the watershed, clip it exactly to the boundary, compute the same watershed statistics on the native GCN10 grid, and build a comparison table.
12. Build the report, interactive map, and downloadable outputs.

## Project Structure

```text
.
|-- app.py
|-- Curve_Number_Studio.bat
|-- LICENSE.md
|-- requirements.txt
|-- Logo/
|   |-- CN_Generator.png
|   `-- CN_Generator.ico
|-- data/
|   |-- HUC10 Example/
|   |-- Local Drainage Example.zip
|   |-- gcn10/
|   `-- lookup_tables/
|-- src/
|   |-- curve_number_calculator.py
|   |-- spatial_operations.py
|   |-- cn_statistics.py
|   |-- zonal_exact.py
|   |-- gcn10.py
|   |-- visualization.py
|   `-- data_prep/
|       |-- common.py
|       |-- soil.py
|       |-- nlcd.py
|       |-- prep_map.py
|       `-- report.py
`-- tools/
    |-- build_windows_package.ps1
    |-- install_dependencies.ps1
    `-- PACKAGE_README.txt
```

## License

Curve Number Studio is free for personal, non-commercial use.

For commercial use, paid consulting, internal business use, client deliverables, training, workshops, course material, demonstrations for paid services, or videos and media created for commercial purposes, please contact Mohsen Tahmasebi Nasab:

https://www.hydromohsen.com/

This software is provided as-is, without warranty of any kind. Always verify results before using them in analysis, design, or decision making.

## References

- USDA NRCS SCS Curve Number method (Technical Release 55)
- USACE HEC-HMS guidance for CN grids
- Annual NLCD (National Land Cover Database) Collection 1, U.S. Geological Survey, distributed by the MRLC Consortium, https://www.mrlc.gov/
- Annual NLCD Collection 1 Science Product User Guide, LSDS-2103, USGS EROS
- Soil Survey Geographic (SSURGO) Database, USDA-NRCS Soil Data Access, https://sdmdataaccess.nrcs.usda.gov/
- GCN10 -- Global 10 m Curve Number Dataset (Azzam et al.), https://hydro.nmsu.edu/datasets/gcn10/, ODbL v1.0
- Azzam, M. A., Cho, H., 2026. GCN10: An MPI-parallelized framework for processing global curve number rasters for hydrologic modeling. SoftwareX 34, 102725
- GeoPandas, Rasterio, rasterstats, Folium, and Gradio
