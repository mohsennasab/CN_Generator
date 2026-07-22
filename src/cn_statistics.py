"""
CN Statistics Module
Calculate zonal statistics and CN distribution metrics
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import rasterio
from typing import Dict, List, Optional
import warnings

try:
    from .zonal_exact import exact_zonal_stats
except ImportError:  # when imported as a top-level module
    from zonal_exact import exact_zonal_stats

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
            
            # Add distribution percentiles (excluding 10 and 75 as requested)
            percentiles = [25, 50, 90]
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
                                  watershed_field: str,
                                  nodata: float = 0) -> pd.DataFrame:
        """
        Calculate zonal statistics for watersheds.

        A raster cell is assigned to a watershed when the cell center falls
        inside the watershed polygon, the same rule an exact raster clip
        uses. The statistics for each watershed therefore come from exactly
        the cells that a clip of the raster to that watershed would keep,
        each counted once with equal weight. See `zonal_exact.py`.

        Parameters:
        -----------
        cn_raster_path : str
            Path to CN raster file
        watershed_gdf : GeoDataFrame
            Watershed boundaries
        watershed_field : str
            Field with watershed names/IDs
        nodata : float
            NoData value of the raster (0 for app-generated CN rasters,
            255 for GCN10 rasters)

        Returns:
        --------
        DataFrame : Zonal statistics for each watershed
        """
        print("Calculating exact-clip zonal statistics for watersheds...")

        # Open raster to check CRS
        with rasterio.open(cn_raster_path) as src:
            raster_crs = src.crs

        # Reproject watersheds if needed
        if watershed_gdf.crs != raster_crs:
            print(f"Reprojecting watersheds to match raster CRS")
            watershed_gdf = watershed_gdf.to_crs(raster_crs)

        # Exact-clip zonal statistics: only cells whose center falls inside
        # each watershed polygon are counted
        stats_list = exact_zonal_stats(
            cn_raster_path,
            list(watershed_gdf.geometry),
            nodata=nodata,
        )

        # Create results dataframe, keeping the columns the rest of the app uses
        results = pd.DataFrame(stats_list)[['min', 'max', 'mean', 'median', 'std']]
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
    def build_comparison_table(user_stats: pd.DataFrame,
                               gcn10_stats: pd.DataFrame,
                               watershed_field: str) -> pd.DataFrame:
        """
        Merge user CN and GCN10 zonal statistics into one comparison table.

        Both inputs come from calculate_zonal_statistics over the same
        watershed polygons. Each raster is summarized on its own grid, so the
        differences reflect the data sources, not resampling.

        Parameters:
        -----------
        user_stats : DataFrame
            Zonal statistics for the user-generated CN raster
        gcn10_stats : DataFrame
            Zonal statistics for the GCN10 raster
        watershed_field : str
            Field with watershed names/IDs

        Returns:
        --------
        DataFrame : Side-by-side statistics with a mean difference column
        """
        user = user_stats[[watershed_field, 'mean', 'median', 'min', 'max']].copy()
        gcn = gcn10_stats[[watershed_field, 'mean', 'median', 'min', 'max']].copy()
        user.columns = [watershed_field, 'user_mean', 'user_median', 'user_min', 'user_max']
        gcn.columns = [watershed_field, 'gcn10_mean', 'gcn10_median', 'gcn10_min', 'gcn10_max']

        comparison = user.merge(gcn, on=watershed_field, how='outer')
        comparison['mean_diff'] = comparison['user_mean'] - comparison['gcn10_mean']

        ordered = [
            watershed_field,
            'user_mean', 'gcn10_mean', 'mean_diff',
            'user_median', 'gcn10_median',
            'user_min', 'gcn10_min',
            'user_max', 'gcn10_max',
        ]
        comparison = comparison[ordered]

        numeric_cols = comparison.select_dtypes(include=[np.number]).columns
        comparison[numeric_cols] = comparison[numeric_cols].round(2)

        return comparison

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
