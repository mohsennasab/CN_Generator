"""
Spatial Operations Module
Handles rasterization and spatial transformations
"""

import geopandas as gpd
import rasterio
from rasterio import features
from rasterio.transform import from_bounds
from rasterio.crs import CRS
import numpy as np
from typing import Tuple, Optional
import tempfile
import os

class SpatialOperations:
    """Handle spatial operations including rasterization and CRS transformations."""

    # Rough bounding box of the conterminous United States in lon/lat.
    # Used only to decide whether Conus Albers is a sensible projection.
    _CONUS_BBOX = (-125.0, 24.0, -66.5, 49.5)  # lon_min, lat_min, lon_max, lat_max

    @staticmethod
    def choose_projected_crs(gdf: gpd.GeoDataFrame) -> Optional[int]:
        """
        Pick a meter-based projected CRS that fits the data extent.

        Working in a projected CRS with meter units means the raster cell size
        is an exact distance and polygon areas are real hectares, with no
        degree-to-meter approximation.

        The rule is:
        - If the data center falls inside the conterminous United States, use
          EPSG:5070 (NAD83 / Conus Albers). It is an equal-area projection in
          meters and is the projection NLCD and gSSURGO are distributed in, so
          it also lines the grid up with those national datasets.
        - Otherwise use the UTM zone that contains the data center (WGS84 UTM,
          EPSG:326xx north of the equator, EPSG:327xx south). UTM is meter
          based and keeps distortion small over a single watershed.

        Parameters
        ----------
        gdf : GeoDataFrame
            Data to fit a projection to. Must have a defined CRS.

        Returns
        -------
        int or None
            EPSG code of the chosen projected CRS, or None when the CRS is
            missing so a caller can fall back to the data as read.
        """
        if gdf is None or gdf.crs is None:
            return None

        # Measure the extent in lon/lat so the test is CRS independent.
        geographic = gdf if gdf.crs.to_epsg() == 4326 else gdf.to_crs(4326)
        minx, miny, maxx, maxy = geographic.total_bounds
        center_lon = (minx + maxx) / 2.0
        center_lat = (miny + maxy) / 2.0

        lon_min, lat_min, lon_max, lat_max = SpatialOperations._CONUS_BBOX
        if lon_min <= center_lon <= lon_max and lat_min <= center_lat <= lat_max:
            return 5070

        zone = int((center_lon + 180.0) // 6.0) + 1
        zone = min(max(zone, 1), 60)
        return (32600 if center_lat >= 0 else 32700) + zone

    @staticmethod
    def create_cn_raster(cn_gdf: gpd.GeoDataFrame,
                         cell_size: float,
                         output_path: str = None,
                         bounds: Optional[Tuple] = None) -> str:
        """
        Convert CN polygons to raster format.
        
        Parameters:
        -----------
        cn_gdf : GeoDataFrame
            Dissolved CN polygons
        cell_size : float
            Cell size in map units
        output_path : str
            Path for output raster
        bounds : tuple
            Optional bounds (minx, miny, maxx, maxy)
            
        Returns:
        --------
        str : Path to output raster file
        """
        # Get bounds
        if bounds is None:
            bounds = cn_gdf.total_bounds
        
        minx, miny, maxx, maxy = bounds
        
        # Auto-adjust cell size based on CRS
        if cn_gdf.crs and cn_gdf.crs.to_string().startswith('EPSG:4326'):
            # For WGS84, convert cell size from meters to degrees
            # Approximate conversion: 1 degree ≈ 111,000 meters at equator
            cell_size_degrees = cell_size / 111000.0
            actual_cell_size = cell_size_degrees
            print(f"Converted cell size from {cell_size}m to {cell_size_degrees:.6f} degrees for WGS84")
        else:
            actual_cell_size = cell_size
        
        # Calculate dimensions
        width = max(1, int((maxx - minx) / actual_cell_size))
        height = max(1, int((maxy - miny) / actual_cell_size))
        
        # Ensure minimum dimensions
        if width <= 0 or height <= 0:
            print(f"Warning: Calculated dimensions too small. Using minimum size.")
            width = max(width, 100)
            height = max(height, 100)
            # Recalculate cell size to fit
            actual_cell_size = min((maxx - minx) / width, (maxy - miny) / height)
        
        print(f"Raster dimensions: {width} x {height} pixels")
        print(f"Actual cell size: {actual_cell_size:.6f} map units")
        
        # Create transform
        transform = from_bounds(minx, miny, maxx, maxy, width, height)
        
        # Prepare shapes for rasterization
        shapes = [(geom, value) for geom, value in 
                  zip(cn_gdf.geometry, cn_gdf['CN'])]
        
        # Rasterize
        raster = features.rasterize(
            shapes=shapes,
            out_shape=(height, width),
            transform=transform,
            fill=0,  # NoData value
            dtype=rasterio.uint8
        )
        
        # Create output path if not provided
        if output_path is None:
            output_path = os.path.join(tempfile.gettempdir(), 'cn_raster.tif')
        
        # Write raster
        with rasterio.open(
            output_path, 'w',
            driver='GTiff',
            height=height,
            width=width,
            count=1,
            dtype=rasterio.uint8,
            crs=cn_gdf.crs,
            transform=transform,
            compress='lzw'
        ) as dst:
            dst.write(raster, 1)
            dst.write_colormap(1, SpatialOperations._create_cn_colormap())
            
        print(f"Created raster: {output_path}")
        
        return output_path
    
    @staticmethod
    def _create_cn_colormap():
        """Create a colormap for CN values (30-100)."""
        colormap = {}
        for cn in range(0, 101):
            if cn == 0:
                # NoData - transparent
                colormap[cn] = (0, 0, 0, 0)
            elif cn < 30:
                # Very low CN - blue
                colormap[cn] = (0, 0, 255, 255)
            elif cn < 50:
                # Low CN - light blue
                colormap[cn] = (100, 150, 255, 255)
            elif cn < 70:
                # Medium CN - yellow
                colormap[cn] = (255, 255, 0, 255)
            elif cn < 85:
                # High CN - orange
                colormap[cn] = (255, 165, 0, 255)
            else:
                # Very high CN - red
                colormap[cn] = (255, 0, 0, 255)
        return colormap
    
    @staticmethod
    def validate_crs_compatibility(gdf1: gpd.GeoDataFrame, 
                                  gdf2: gpd.GeoDataFrame) -> bool:
        """
        Check if two GeoDataFrames have compatible CRS.
        
        Parameters:
        -----------
        gdf1, gdf2 : GeoDataFrame
            GeoDataFrames to compare
            
        Returns:
        --------
        bool : True if CRS are compatible
        """
        if gdf1.crs is None or gdf2.crs is None:
            print("Warning: One or both datasets lack CRS information")
            return False
        
        if gdf1.crs != gdf2.crs:
            print(f"CRS mismatch detected:")
            print(f"   Dataset 1: {gdf1.crs}")
            print(f"   Dataset 2: {gdf2.crs}")
            return False
        
        return True