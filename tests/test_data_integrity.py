"""数据完整性测试（PRD 6.1）

口径：固定迁移基线 + 已验证增量。
- MIGRATION_BASELINE 是迁移验收时逐项核实的数量，不得改动；
- VERIFIED_INCREMENTS 是每次正式 fetch-new 验收通过后登记的增量活动。
测试断言「当前数据 == 基线 + 已登记增量」，执行期间出现的新活动应先走隔离验证、
正式写入后登记到这里，而不是把新数字硬编码进断言。
"""

import pandas as pd

from conftest import CACHE_LLM_DIR, DEEP_DIR, PROJECT_ROOT

# 固定迁移基线（2026-11-06 验收时核实）
MIGRATION_BASELINE = {
    'cache_activities': 153,   # 原始活动缓存
    'main_rows': 150,          # 分析主表
    'lap_rows': 2740,          # 分圈数据
    'deep_html': 94,           # 历史深析 HTML（PRD 记录 95，经核实 95 含 cache 目录项）
    'llm_cache': 22,           # LLM 缓存
    'max_date': '2026-11-06',  # 主表最晚活动日期
}

# 已验证增量：正式写入并逐字段验收通过的活动（id、日期、分圈行数）
VERIFIED_INCREMENTS = [
    {'activity_id': 660164388, 'date': '2026-11-08', 'lap_rows': 17},
]


def _increments_present(ids) -> list[dict]:
    id_set = {str(x) for x in ids}
    return [i for i in VERIFIED_INCREMENTS if str(i['activity_id']) in id_set]


def test_activities_cache_count(activities_cache):
    """原始活动缓存 == 基线 + 已验证增量数"""
    ids = {str(_aid(a)) for a in activities_cache}
    assert len(activities_cache) == MIGRATION_BASELINE['cache_activities'] + len(ids & _inc_ids())


def test_main_table_shape(df):
    """主表行数/唯一 id == 基线 + 已验证增量；列数不变"""
    inc = _increments_present(df['activity_id'].astype(str))
    assert len(df) == MIGRATION_BASELINE['main_rows'] + len(inc)
    assert df['activity_id'].nunique() == MIGRATION_BASELINE['main_rows'] + len(inc)
    assert len(df.columns) == 62


def test_lap_data_integrity(lap_df, df):
    """分圈行数 == 基线 + 已验证增量分圈；覆盖主表全部活动"""
    inc = _increments_present(df['activity_id'].astype(str))
    expected = MIGRATION_BASELINE['lap_rows'] + sum(i['lap_rows'] for i in inc)
    assert len(lap_df) == expected
    assert lap_df['activity_id'].nunique() == df['activity_id'].nunique()
    assert set(lap_df['activity_id'].astype(str)) == set(df['activity_id'].astype(str))


def test_three_filtered_records_absent(df, activities_cache):
    """三个过滤记录继续缺席主表，且缺席原因符合原规则：
    1 次 138.85 km 超长记录 + 2 次标题含「间歇跑」"""
    dist_filtered = [a for a in activities_cache if _dist_km(a) > 50]
    title_filtered = [a for a in activities_cache if '间歇跑' in _title(a)]
    assert len(dist_filtered) == 1
    assert abs(_dist_km(dist_filtered[0]) - 138.85) < 0.01
    assert len(title_filtered) == 2

    in_table = set(df['activity_id'].astype(str))
    for a in dist_filtered + title_filtered:
        assert str(_aid(a)) not in in_table


def test_historical_assets_count(df):
    """历史深析 HTML / LLM 缓存 == 基线 + 已验证增量；外部 PRD 数固定"""
    deep_html = list(DEEP_DIR.glob('run_analysis_*.html'))
    inc = _increments_present(df['activity_id'].astype(str))
    assert len(deep_html) == MIGRATION_BASELINE['deep_html'] + len(inc)
    # 每个已验证增量都应有对应的深析 HTML
    for i in inc:
        assert list(DEEP_DIR.glob(f"run_analysis_*_{i['activity_id']}.html")), \
            f"缺增量深析: {i['activity_id']}"
    llm_caches = list(CACHE_LLM_DIR.glob('llm_*.md'))
    assert len(llm_caches) == MIGRATION_BASELINE['llm_cache'] + len(inc)
    for i in inc:
        assert (CACHE_LLM_DIR / f"llm_{i['activity_id']}.md").exists(), \
            f"缺增量 LLM 缓存: {i['activity_id']}"
    assert len(list((PROJECT_ROOT / 'docs' / 'prd' / 'external').glob('*.md'))) == 16


def test_data_date_range(df):
    """数据起点固定；终点 == max(基线日期, 已验证增量最晚日期)"""
    assert df['date'].min().strftime('%Y-%m-%d') == '2025-10-24'
    expected_max = max([MIGRATION_BASELINE['max_date']] + [i['date'] for i in VERIFIED_INCREMENTS])
    assert df['date'].max().strftime('%Y-%m-%d') == expected_max


# ------------------------------------------------------------------
# 工具函数（与原测试同口径）
# ------------------------------------------------------------------
def _aid(a: dict):
    return (a.get("activity_id") or a.get("activityId") or
            a.get("id") or a.get("activityID") or 0)


def _inc_ids() -> set[str]:
    return {str(i['activity_id']) for i in VERIFIED_INCREMENTS}


def _dist_km(a: dict) -> float:
    d = a.get('distance') or (a.get('summaryDTO') or {}).get('distance') or 0
    return d / 1000.0


def _title(a: dict) -> str:
    return a.get('activityName') or (a.get('summaryDTO') or {}).get('activityName') or ''
