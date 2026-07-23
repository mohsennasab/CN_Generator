"""
Data Preparation - Summary Report
Compact HTML summary of the prepared soil and land cover layers, shown in
the Data Preparation tab above the preview map.
"""

import pandas as pd

from .nlcd import NLCD_ATTRIBUTION, NLCD_DATASET_URL
from .soil import SDA_ATTRIBUTION, SDA_DATASET_URL

_TABLE_STYLE = """
    <style>
        .prep-report { font-family: Arial, sans-serif; color: var(--body-text-color); }
        .prep-report h2 {
            color: var(--body-text-color);
            border-bottom: 1px solid var(--border-color-primary);
            padding-bottom: 8px; margin-top: 24px; font-size: 18px;
        }
        .prep-report table {
            border-collapse: collapse; width: 100%; margin: 12px 0;
        }
        .prep-report th, .prep-report td {
            border: 1px solid var(--border-color-primary);
            padding: 8px 10px; text-align: left; font-size: 13px;
        }
        .prep-report th {
            background-color: var(--button-primary-background-fill, #2f766d);
            color: var(--button-primary-text-color, #ffffff);
        }
        .prep-report tr:nth-child(even) {
            background-color: var(--input-background-fill);
        }
        .prep-report .footnote {
            font-size: 12px; font-style: italic;
            color: var(--body-text-color-subdued, var(--body-text-color));
            margin: 6px 0 0 0;
        }
    </style>
"""


def _area_table(df, columns, headers):
    display = df[columns].copy()
    display.columns = headers
    return display.to_html(
        index=False,
        float_format=lambda x: f"{x:,.1f}" if pd.notna(x) else "N/A",
        border=0,
    )


def create_prep_report(soil_info=None, nlcd_info=None):
    """Build the HTML summary for the Data Preparation tab."""
    html = _TABLE_STYLE + '<div class="prep-report">'

    if nlcd_info is not None:
        product = nlcd_info.get("product", f"NLCD {nlcd_info['year']}")
        html += f"<h2>{product} Land Cover: Area by Class</h2>"
        html += _area_table(
            nlcd_info["summary"],
            ["gridcode", "landuse", "area_acres", "percent_area"],
            ["Code", "Land Cover Class", "Area (acres)", "Percent of Area"],
        )
        html += (
            f'<p class="footnote">{nlcd_info["polygon_count"]:,} land use '
            'polygons were created from the clipped 30 m land cover grid. '
            f'Source: <a href="{NLCD_DATASET_URL}" target="_blank">'
            f"{NLCD_ATTRIBUTION}</a>.</p>"
        )

    if soil_info is not None:
        html += "<h2>SSURGO Soils: Area by Hydrologic Group</h2>"
        html += _area_table(
            soil_info["summary"],
            ["hydrologic_group", "area_acres", "percent_area"],
            ["Hydrologic Group", "Area (acres)", "Percent of Area"],
        )
        html += (
            f'<p class="footnote">{soil_info["polygon_count"]:,} soil polygons '
            "were downloaded and clipped to the watershed. "
            f'Source: <a href="{SDA_DATASET_URL}" target="_blank">'
            f"{SDA_ATTRIBUTION}</a>.</p>"
        )
        if soil_info.get("missing_hsg_count"):
            html += (
                f'<p class="footnote"><strong>{soil_info["missing_hsg_count"]} '
                "soil polygons have no hydrologic group in SSURGO</strong> "
                "(commonly water bodies, urban land, or pits). They are kept "
                "in the layer; areas without a group are excluded from the CN "
                "calculation and reported as missing hydrogroups. Dual groups "
                "such as A/D are kept as-is here; the CN workflow (next tab) "
                "applies your drained/undrained replacements.</p>"
            )

    html += "</div>"
    return html
