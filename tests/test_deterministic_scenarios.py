"""确定性场景测试（PRD 6.2）。

以结构化 analysis_data、指标和关键文案为主，不要求 Plotly HTML 字节一致。
"""

import pandas as pd
import pytest

import main
from main import LLM_PROMPT_VERSION, REQUIRED_LLM_SECTIONS
from src.config import HR_ZONE_PERCENTAGES, USER_CONFIG
from src.deep_analyzer import DeepRunAnalyzer
from conftest import CACHE_LLM_DIR, PROJECT_ROOT


def _analyze(df, date_str):
    row = df[df['date'].dt.date == pd.Timestamp(date_str).date()].iloc[0]
    az = DeepRunAnalyzer(df, target_date=row['date'],
                         max_hr=188, resting_hr=60)
    return row, az.analyze(row)


# ------------------------------------------------------------------
# 场景 1：2026-11-06 携带附录原体感的最新深析缓存
# ------------------------------------------------------------------
def test_2026_11_06_latest_deep_analysis():
    cache = (CACHE_LLM_DIR / 'llm_659451010.md').read_text(encoding='utf-8')
    body = cache.split('\n', 4)[4]  # 去 frontmatter

    # 六小节完整且顺序正确
    pos = 0
    for sec in REQUIRED_LLM_SECTIONS:
        idx = body.find(sec, pos)
        assert idx != -1, f"缺少小节: {sec}"
        pos = idx + len(sec)

    # BRIEF 块存在
    assert '<<<BRIEF>>>' in body and '<<<END>>>' in body

    # 无「预期配速」旧字样、无机械「关键发现」区块
    assert '预期配速' not in body
    assert '关键发现' not in body

    # user_note_hash 与附录体感一致（PRD 附录原文的 sha256）
    note = ("连续出差+应酬，导致不仅训练进度滞后，还拉跨了运动状态。今天一起步就感觉心率不对，"
            "一直找不到状态。第4公里开始4:55节奏，原来想坚持下看看能不能跑8KM的节奏跑，"
            "但坚持了6KM节奏跑配速之后，感觉不太行了。剩余6KM恢复跑，一时也没找到节奏，"
            "一直到最后4KM开始，慢慢找回状态，但感觉仍然比上周状态差。目前计划明后天跑一次有氧慢跑，"
            "找找状态，如果状态找回，下周二三再试一次节奏跑。")
    assert cache.split('\n')[0].split(': ', 1)[1] == main._user_note_hash(note)


# ------------------------------------------------------------------
# 场景 2：2026-09-24 热天轻松跑，既有结论不回归
# ------------------------------------------------------------------
def test_2026_09_24_hot_easy_run(df):
    row, data = _analyze(df, '2026-09-24')
    # 热天（28-30°C）轻松跑
    assert row['category'] == 'easy_run'
    assert row['min_temperature'] >= 25
    # 既有结论：热环境下心率漂移是主要现象，能力性结论稳定（长期趋势「稳定」同温区口径）
    comp = data['comparison']
    assert comp['long_term']['window_days'] == 180
    assert comp['long_term']['verdict'] == '稳定'
    assert comp['long_term']['baseline_scope'] == 'same_temp'
    assert comp['short_term']['sample_size'] >= 10
    # 该次无确定性问题回归（历史结论：热负荷现象，非能力退步）
    assert data['issues'] == []


# ------------------------------------------------------------------
# 场景 3：2026-10-22 凉爽天轻松跑，180 天全量回归，不得「样本不足」
# ------------------------------------------------------------------
def test_2026_10_22_cool_easy_run(df):
    row, data = _analyze(df, '2026-10-22')
    assert row['category'] == 'easy_run'
    lt = data['comparison']['long_term']
    assert lt['window_days'] == 180
    assert lt['verdict'] != '数据不足'
    assert lt['verdict'] == '进步'
    # 全量回归给出斜率，而非样本不足
    trend = lt.get('trend', {})
    assert 'hr_slope_per_month' in trend
    assert 'pace_slope_per_month' in trend


# ------------------------------------------------------------------
# 场景 4：2026-10-25 30.13 km LSD，「全部 LSD 同池对比」，月度护栏 ≥1/月
# ------------------------------------------------------------------
def test_2026_10_25_lsd(df):
    row, data = _analyze(df, '2026-10-25')
    assert row['category'] == 'lsd'
    assert abs(row['distance'] - 30.13) < 0.01
    # LSD 豁免温度过滤：长期基线为 no_temp 同池口径
    lt = data['comparison']['long_term']
    assert lt['baseline_scope'] == 'no_temp'
    assert lt['verdict'] != '数据不足'
    # 月度护栏 ≥1/月：180 天窗口的月度样本充足，全量回归有斜率
    assert 'hr_slope_per_month' in lt.get('trend', {})


def test_2026_10_25_lsd_baseline_note(df):
    """分圈历史基线标注「全部 LSD N 次」同池口径"""
    from src.data_fetcher import GarminDataFetcher
    row = df[df['date'].dt.date == pd.Timestamp('2026-10-25').date()].iloc[0]
    fetcher = GarminDataFetcher(state_file=str(PROJECT_ROOT / 'data' / 'last_fetch.json'))
    recent_laps, note = main._load_similar_lap_history(
        df, row['category'], pd.Timestamp(row['date']),
        row['activity_id'], 100, fetcher)
    fetcher.close()
    assert note.startswith('全部 LSD')
    assert len(recent_laps) > 0


# ------------------------------------------------------------------
# 场景 5：历史对比不得使用目标活动之后的数据
# ------------------------------------------------------------------
def test_history_excludes_future_data(df):
    from src.data_fetcher import GarminDataFetcher
    row = df[df['date'].dt.date == pd.Timestamp('2026-10-22').date()].iloc[0]
    target_ts = pd.Timestamp(row['date'])
    fetcher = GarminDataFetcher(state_file=str(PROJECT_ROOT / 'data' / 'last_fetch.json'))
    recent_laps, _ = main._load_similar_lap_history(
        df, row['category'], target_ts, row['activity_id'], 100, fetcher)
    fetcher.close()
    assert recent_laps
    for laps in recent_laps:
        for lap in laps:
            src_id = lap.get('activity_id')
            src = df[df['activity_id'] == src_id]
            assert not src.empty
            assert pd.Timestamp(src.iloc[0]['date']) <= target_ts


# ------------------------------------------------------------------
# 场景 6：max_hr=188、resting_hr=60、Karvonen HRR 口径不变
# ------------------------------------------------------------------
def test_hr_zone_karvonen_config_unchanged():
    assert USER_CONFIG['max_hr'] == 188
    assert USER_CONFIG['resting_hr'] == 60
    # HRR 区间百分比固定
    assert HR_ZONE_PERCENTAGES['Z2']['min_pct'] == 0.74
    assert HR_ZONE_PERCENTAGES['Z2']['max_pct'] == 0.84
    assert HR_ZONE_PERCENTAGES['Z5']['min_pct'] == 0.94

    from src.classifier import HeartRateClassifier
    hrc = HeartRateClassifier(188, 60)
    hrr = 188 - 60  # 128
    # Z2 上限 = resting + 0.84 * HRR；下限因连续化规则 = Z1 上限 + 1
    assert hrc.ZONES['Z1']['range'][1] == int(60 + 0.74 * hrr)
    assert hrc.ZONES['Z2']['range'] == (hrc.ZONES['Z1']['range'][1] + 1, int(60 + 0.84 * hrr))


def test_prompt_version_unchanged():
    """仅更换执行平台，Prompt 版本保持 12"""
    assert LLM_PROMPT_VERSION == 12
