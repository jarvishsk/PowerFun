"""PowerFun 分析模块

心率区间分析、配速趋势、月跑量统计、训练负荷等。
"""

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from src.config import HEART_RATE_ZONES, PACE_LEVELS, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class RunningAnalyzer:
    """跑步数据分析器"""

    def __init__(self, max_hr: Optional[int] = None, resting_hr: Optional[int] = None):
        """
        Args:
            max_hr: 最大心率 (用于计算心率区间)
            resting_hr: 静息心率 (用于心率储备法)
        """
        self.max_hr = max_hr
        self.resting_hr = resting_hr
        self.hr_zone_method = DEFAULT_CONFIG['hr_zone_method']

    def analyze(self, df: pd.DataFrame) -> dict:
        """综合分析，返回统计摘要

        Args:
            df: 标准化后的 DataFrame

        Returns:
            分析结果字典
        """
        if df.empty:
            return {'error': '无数据'}

        result = {}
        result['summary'] = self._summary_stats(df)
        result['monthly'] = self._monthly_stats(df)
        result['weekly'] = self._weekly_stats(df)
        result['pace_trend'] = self._pace_trend(df)
        result['hr_zones'] = self._hr_zone_summary(df)
        result['pace_distribution'] = self._pace_distribution(df)
        result['best_performances'] = self._best_performances(df)

        return result

    def _summary_stats(self, df: pd.DataFrame) -> dict:
        """总体统计"""
        return {
            'total_activities': len(df),
            'total_distance_km': round(df['distance'].sum(), 2),
            'total_duration_min': round(df['duration_min'].sum(), 1) if 'duration_min' in df.columns else None,
            'total_calories': int(df['calories'].sum()) if 'calories' in df.columns else None,
            'avg_distance_km': round(df['distance'].mean(), 2),
            'avg_pace': self._avg_pace_str(df),
            'avg_hr': round(df['avg_hr'].mean(), 0) if 'avg_hr' in df.columns else None,
            'max_hr': int(df['max_hr'].max()) if 'max_hr' in df.columns else None,
            'avg_cadence': round(df['cadence'].mean(), 0) if 'cadence' in df.columns else None,
            'date_range': {
                'start': df['date'].min().strftime('%Y-%m-%d'),
                'end': df['date'].max().strftime('%Y-%m-%d'),
            },
        }

    def _avg_pace_str(self, df: pd.DataFrame) -> str:
        """计算平均配速 (mm:ss)"""
        if 'pace_min_per_km' in df.columns:
            avg_pace = df['pace_min_per_km'].mean()
            if pd.notna(avg_pace) and avg_pace > 0:
                minutes = int(avg_pace)
                seconds = int((avg_pace - minutes) * 60)
                return f"{minutes:02d}:{seconds:02d}/km"
        return '--:--/km'

    def _monthly_stats(self, df: pd.DataFrame) -> pd.DataFrame:
        """月度统计"""
        df_copy = df.copy()
        df_copy['year_month'] = df_copy['date'].dt.to_period('M')

        monthly = df_copy.groupby('year_month').agg(
            activities=('date', 'count'),
            distance_km=('distance', 'sum'),
            duration_min=('duration_min', 'sum') if 'duration_min' in df_copy.columns else ('date', 'sum'),
            avg_hr=('avg_hr', 'mean') if 'avg_hr' in df_copy.columns else ('date', 'mean'),
            avg_pace=('pace_min_per_km', 'mean') if 'pace_min_per_km' in df_copy.columns else ('date', 'mean'),
        ).reset_index()

        monthly['year_month'] = monthly['year_month'].astype(str)
        return monthly

    def _weekly_stats(self, df: pd.DataFrame) -> pd.DataFrame:
        """周统计 (按 ISO 周)"""
        df_copy = df.copy()
        df_copy['year_week'] = df_copy['date'].dt.isocalendar().year.astype(str) + '-W' + df_copy['date'].dt.isocalendar().week.astype(str).str.zfill(2)

        weekly = df_copy.groupby('year_week').agg(
            activities=('date', 'count'),
            distance_km=('distance', 'sum'),
            duration_min=('duration_min', 'sum') if 'duration_min' in df_copy.columns else ('date', 'sum'),
        ).reset_index()

        return weekly

    def _pace_trend(self, df: pd.DataFrame) -> dict:
        """配速趋势分析"""
        if 'pace_min_per_km' not in df.columns:
            return {'error': '无配速数据'}

        df_sorted = df.sort_values('date')
        recent_10 = df_sorted.tail(10)

        return {
            'recent_avg_pace': self._avg_pace_str(recent_10),
            'overall_avg_pace': self._avg_pace_str(df),
            'trend': self._calculate_trend(df_sorted),
        }

    def _calculate_trend(self, df: pd.DataFrame) -> str:
        """计算趋势 (提升/持平/下降)"""
        if len(df) < 5:
            return '数据不足'

        n = len(df)
        first_half = df.iloc[:n // 2]['pace_min_per_km'].mean()
        second_half = df.iloc[n // 2:]['pace_min_per_km'].mean()

        if pd.isna(first_half) or pd.isna(second_half):
            return '数据不足'

        diff = second_half - first_half
        if abs(diff) < 0.1:  # 10 秒以内视为持平
            return '持平 ➡️'
        elif diff < 0:
            return f'提升 📈 (配速降低 {abs(diff):.1f} min/km)'
        else:
            return f'下降 📉 (配速增加 {diff:.1f} min/km)'

    def _hr_zone_summary(self, df: pd.DataFrame) -> dict:
        """心率区间汇总 (基于平均心率)"""
        if 'avg_hr' not in df.columns or self.max_hr is None:
            return {'error': '需要心率数据和最大心率'}

        zones = {}
        for zone_name, zone_config in HEART_RATE_ZONES.items():
            min_hr = self.max_hr * zone_config['min_pct']
            max_hr = self.max_hr * zone_config['max_pct']

            count = len(df[(df['avg_hr'] >= min_hr) & (df['avg_hr'] < max_hr)])
            pct = round(count / len(df) * 100, 1) if len(df) > 0 else 0

            zones[zone_name] = {
                'hr_range': f"{int(min_hr)}-{int(max_hr)} bpm",
                'count': count,
                'percentage': pct,
                'color': zone_config['color'],
                'emoji': zone_config['emoji'],
            }

        return zones

    def _pace_distribution(self, df: pd.DataFrame) -> dict:
        """配速等级分布"""
        if 'pace_min_per_km' not in df.columns:
            return {'error': '无配速数据'}

        distribution = {}
        for level_name, level_config in PACE_LEVELS.items():
            mask = (df['pace_min_per_km'] < level_config['max']) & \
                   (df['pace_min_per_km'] >= (list(PACE_LEVELS.values())[list(PACE_LEVELS.keys()).index(level_name) - 1]['max']
                    if list(PACE_LEVELS.keys()).index(level_name) > 0 else 0))
            count = mask.sum()
            pct = round(count / len(df) * 100, 1) if len(df) > 0 else 0

            distribution[level_name] = {
                'count': int(count),
                'percentage': pct,
                'emoji': level_config['emoji'],
            }

        return distribution

    def _best_performances(self, df: pd.DataFrame) -> dict:
        """最佳成绩"""
        best = {}

        # 最短配速 (5km+ 距离)
        if 'pace_min_per_km' in df.columns:
            long_runs = df[df['distance'] >= 5]
            if not long_runs.empty:
                best_pace_idx = long_runs['pace_min_per_km'].idxmin()
                best['fastest_5k_pace'] = {
                    'pace': long_runs.loc[best_pace_idx, 'pace_min_per_km'],
                    'pace_str': f"{int(long_runs.loc[best_pace_idx, 'pace_min_per_km'])}:{int((long_runs.loc[best_pace_idx, 'pace_min_per_km'] % 1) * 60):02d}",
                    'date': long_runs.loc[best_pace_idx, 'date'].strftime('%Y-%m-%d'),
                    'distance': long_runs.loc[best_pace_idx, 'distance'],
                }

        # 最长距离
        if 'distance' in df.columns:
            longest_idx = df['distance'].idxmax()
            best['longest_run'] = {
                'distance': df.loc[longest_idx, 'distance'],
                'date': df.loc[longest_idx, 'date'].strftime('%Y-%m-%d'),
            }

        # 最高心率
        if 'max_hr' in df.columns:
            best['max_hr'] = {
                'value': int(df['max_hr'].max()),
                'date': df.loc[df['max_hr'].idxmax(), 'date'].strftime('%Y-%m-%d'),
            }

        return best
