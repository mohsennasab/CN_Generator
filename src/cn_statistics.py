"""
CN Statistics Module
Calculate zonal statistics and CN distribution metrics
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from rasterstats import zonal_stats
import rasterio
from typing import Dict, List, Optional
import warnings
warnings.filterwarnings('ignore')

class CNStatistics:
    """Calculate statistics for Curve Number distributions."""
    
    @staticmethod
    def calculate_global_stats(cn_gdf: gpd.GeoDataFrame) -> Dict:
        """
        Calculate global CN statistics.
        
        Parameters:
        -----------
        cn_gdf : GeoDataFrame
            GeoDataFrame with CN values
            
        Returns:
        --------
        dict : Statistics dictionary
        """
        # Filter valid CN values
        valid_cn = cn_gdf[cn_gdf['CN'].notna()]['CN']
        
        if 'area_ha' in cn_gdf.columns:
            # Weighted statistics by area
            weights = cn_gdf[cn_gdf['CN'].notna()]['area_ha']
            weighted_mean = np.average(valid_cn, weights=weights)
            
            stats = {
                'count': len(valid_cn),
                'min': valid_cn.min(),
                'max': valid_cn.max(),
                'mean': valid_cn.mean(),
                'weighted_mean': weighted_mean,
                'median': valid_cn.median(),
                'std': valid_cn.std(),
                'unique_values': len(valid_cn.unique())
            }
            
            # Add distribution percentiles
            percentiles = [10, 25, 50, 75, 90]
            for p in percentiles:
                stats[f'percentile_{p}'] = np.percentile(valid_cn, p)
        else:
            stats = {
                'count': len(valid_cn),
                'min': valid_cn.min(),
                'max': valid_cn.max(),
                'mean': valid_cn.mean(),
                'median': valid_cn.median(),
                'std': valid_cn.std(),
                'unique_values': len(valid_cn.unique())
            }
        
        return stats
    
    @staticmethod
    def calculate_zonal_statistics(cn_raster_path: str,
                                  watershed_gdf: gpd.GeoDataFrame,
                                  watershed_field: str) -> pd.DataFrame:
        """
        Calculate zonal statistics for watersheds.
        
        Parameters:
        -----------
        cn_raster_path : str
            Path to CN raster file
        watershed_gdf : GeoDataFrame
            Watershed boundaries
        watershed_field : str
            Field with watershed names/IDs
            
        Returns:
        --------
        DataFrame : Zonal statistics for each watershed
        """
        print("Calculating zonal statistics for watersheds...")
        
        # Open raster to check CRS
        with rasterio.open(cn_raster_path) as src:
            raster_crs = src.crs
            
        # Reproject watersheds if needed
        if watershed_gdf.crs != raster_crs:
            print(f"Reprojecting watersheds to match raster CRS")
            watershed_gdf = watershed_gdf.to_crs(raster_crs)
        
        # Calculate zonal statistics
        stats_list = zonal_stats(
            watershed_gdf.geometry,
            cn_raster_path,
            stats=['min', 'max', 'mean', 'median', 'std', 'count', 'sum'],
            nodata=0
        )
        
        # Create results dataframe
        results = pd.DataFrame(stats_list)
        results[watershed_field] = watershed_gdf[watershed_field].values
        
        # Calculate additional statistics
        results['cv'] = (results['std'] / results['mean']) * 100  # Coefficient of variation
        results['range'] = results['max'] - results['min']
        
        # Reorder columns
        cols = [watershed_field] + [col for col in results.columns if col != watershed_field]
        results = results[cols]
        
        # Round numeric columns
        numeric_cols = results.select_dtypes(include=[np.number]).columns
        results[numeric_cols] = results[numeric_cols].round(2)
        
        print(f"Calculated statistics for {len(results)} watersheds")
        
        return results
    
    @staticmethod
    def generate_cn_distribution(cn_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
        """
        Generate CN value distribution table.
        
        Parameters:
        -----------
        cn_gdf : GeoDataFrame
            GeoDataFrame with CN values
            
        Returns:
        --------
        DataFrame : Distribution of CN values
        """
        # Group by CN value
        if 'area_ha' in cn_gdf.columns:
            distribution = cn_gdf.groupby('CN').agg({
                'area_ha': 'sum',
                'geometry': 'count'
            }).rename(columns={'geometry': 'polygon_count'})
            
            # Calculate percentages
            total_area = distribution['area_ha'].sum()
            distribution['area_percent'] = (distribution['area_ha'] / total_area * 100).round(2)
            
            # Add cumulative percentage
            distribution['cumulative_percent'] = distribution['area_percent'].cumsum()
        else:
            distribution = cn_gdf.groupby('CN').size().to_frame('count')
            distribution['percent'] = (distribution['count'] / distribution['count'].sum() * 100).round(2)
        
        distribution = distribution.reset_index()
        
        return distribution
    
    @staticmethod
    def classify_cn_ranges(cn_values: pd.Series) -> pd.Series:
        """
        Classify CN values into runoff potential categories.
        
        Parameters:
        -----------
        cn_values : Series
            Series of CN values
            
        Returns:
        --------
        Series : Classification labels
        """
        conditions = [
            cn_values < 40,
            (cn_values >= 40) & (cn_values < 60),
            (cn_values >= 60) & (cn_values < 80),
            cn_values >= 80
        ]
        
        choices = [
            'Low Runoff Potential',
            'Moderate Runoff Potential', 
            'High Runoff Potential',
            'Very High Runoff Potential'
        ]
        
        return pd.Series(np.select(conditions, choices, default='Unknown'), 
                        index=cn_values.index)