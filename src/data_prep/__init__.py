"""
Data Preparation Package
Optional workflow that downloads and processes soil (SSURGO) and NLCD land
cover data for a watershed, producing zipped shapefiles ready to import in
the CN workflow plus downloadable rasters and a preview map.

Modules
-------
common   : shared helpers (HTTP with VPN certificate fallback, AOI, exports)
soil     : SSURGO soil polygons with hydrologic groups via USDA Soil Data Access
nlcd     : NLCD land cover via the official MRLC Web Coverage Service
prep_map : interactive preview map of the prepared layers
"""

from .common import BOUNDARY_BUFFER_M, PREP_CELL_SIZE, PREP_CRS
from .nlcd import (
    FALLBACK_YEARS,
    NLCD_ATTRIBUTION,
    NLCD_CLASSES,
    NLCD_COLORS,
    NLCD_DATASET_URL,
    available_nlcd_years,
    fetch_nlcd_data,
)
from .prep_map import create_prep_map
from .report import create_prep_report
from .soil import (
    HSG_COLORS,
    SDA_ATTRIBUTION,
    SDA_DATASET_URL,
    fetch_soil_data,
)

__all__ = [
    "BOUNDARY_BUFFER_M",
    "PREP_CELL_SIZE",
    "PREP_CRS",
    "FALLBACK_YEARS",
    "NLCD_ATTRIBUTION",
    "NLCD_CLASSES",
    "NLCD_COLORS",
    "NLCD_DATASET_URL",
    "available_nlcd_years",
    "fetch_nlcd_data",
    "create_prep_map",
    "create_prep_report",
    "HSG_COLORS",
    "SDA_ATTRIBUTION",
    "SDA_DATASET_URL",
    "fetch_soil_data",
]
