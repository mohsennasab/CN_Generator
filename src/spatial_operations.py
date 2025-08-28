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