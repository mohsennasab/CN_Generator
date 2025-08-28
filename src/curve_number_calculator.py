"""
SCS Curve Number Calculator Module
Handles the core CN calculation logic using open-source geospatial libraries
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import box
import warnings
from multiprocessing import Pool, cpu_count
from functools import partial
from typing import Optional, Tuple, Dict, Any

warnings.filterwarnings('ignore')

class CurveNumberCalculator:
    """
    Calculate SCS Curve Numbers based on land use and soil hydrologic groups.
    
    The SCS (Soil Conservation Service) Curve Number method estimates 
    direct runoff from rainfall events based on land use and soil properties.
    """
    
    def __init__(self, crs: str = 'EPSG:4326', use_parallel: bool = True):
        """
        Initialize the Curve Number Calculator.
        
        Parameters:
        -----------
        crs : str
            Coordinate Reference System (e.g., 'EPSG:4326', 'EPSG:3857')
        use_parallel : bool
            Enable parallel processing for large datasets (currently not implemented for overlay)
        """
        self.crs = crs
        self.use_parallel = use_parallel
        self.n_cores = cpu_count() - 1 if use_parallel else 1
        
    def load_lookup_table(self, lookup_path: str = None, use_nlcd: bool = True) -> pd.DataFrame:
        """
        Load the CN lookup table.
        
        Parameters:
        -----------
        lookup_path : str
            Path to custom lookup table CSV
        use_nlcd : bool
            Use the built-in NLCD lookup table
            
        Returns:
        --------
        pd.DataFrame : Lookup table with land use codes and CN values
        """
        if lookup_path:
            lookup_df = pd.read_csv(lookup_path)
            print(f"Loaded custom lookup table from {lookup_path}")
        elif use_nlcd:
            # Default NLCD lookup table structure
            lookup_df = self._get_nlcd_lookup()
            print("Using NLCD (National Land Cover Database) lookup table")
        else:
            raise ValueError("Please provide a lookup table or enable NLCD option")
            
        return lookup_df
    
    def _get_nlcd_lookup(self) -> pd.DataFrame:
        """
        Get the default NLCD lookup table with CN values based on official HEC-HMS documentation.
        
        Returns a comprehensive lookup table for NLCD land cover classes
        with curve numbers for each hydrologic soil group.
        
        Reference: HEC-HMS User's Manual and official USACE documentation
        """
        data = {
            'LUValue': [11, 21, 22, 23, 24, 31, 41, 42, 43, 52, 71, 81, 82, 90, 95],
            'Description': [
                'Open Water', 'Developed, Open Space', 'Developed, Low Intensity', 
                'Developed, Medium Intensity', 'Developed, High Intensity', 
                'Barren Land (Rock/Sand/Clay)', 'Deciduous Forest', 'Evergreen Forest',
                'Mixed Forest', 'Shrub/Scrub', 'Grassland/Herbaceous', 'Pasture/Hay',
                'Cultivated Crops', 'Woody Wetlands', 'Emergent Herbaceous Wetlands'
            ],
            'A': [98, 49, 57, 61, 81, 78, 45, 25, 36, 55, 50, 49, 67, 30, 30],
            'B': [98, 69, 72, 75, 88, 86, 66, 55, 60, 72, 69, 69, 78, 58, 58],
            'C': [98, 79, 81, 83, 91, 91, 77, 70, 73, 81, 79, 79, 85, 71, 71],
            'D': [98, 84, 86, 87, 93, 93, 83, 77, 79, 86, 84, 84, 89, 78, 78]
        }
        return pd.DataFrame(data)
    
    def preprocess_soil_data(self, soil_gdf: gpd.GeoDataFrame, hydgrp_field: str,
                           replacements: Dict[str, str]) -> gpd.GeoDataFrame:
        """
        Preprocess soil data and handle dual hydrologic groups.
        
        Parameters:
        -----------
        soil_gdf : GeoDataFrame
            Soil shapefile data
        hydgrp_field : str
            Field name containing hydrologic group codes
        replacements : dict
            Replacement mapping for dual groups (e.g., {'A/D': 'D'})
            
        Returns:
        --------
        GeoDataFrame : Preprocessed soil data
        """
        soil_gdf = soil_gdf.copy()
        
        # Ensure consistent CRS
        if soil_gdf.crs != self.crs:
            print(f"Reprojecting soil data from {soil_gdf.crs} to {self.crs}")
            soil_gdf = soil_gdf.to_crs(self.crs)
        
        # Handle dual hydrologic groups
        for dual_group, replacement in replacements.items():
            mask = soil_gdf[hydgrp_field] == dual_group
            soil_gdf.loc[mask, hydgrp_field] = replacement
            if mask.sum() > 0:
                print(f"Replaced {mask.sum()} occurrences of '{dual_group}' with '{replacement}'")
        
        # Validate hydrologic groups
        valid_groups = ['A', 'B', 'C', 'D']
        invalid_mask = ~soil_gdf[hydgrp_field].isin(valid_groups)
        if invalid_mask.sum() > 0:
            print(f"Warning: {invalid_mask.sum()} features have invalid hydrologic groups")
            print(f"   Invalid values: {soil_gdf.loc[invalid_mask, hydgrp_field].unique()}")
        
        return soil_gdf
    
    def preprocess_landuse_data(self, landuse_gdf: gpd.GeoDataFrame, 
                               code_field: str) -> gpd.GeoDataFrame:
        """
        Preprocess land use data.
        
        Parameters:
        -----------
        landuse_gdf : GeoDataFrame
            Land use shapefile data
        code_field : str
            Field name containing land use codes
            
        Returns:
        --------
        GeoDataFrame : Preprocessed land use data
        """
        landuse_gdf = landuse_gdf.copy()
        
        # Ensure consistent CRS
        if landuse_gdf.crs != self.crs:
            print(f"Reprojecting land use data from {landuse_gdf.crs} to {self.crs}")
            landuse_gdf = landuse_gdf.to_crs(self.crs)
        
        # Ensure land use codes are integers
        try:
            landuse_gdf[code_field] = landuse_gdf[code_field].astype(int)
        except:
            print("Warning: Could not convert all land use codes to integers")
        
        return landuse_gdf
    
    def compute_intersection(self, soil_gdf: gpd.GeoDataFrame, 
                           landuse_gdf: gpd.GeoDataFrame,
                           hydgrp_field: str, 
                           code_field: str) -> gpd.GeoDataFrame:
        """
        Compute spatial intersection of soil and land use layers.
        
        Parameters:
        -----------
        soil_gdf : GeoDataFrame
            Preprocessed soil data
        landuse_gdf : GeoDataFrame
            Preprocessed land use data
        hydgrp_field : str
            Soil hydrologic group field
        code_field : str
            Land use code field
            
        Returns:
        --------
        GeoDataFrame : Intersection with both soil and land use attributes
        """
        print("Computing spatial intersection (this may take a while for large datasets)...")
        
        # Use standard geopandas overlay - it's already optimized
        intersection_gdf = gpd.overlay(soil_gdf, landuse_gdf, how='intersection')
        
        # Clean up column names
        if f'{hydgrp_field}_1' in intersection_gdf.columns:
            intersection_gdf[hydgrp_field] = intersection_gdf[f'{hydgrp_field}_1']
            intersection_gdf = intersection_gdf.drop(columns=[f'{hydgrp_field}_1', f'{hydgrp_field}_2'], errors='ignore')
        
        if f'{code_field}_1' in intersection_gdf.columns:
            intersection_gdf[code_field] = intersection_gdf[f'{code_field}_1']
            intersection_gdf = intersection_gdf.drop(columns=[f'{code_field}_1', f'{code_field}_2'], errors='ignore')
        
        print(f"Created {len(intersection_gdf)} intersection polygons")
        return intersection_gdf
    
    def assign_curve_numbers(self, intersection_gdf: gpd.GeoDataFrame,
                            lookup_df: pd.DataFrame,
                            hydgrp_field: str,
                            code_field: str) -> gpd.GeoDataFrame:
        """
        Assign curve numbers based on lookup table.
        
        Parameters:
        -----------
        intersection_gdf : GeoDataFrame
            Intersection of soil and land use
        lookup_df : DataFrame
            CN lookup table
        hydgrp_field : str
            Soil hydrologic group field
        code_field : str
            Land use code field
            
        Returns:
        --------
        GeoDataFrame : Data with assigned curve numbers
        """
        # Create lookup dictionary
        lookup_dict = {}
        for _, row in lookup_df.iterrows():
            lu_value = row['LUValue']
            for hg in ['A', 'B', 'C', 'D']:
                if hg in row:
                    lookup_dict[(lu_value, hg)] = row[hg]
        
        # Assign CN values
        cn_values = []
        for _, row in intersection_gdf.iterrows():
            key = (row[code_field], row[hydgrp_field])
            cn = lookup_dict.get(key, None)
            cn_values.append(cn)
        
        intersection_gdf['CN'] = cn_values
        
        # Report statistics
        valid_cn = intersection_gdf['CN'].notna()
        print(f"Assigned curve numbers to {valid_cn.sum()}/{len(intersection_gdf)} polygons")
        
        if not valid_cn.all():
            missing_combos = intersection_gdf[~valid_cn][[code_field, hydgrp_field]].drop_duplicates()
            print(f"Warning: {(~valid_cn).sum()} polygons have no CN value")
            print("   Missing land use/soil combinations:")
            for _, row in missing_combos.iterrows():
                print(f"     Land Use: {row[code_field]}, Soil Group: {row[hydgrp_field]}")
        
        return intersection_gdf
    
    def dissolve_by_cn(self, cn_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Dissolve polygons by curve number value.
        
        Parameters:
        -----------
        cn_gdf : GeoDataFrame
            Data with curve numbers assigned
            
        Returns:
        --------
        GeoDataFrame : Dissolved polygons by CN value
        """
        # Remove invalid CN values
        valid_gdf = cn_gdf[cn_gdf['CN'].notna()].copy()
        
        if len(valid_gdf) == 0:
            raise ValueError("No valid curve numbers found!")
        
        print("Dissolving polygons by curve number...")
        
        # Calculate area before dissolving
        valid_gdf['area_ha'] = valid_gdf.geometry.area / 10000  # Convert to hectares
        
        # Dissolve and aggregate statistics
        dissolved = valid_gdf.dissolve(by='CN', aggfunc={'area_ha': 'sum'})
        dissolved = dissolved.reset_index()
        
        print(f"Dissolved to {len(dissolved)} unique curve number polygons")
        
        return dissolved