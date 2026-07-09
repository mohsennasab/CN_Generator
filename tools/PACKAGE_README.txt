CN Generator for Windows

This folder contains a ready-to-run copy of CN Generator. You do not need to install Python.

How to start

1. Extract the full zip file first. Do not run the app from inside the zip preview.
2. Double-click CN_Generator.exe.
3. Your browser should open to the local app.
4. Keep the CN Generator window open while you use the app.
5. Close the window when you are finished.

If Windows SmartScreen appears, choose More info, then Run anyway if you trust this download.

Sample data

Sample files are included in:

Sample Data\HUC10 Example

Use these files to try the app:

- SoilData_SandCreek.zip as the soil layer
- NLCD2024_SandCreek.zip as the land use layer
- SandCreek_HUC10.zip as the optional watershed boundary layer

Shortcuts

CN_Generator.exe is the main app launcher. It already uses the CN Generator icon.

If you want a folder shortcut and Desktop shortcut, double-click:

Create_Shortcuts.bat

GCN10 global dataset (optional)

The app can also read the GCN10 global 10 m Curve Number dataset for your
watershed. Enable it in Step 2 of the app. You can view the GCN10 layer on the
map, download the clipped GeoTIFF, download watershed statistics, and compare
GCN10 with your own results. This option needs an internet connection while
processing. Everything else works offline.

GCN10 credit: GCN10 -- Global 10 m Curve Number Dataset (Azzam et al.),
https://hydro.nmsu.edu/datasets/gcn10/, ODbL v1.0 license.
Citation: Azzam, M. A., Cho, H., 2026. GCN10: An MPI-parallelized framework
for processing global curve number rasters for hydrologic modeling.
SoftwareX 34, 102725.

Notes

- The app runs locally on your computer.
- It does not upload your GIS files to a public server.
- The optional GCN10 feature downloads only the small part of the dataset
  that covers your watershed.
- The _internal folder contains bundled app files. It is hidden because most users do not need to open it.
- If the app does not start, move the folder to a simple path such as C:\CN_Generator and try again.

License

CN Generator is free for personal use. For commercial use, training, workshops, or videos, contact Mohsen Tahmasebi Nasab at https://www.hydromohsen.com/.
