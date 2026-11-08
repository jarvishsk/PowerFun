"""数据完整性测试（PRD 6.1）"""

import json
from pathlib import Path

import pandas as pd

from conftest import DATA_DIR, CACHE_LLM_DIR, DEEP_DIR, PROJECT_ROOT


def test_activities_cache_count(activities_cache):
    """原始活动缓存 153 次"""
    assert len(activities_cache) == 153


def test_main_table_shape(df):
    """主表 150 行、150 个唯一 activity_id、62 列"""
    assert len(df) == 150
    assert df['activity_id'].nunique() == 150
    assert len(df.columns) == 62


def test_lap_data_integrity(lap_df, df):
    """分圈 2,740 行、覆盖 150 个 activity_id"""
    assert len(lap_df) == 2740
    assert lap_df['activity_id'].nunique() == 150
    assert set(lap_df['activity_id'].unique()) == set(df['activity_id'].unique())


def test_three_filtered_records_absent(df, activities_cache):
    """三个过滤记录继续缺席主表，且缺席原因符合原规则：
    1 次 138.85 km 超长记录 + 2 次标题含「间歇跑」"""
    def _get_id(a):
        return (a.get("activity_id") or a.get("activityId") or
                a.get("id") or a.get("activityID") or 0)

    def _dist_km(a):
        d = a.get('distance') or (a.get('summaryDTO') or {}).get('distance') or 0
        return d / 1000.0

    def _title(a):
        return a.get('activityName') or (a.get('summaryDTO') or {}).get('activityName') or ''

    dist_filtered = [a for a in activities_cache if _dist_km(a) > 50]
    title_filtered = [a for a in activities_cache if '间歇跑' in _title(a)]
    assert len(dist_filtered) == 1
    assert abs(_dist_km(dist_filtered[0]) - 138.85) < 0.01
    assert len(title_filtered) == 2

    in_table = set(df['activity_id'].astype(str))
    for a in dist_filtered + title_filtered:
        assert str(_get_id(a)) not in in_table


def test_historical_assets_count():
    """历史深析 HTML 94 份（PRD 记录为 95，经核实 95 含 cache 目录项）、LLM 缓存 22 份、外部 PRD 16 份"""
    deep_html = list(DEEP_DIR.glob('run_analysis_*.html'))
    assert len(deep_html) == 94
    assert len(list(CACHE_LLM_DIR.glob('llm_*.md'))) == 22
    assert len(list((PROJECT_ROOT / 'docs' / 'prd' / 'external').glob('*.md'))) == 16


def test_data_date_range(df):
    """数据时间范围 2025-10-24 至 2026-11-06"""
    assert df['date'].min().strftime('%Y-%m-%d') == '2025-10-24'
    assert df['date'].max().strftime('%Y-%m-%d') == '2026-11-06'
