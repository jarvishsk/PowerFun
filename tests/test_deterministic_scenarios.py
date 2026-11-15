"""确定性场景测试（PRD 6.2）。

以结构化 analysis_data、指标和关键文案为主，不要求 Plotly HTML 字节一致。
"""

import pandas as pd
import pytest

import main
from main import LLM_PROMPT_VERSION, REQUIRED_LLM_SECTIONS
from src.activity_overrides import apply_activity_overrides
from src.config import HR_ZONE_PERCENTAGES, USER_CONFIG
from src.deep_analyzer import DeepRunAnalyzer
from conftest import CACHE_LLM_DIR, PROJECT_ROOT


def _analyze(df, date_str):
    """统一报告口径：先应用人工课型覆盖（5.0 第一批 F1），加载分圈后分析"""
    df = apply_activity_overrides(df)
    row = df[df['date'].dt.date == pd.Timestamp(date_str).date()].iloc[0]
    from src.data_fetcher import GarminDataFetcher
    fetcher = GarminDataFetcher(state_file=str(PROJECT_ROOT / 'data' / 'last_fetch.json'))
    try:
        laps = fetcher._load_lap_cache(row['activity_id'])
    finally:
        fetcher.close()
    az = DeepRunAnalyzer(df, target_date=row['date'],
                         max_hr=188, resting_hr=60, raw_laps=laps)
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
    # 该次能力性结论不回归（长期趋势同温区口径）
    # 断言更新（旧值→新值→依据）：「稳定」→「趋势待确认」+ verdict_allowed=False
    # ——验收阻断二修正：全量阈值内（stable 类）指标同样消费逐月剔除敏感性；
    # 该次配速全量斜率 -0.86 秒/月在阈值内，但逐月剔除方向不稳（LOO -2.47~+4.05），
    # 稳定结论依法降级为「趋势待确认」，理由须标明敏感指标。
    comp = data['comparison']
    assert comp['long_term']['window_days'] == 180
    assert comp['long_term']['verdict'] == '趋势待确认'
    assert comp['long_term']['verdict_allowed'] is False
    assert comp['long_term']['baseline_scope'] == 'same_temp'
    assert comp['long_term']['loo_unstable_stable'] == ['pace']
    assert '配速' in comp['long_term']['evidence_reason']
    assert '逐月剔除' in comp['long_term']['evidence_reason']
    assert comp['short_term']['sample_size'] >= 10
    # 5.0 第一批 F3：负向漂移修复后，热天整场 -7.9% 漂移被正确报告
    # （旧 >+5% 探测器漏报所有负向漂移；该次历史结论本就是「热负荷现象」，现在能出确定性信号）
    drift = [i for i in data['issues'] if '心率漂移' in i['title']]
    assert len(drift) == 1
    assert '-7.9%' in drift[0]['title'] and '阈值 -5%' in drift[0]['title']
    assert not any('强度偏离课型' in i['title'] for i in data['issues'])


# ------------------------------------------------------------------
# 场景 3：2026-10-22 凉爽天轻松跑，180 天全量回归，不得「样本不足」
# ------------------------------------------------------------------
def test_2026_10_22_cool_easy_run(df):
    """10-22 轻松跑：全量回归给出斜率；实际 baseline_scope=all_temp，
    第二批 F2 后只作表现描述，不得输出能力「进步」（旧断言无条件「进步」作废）。

    旧预期 → 新预期 → 依据：
    verdict == '进步' → verdict == '能力证据不足' 且 verdict_allowed=False、
    evidence_level='descriptive'；依据 PRD 11.3（all_temp 只作描述）。
    """
    row, data = _analyze(df, '2026-10-22')
    assert row['category'] == 'easy_run'
    lt = data['comparison']['long_term']
    assert lt['window_days'] == 180
    assert lt['baseline_scope'] == 'all_temp'
    # 全量回归给出斜率，而非样本不足
    trend = lt.get('trend', {})
    assert 'hr_slope_per_month' in trend
    assert 'pace_slope_per_month' in trend
    # 第二批 F2：跨温区参照池不输出能力 verdict
    assert lt['verdict'] == '能力证据不足'
    assert lt['verdict_allowed'] is False
    assert lt['evidence_level'] == 'descriptive'
    assert '未排除温度影响' in lt['evidence_reason']
    # 敏感性结构存在（描述级保留）
    assert 'hr' in (lt.get('sensitivity') or {})
    assert lt.get('monthly_points')


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
    # 第二批 F2：全部 LSD 同池不输出能力 verdict，只作表现描述（PRD 11.2）
    assert lt['verdict'] == '能力证据不足'
    assert lt['verdict_allowed'] is False
    assert lt['evidence_level'] == 'descriptive'


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


def test_prompt_version_unchanged_for_baseline_data_changes():
    """仅基线数据变化不升 Prompt 结构版本，避免历史点评缓存全部失效。
    当前为 14（旧值 13 → 新值 14：5.0.2 PRD 10.3 比赛参照/技术语义/比赛计划/点评指令变更要求 13→14）。"""
    assert LLM_PROMPT_VERSION == 14


def test_2026_11_12_reference_pools_expand_beyond_small_same_temp(df):
    """11-12 轻松跑（661585068）：未覆盖活动口径不变；656543045 退出轻松跑参照池后短期 14→13。"""
    row, data = _analyze(df, '2026-11-12')
    assert row['activity_id'] == 661585068
    # 普通课型无人工覆盖：分类与来源保持自动口径
    assert row['category'] == 'easy_run'
    assert row['category_auto'] == 'easy_run'
    assert row['category_source'] == 'auto'
    # 普通课型 Pa:Hr 保持整场 +0.92%（PRD 9.4）
    pa = data['pa_hr']
    assert pa['scope'] == 'full_activity'
    assert abs(pa['pa_hr_pct'] - 0.92) < 0.01

    comparison = data['comparison']
    assert comparison['sample_size'] == 15
    assert comparison['baseline_scope'] == 'all_temp'

    short = comparison['short_term']
    assert short['window_days'] == 60
    assert short['baseline_scope'] == 'all_temp'
    # 656543045（10-29，原误分轻松跑）退出轻松跑池：14 → 13，配速方向 持平 → 更快（PRD 9.4）
    assert short['sample_size'] == 13
    assert short['verdict_pace'] == '更快'

    percentile = comparison['percentile']
    assert percentile['sample_size'] == 30
    # 长期池 57 → 56，效率排名 P70 → P73（PRD 9.4）
    assert percentile['value'] == 73
    assert comparison['long_term']['sample_size'] == 56


# ------------------------------------------------------------------
# 场景 7（5.0 第一批 PRD 9.1/9.2/9.3）：人工课型与 Pa:Hr 双轨回放
# ------------------------------------------------------------------
def test_2026_11_06_tempo_manual_segment_negative_drift(df):
    """659451010：人工节奏跑，只算第 4—9 圈，-6.14% 触发负向漂移（PRD 9.1）"""
    row, data = _analyze(df, '2026-11-06')
    assert row['activity_id'] == 659451010
    assert row['category'] == 'tempo_run'
    assert row['category_auto'] == 'aerobic_run'
    assert row['category_source'] == 'manual'
    assert row['category_name'] == '节奏跑'
    pa = data['pa_hr']
    assert pa['scope'] == 'manual_segment'
    assert pa['segment_laps'] == [4, 9]
    assert abs(pa['pa_hr_pct'] - (-6.14)) < 0.01
    assert abs(pa['first_half_pace'] - 295) < 1
    assert abs(pa['second_half_pace'] - 295) < 1
    assert abs(pa['first_half_hr'] - 168.0) < 0.1
    assert abs(pa['second_half_hr'] - 179.0) < 0.1
    drift = [i for i in data['issues'] if '心率漂移' in i['title']]
    assert len(drift) == 1
    assert '阈值 -5%' in drift[0]['title']
    # 原「有氧耐力课 Z4+ 超标」不再出现；无同类型基线可排名
    assert not any('强度偏离课型' in i['title'] for i in data['issues'])
    assert data['comparison'].get('sample_size', 0) == 0
    assert data['comparison'].get('percentile') is None


def test_2026_11_09_tempo_manual_segment_no_drift(df):
    """660460268：人工节奏跑，只算第 5—11 圈，-4.12% 不触发 5% 漂移（PRD 9.2）"""
    row, data = _analyze(df, '2026-11-09')
    assert row['activity_id'] == 660460268
    assert row['category'] == 'tempo_run'
    assert row['category_source'] == 'manual'
    pa = data['pa_hr']
    assert pa['scope'] == 'manual_segment'
    assert pa['segment_laps'] == [5, 11]
    assert abs(pa['pa_hr_pct'] - (-4.12)) < 0.01
    assert abs(pa['first_half_pace'] - 290) < 1
    assert abs(pa['second_half_pace'] - 291) < 1
    assert abs(pa['first_half_hr'] - 169.1) < 0.1
    assert abs(pa['second_half_hr'] - 175.7) < 0.1
    assert not any('心率漂移' in i['title'] for i in data['issues'])
    # 负荷激增与最大心率异常信号保持
    assert any('负荷激增' in i['title'] for i in data['issues'])
    assert any('心率异常' in i['title'] for i in data['issues'])


def test_2026_10_29_intensity_not_applicable(df):
    """656543045：人工间歇跑，Pa:Hr 不适用，不得回退整场 -2.95%（PRD 9.3）"""
    row, data = _analyze(df, '2026-10-29')
    assert row['activity_id'] == 656543045
    assert row['category'] == 'intensity_run'
    assert row['category_auto'] == 'easy_run'
    assert row['category_source'] == 'manual'
    assert row['category_name'] == '间歇跑'
    assert data['pa_hr'] is None
    ctx = data['pa_hr_context']
    assert ctx['scope'] == 'not_applicable'
    assert ctx['reason'] == 'interval_not_applicable'
    # 不再出现轻松跑强度偏离提示
    assert not any('强度偏离课型' in i['title'] for i in data['issues'])


# ------------------------------------------------------------------
# 场景 8（5.0 第一批 PRD 9.5）：普通课型回归——LSD、比赛、有氧耐力跑口径不变
# ------------------------------------------------------------------
NORMAL_REGRESSION_PICKS = {
    'lsd': 657594960,           # 2026-11-01 LSD
    'race_event': 652143123,    # 2026-10-18 其他赛事
    'aerobic_run': 648829680,   # 2026-10-09 有氧耐力跑（未被人工覆盖）
}


def test_normal_categories_pa_hr_unchanged(df):
    """普通课型：category 与自动分类一致、来源 auto、Pa:Hr 整场且数值与修改前一致"""
    from src.data_fetcher import GarminDataFetcher

    overridden = apply_activity_overrides(df)
    fetcher = GarminDataFetcher(state_file=str(PROJECT_ROOT / 'data' / 'last_fetch.json'))
    try:
        for category, aid in NORMAL_REGRESSION_PICKS.items():
            row = overridden[overridden['activity_id'] == aid].iloc[0]
            # 分类与修改前一致，无人工来源或工作段标记
            assert row['category'] == category, f"{aid} 课型被意外改变"
            assert row['category_auto'] == category
            assert row['category_source'] == 'auto'
            assert pd.isna(row['pa_hr_lap_start']) and pd.isna(row['pa_hr_lap_end'])

            laps = fetcher._load_lap_cache(aid)
            assert laps, f"{aid} 缺分圈数据"
            az = DeepRunAnalyzer(overridden, target_date=row['date'],
                                 max_hr=188, resting_hr=60, raw_laps=laps)
            data = az.analyze(row)
            pa = data['pa_hr']
            # Pa:Hr 输入为完整有效分圈，数值与直接整场计算一致
            assert pa['scope'] == 'full_activity'
            assert pa['segment_laps'] is None
            direct = az._calc_pa_hr(laps)
            assert pa['pa_hr_pct'] == direct['pa_hr_pct'], f"{aid} Pa:Hr 数值改变"
    finally:
        fetcher.close()
