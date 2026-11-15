"""统计证据门槛测试（5.0 第二批 PRD 第 10 节：F1 短期 / F2-F3 长期与敏感性 / F4 同比 / F5 百分位）

全部使用合成数据直接驱动 DeepRunAnalyzer 的确定性内核；
HTML 证据通过 AnalysisReportGenerator 渲染到 pytest 临时目录，不写正式 reports/。
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.deep_analyzer import (DeepRunAnalyzer, LLMReportGenerator, PERCENTILE_MIN_VALID,
                               SHORT_TERM_WINDOW_DAYS, YOY_METRIC_MIN_SAMPLES,
                               YOY_MIN_MONTHS)

TARGET_DATE = '2026-11-10'
# 合成温度：min 22 / max 26 → 中值 24 → mild 桶（15-25℃）
MILD = (22.0, 26.0)


def _row(aid, date, category='easy_run', hr=150.0, pace=300.0, temp=MILD,
         distance=10.0):
    d = {'activity_id': aid, 'date': date, 'category': category,
         'avg_hr': hr, 'avg_pace_sec': pace, 'distance': distance,
         'min_temperature': temp[0], 'max_temperature': temp[1]}
    return d


def _df(rows):
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df['_category_norm'] = df['category']
    return df


def _target(category='easy_run', hr=160.0, pace=310.0, temp=MILD):
    return pd.Series(_row(999, TARGET_DATE, category=category, hr=hr, pace=pace, temp=temp))


def _analyzer(df, target=None):
    t = target if target is not None else _target()
    return DeepRunAnalyzer(df, target_date=pd.Timestamp(TARGET_DATE),
                           max_hr=188, resting_hr=60), t


def _short(n, category='easy_run', hr=150.0, pace=300.0, temp=MILD, spread=0.0):
    """构造近 60 天内 n 次同温区历史（默认与目标同桶），目标为 n+1 号"""
    base = pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=30)
    rows = [_row(i + 1, base + pd.Timedelta(days=i * 3), category=category,
                 hr=hr + (i % 2) * spread, pace=pace + (i % 3) * spread, temp=temp)
            for i in range(n)]
    return _df(rows)


# ------------------------------------------------------------------
# F1 短期：n<3 数据不足 / 3≤n<5 仅作描述 / n≥5 方向 verdict / 单指标独立降级
# ------------------------------------------------------------------
def test_short_n2_insufficient():
    az, t = _analyzer(_short(2))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    assert st['sample_size'] == 2
    assert 'message' in st
    assert st['evidence_level'] == 'insufficient'
    assert st['verdict_allowed'] is False
    assert 'verdict_hr' not in st or st.get('verdict_hr') is None


@pytest.mark.parametrize('n', [3, 4])
def test_short_n3_n4_descriptive_no_verdict(n):
    az, t = _analyzer(_short(n))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    assert st['sample_size'] == n
    # 中位数与差值保留
    assert st['hr']['median'] is not None
    assert st['pace_median'] is not None
    assert st['hr_diff'] is not None
    assert st['pace_diff'] is not None
    # verdict 必须为 None，证据等级 descriptive
    assert st['verdict_hr'] is None
    assert st['verdict_pace'] is None
    assert st['verdict_efficiency'] is None
    assert st['verdict_allowed'] is False
    assert st['evidence_level'] == 'descriptive'
    assert '样本有限' in st['evidence_reason']


def test_short_n5_directional_thresholds():
    # 目标心率 160 vs 基线 150（+10 > +3 → 更累）；配速 310 vs 300（+10 > +5 → 更慢）
    az, t = _analyzer(_short(5))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    assert st['sample_size'] == 5
    assert st['verdict_allowed'] is True
    assert st['evidence_level'] == 'directional'
    assert st['verdict_hr'] == '更累'
    assert st['verdict_pace'] == '更慢'
    assert st['hr_diff'] == pytest.approx(10.0, abs=0.6)
    assert st['pace_diff'] == pytest.approx(10.0, abs=0.6)


def test_short_n5_eff_diff_direction():
    # 目标效率显著高于基线 → 更经济（效率阈值 ±3）
    rows = [_row(i + 1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10 + i * 5),
                 hr=150, pace=330) for i in range(5)]
    az, t = _analyzer(_df(rows), _target(hr=145, pace=300))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    assert st['verdict_efficiency'] == '更经济'


def test_short_metric_independent_missing_downgrade():
    """总样本达标但某指标全部缺失：该指标无 verdict、差值为 None，其余指标正常"""
    rows = []
    for i in range(5):
        r = _row(i + 1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10 + i * 5),
                 hr=150, pace=300)
        r['avg_hr'] = np.nan  # 心率全缺失
        rows.append(r)
    az, t = _analyzer(_df(rows), _target(hr=160, pace=290))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    assert st['sample_size'] == 5
    assert st['hr_baseline'] is None and st['hr_diff'] is None
    assert st['verdict_hr'] is None            # 单指标降级
    assert st['verdict_pace'] == '更快'        # 配速指标不受影响
    assert st['verdict_allowed'] is True


def test_short_all_temp_scope_behavior_unchanged():
    """all_temp 短期基线选择行为不变：同桶 <3 时放宽全池，n≥5 仍给方向"""
    base = pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=30)
    rows = []
    # 同桶仅 2 次，另 3 次为 cold 桶 → all_temp n=5
    for i in range(2):
        rows.append(_row(i + 1, base + pd.Timedelta(days=i * 3), temp=MILD))
    for i in range(3):
        rows.append(_row(10 + i, base + pd.Timedelta(days=i * 4), temp=(5.0, 10.0)))
    az, t = _analyzer(_df(rows))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    assert st['baseline_scope'] == 'all_temp'
    assert st['sample_size'] == 5
    assert st['verdict_allowed'] is True


def test_short_no_temp_scope_behavior_unchanged():
    """LSD 短期仍直接不限温区池（no_temp），行为不变"""
    rows = [_row(i + 1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10 + i * 5),
                 category='lsd', hr=145, pace=330) for i in range(5)]
    az, t = _analyzer(_df(rows), _target(category='lsd', hr=145, pace=330))
    st = az._calc_short_term(t, 'lsd', 'mild', az.df_all)
    assert st['baseline_scope'] == 'no_temp'
    assert st['sample_size'] == 5
    assert st['verdict_allowed'] is True


# ------------------------------------------------------------------
# F1 输出一致性：Prompt 文本（_format_comparison 只消费内核结果）
# ------------------------------------------------------------------
DIRECTION_WORDS = ('更快', '更慢', '更轻松', '更累', '更经济', '更费力')


def _prompt_for(comparison):
    gen = LLMReportGenerator(pd.DataFrame())
    return gen._format_comparison(comparison)


def test_prompt_short_n3_descriptive_text():
    az, t = _analyzer(_short(3))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    text = _prompt_for({'short_term': st})
    assert '样本有限' in text and '仅作描述' in text
    # 禁令提示语本身列举方向词，剥除后再断言正文无方向 verdict
    body = text.replace('「更快/更慢/更轻松/更累/更经济/更费力」', '')
    for w in DIRECTION_WORDS:
        assert w not in body
    # 差值注入模型上下文
    assert '当前 160' in text
    assert '中位' in text


def test_prompt_short_n5_keeps_direction():
    az, t = _analyzer(_short(5))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    text = _prompt_for({'short_term': st})
    assert '更累' in text and '更慢' in text


# ------------------------------------------------------------------
# F2/F3 长期：月份护栏、跨温只作描述、same_temp 敏感性门槛
# ------------------------------------------------------------------
def _long_df(monthly, category='easy_run', temp=MILD, per_month=2):
    """monthly: [(month_offset_from_2026_07, hr, pace, extra_count)]"""
    rows = []
    aid = 1
    for m_off, hr, pace, extra in monthly:
        month = pd.Period('2026-07', freq='M') + m_off
        for i in range(per_month + extra):
            day = min(2 + i * 10, 28)
            rows.append(_row(aid, f'{month}-{day:02d}', category=category,
                             hr=hr, pace=pace, temp=temp))
            aid += 1
    return _df(rows)


def test_long_monthly_guard_normal_category():
    """普通课型每月 1 次不计入回归；months_available=进入回归的月份数"""
    # 4 个月：每月 1 次 + 两个月份各 +1 extra → 只有两个月达到 ≥2/月
    df = _long_df([(0, 150, 300, 0), (1, 150, 300, 1), (2, 150, 300, 1), (3, 150, 300, 0)],
                  per_month=1)
    az, t = _analyzer(df)
    lt = az._calc_long_term(t, 'easy_run', 'mild', az.df_all)
    assert lt['months_with_data'] == 4    # 四个月都有数据
    assert lt['months_available'] == 0    # 无月份进入回归（<3 有效月份）
    assert lt['verdict'] == '数据不足'
    assert lt['evidence_level'] == 'insufficient'


def test_long_months_available_counts_regression_months():
    df = _long_df([(0, 150, 300, 0), (1, 150, 300, 0), (2, 150, 300, 0), (3, 150, 300, 0)])
    # 每月 2 次 × 4 个月 = 8 次；第 0 月只有 2 次，全部月份 ≥2/月
    az, t = _analyzer(df)
    lt = az._calc_long_term(t, 'easy_run', 'mild', az.df_all)
    assert lt['months_available'] == 4
    assert lt['months_with_data'] == 4
    assert len(lt['monthly_points']) == 4
    p = lt['monthly_points'][0]
    assert {'month', 'count', 'hr_median', 'pace_median_sec', 'efficiency'} <= set(p)


def test_long_all_temp_descriptive_no_ability_verdict():
    """all_temp：斜率与月度点保留，但不得输出能力 verdict（第二批 F2）"""
    df = _long_df([(0, 155, 310, 1), (1, 153, 307, 1), (2, 151, 304, 1), (3, 148, 300, 1)])
    az, t = _analyzer(df)  # 目标 cool 桶 → 同桶 0 → all_temp
    lt = az._calc_long_term(t, 'easy_run', 'cool', az.df_all)
    assert lt['baseline_scope'] == 'all_temp'
    assert 'hr_slope_per_month' in lt['trend']
    assert lt['verdict'] == '能力证据不足'
    assert lt['verdict_allowed'] is False
    assert lt['evidence_level'] == 'descriptive'
    assert '未排除温度影响' in lt['evidence_reason']
    assert 'sensitivity' in lt and 'hr' in lt['sensitivity']


def test_long_same_temp_stable_verdict_allowed():
    """same_temp 且斜率在阈值内 → 稳定 verdict 允许（敏感性无方向可破坏）"""
    # 同桶 ≥10 次（每月 3 次 × 4 个月 = 12），心率/配速几乎平
    df = _long_df([(0, 150, 300, 1), (1, 150.5, 300.5, 1), (2, 150, 300, 1), (3, 150.5, 300, 1)],
                  temp=MILD)
    az, t = _analyzer(df)
    lt = az._calc_long_term(t, 'easy_run', 'mild', az.df_all)
    assert lt['baseline_scope'] == 'same_temp'
    assert lt['verdict'] == '稳定'
    assert lt['verdict_allowed'] is True
    assert lt['evidence_level'] == 'directional'


def test_long_same_temp_single_month_sensitive_becomes_trend_pending():
    """构造单月主导：全量有心率方向，但剔除关键月后方向改变 → 趋势待确认，不得退化为稳定"""
    # 前 3 个月心率 150 平，最后一个月骤降到 138（全量斜率负向=positive 类）
    df = _long_df([(0, 150, 300, 1), (1, 150, 300, 1), (2, 150, 300, 1), (3, 138, 300, 1)],
                  temp=MILD)
    az, t = _analyzer(df)
    lt = az._calc_long_term(t, 'easy_run', 'mild', az.df_all)
    assert lt['baseline_scope'] == 'same_temp'
    # 心率方向指标存在（月降超过 1bpm/月阈值）
    assert lt['trend']['hr_slope_per_month'] < -1.0
    assert lt['sensitivity']['hr']['direction_stable'] is False
    # 若全部方向指标对单月敏感 → 趋势待确认
    assert lt['verdict'] == '趋势待确认'
    assert lt['verdict_allowed'] is False
    assert '敏感' in lt['evidence_reason']


def test_long_same_temp_sensitive_metric_excluded_from_reason():
    """部分指标敏感、部分稳定：稳定指标支撑 verdict，敏感指标在理由中标注未纳入"""
    # 心率：最后月骤降（敏感）；配速：全程稳定下降（每月 -2 秒/月，稳定超过 ±2 阈值边缘 → 构造 -3）
    df = _long_df([(0, 150, 306, 1), (1, 150, 303, 1), (2, 150, 300, 1), (3, 138, 297, 1)],
                  temp=MILD)
    az, t = _analyzer(df)
    lt = az._calc_long_term(t, 'easy_run', 'mild', az.df_all)
    assert lt['baseline_scope'] == 'same_temp'
    assert lt['sensitivity']['hr']['direction_stable'] is False
    if lt['sensitivity']['pace']['direction_stable']:
        assert lt['verdict'] in ('进步', '分化')
        assert lt['verdict_allowed'] is True
        assert '未纳入判断' in lt['reason']
    else:
        # 配速也敏感 → 趋势待确认
        assert lt['verdict'] == '趋势待确认'


def test_long_lsd_no_temp_pool_unchanged_monthly_guard():
    """LSD：no_temp 全池、每月≥1 可计入（第二批 F2 只禁 verdict，不缩池）"""
    rows = []
    for m_off in (0, 1, 2, 3):
        month = pd.Period('2026-07', freq='M') + m_off
        rows.append(_row(100 + m_off, f'{month}-05', category='lsd', hr=145, pace=340,
                         temp=(5.0, 10.0) if m_off % 2 else (30.0, 33.0)))  # 温区交替
    az, t = _analyzer(_df(rows), _target(category='lsd', hr=145, pace=340))
    lt = az._calc_long_term(t, 'lsd', 'mild', az.df_all)
    assert lt['baseline_scope'] == 'no_temp'
    assert lt['months_available'] == 4        # 每月≥1 规则不变
    assert 'hr_slope_per_month' in lt['trend']
    assert lt['verdict'] == '能力证据不足'     # no_temp 同样只作描述
    assert lt['verdict_allowed'] is False


def test_long_selection_order_unchanged():
    """同温区 ≥10 次时仍优先 same_temp（选择顺序不变）"""
    df = _long_df([(0, 150, 300, 2), (1, 150, 300, 2), (2, 150, 300, 2)],
                  temp=MILD)  # 3 个月 × 4 次 = 12 次同桶
    az, t = _analyzer(df)
    lt = az._calc_long_term(t, 'easy_run', 'mild', az.df_all)
    assert lt['baseline_scope'] == 'same_temp'


def test_prompt_long_all_temp_no_ability_verdict():
    df = _long_df([(0, 155, 310, 1), (1, 153, 307, 1), (2, 151, 304, 1), (3, 148, 300, 1)])
    az, t = _analyzer(df)
    lt = az._calc_long_term(t, 'easy_run', 'cool', az.df_all)
    text = _prompt_for({'long_term': lt})
    assert '不得解读为能力进步或退步' in text
    assert '月度中位点' in text
    assert '敏感性' in text
    # 除禁令说明外，不得出现能力 verdict 文本
    body = text.replace('不得解读为能力进步或退步', '')
    for w in ('判定：进步', '判定：退步', '判定：分化', '判定：稳定'):
        assert w not in body


# ------------------------------------------------------------------
# F4 同比：每指标 ≥3 有效样本；月度中位数回归；≥3 有效月份
# ------------------------------------------------------------------
def _yoy_df(rows):
    """去年同期窗口（2025-11-10 前 180 天）内的样本"""
    return _df(rows)


def _yoy_analyzer(df):
    return DeepRunAnalyzer(df, target_date=pd.Timestamp(TARGET_DATE),
                           max_hr=188, resting_hr=60)


def test_yoy_metric_median_requires_3_valid():
    base = pd.Timestamp('2025-11-10')
    rows = [_row(i + 1, base - pd.Timedelta(days=i * 10), hr=140 + i, pace=350 + i * 2)
            for i in range(2)]
    az = _yoy_analyzer(_yoy_df(rows))
    yoy = az._calc_yoy(_target(), 'easy_run', az.df_all)
    # 每指标只有 2 个有效样本：均不达 ≥3 门槛 → 数据不足
    assert yoy.get('message') == '数据不足'
    assert YOY_METRIC_MIN_SAMPLES == 3

    rows.append(_row(3, base - pd.Timedelta(days=30), hr=142, pace=355))
    az = _yoy_analyzer(_yoy_df(rows))
    yoy = az._calc_yoy(_target(), 'easy_run', az.df_all)
    assert yoy['sample_size'] == 3
    assert yoy['hr_valid_samples'] == 3 and yoy['pace_valid_samples'] == 3
    assert yoy['hr_median'] == pytest.approx(141, abs=1.5)
    assert yoy['pace_median_sec'] == pytest.approx(353, abs=1.5)


def test_yoy_same_month_3_activities_median_but_no_slope():
    """同一自然月 3 次活动：有中位数、无月斜率（第二批 F4）"""
    rows = [_row(i + 1, f'2025-10-{5 + i * 8}', hr=140 + i, pace=350 + i * 3)
            for i in range(3)]
    az = _yoy_analyzer(_yoy_df(rows))
    yoy = az._calc_yoy(_target(), 'easy_run', az.df_all)
    assert yoy['hr_median'] is not None
    assert 'hr_slope_per_month' not in yoy
    assert 'pace_slope_per_month' not in yoy


def test_yoy_3_months_1_per_month_normal_category_no_slope():
    """普通课型 3 个月但每月仅 1 次：无月斜率"""
    rows = [_row(1, '2025-09-05', hr=145, pace=360),
            _row(2, '2025-10-05', hr=143, pace=356),
            _row(3, '2025-11-05', hr=141, pace=352)]
    az = _yoy_analyzer(_yoy_df(rows))
    yoy = az._calc_yoy(_target(), 'easy_run', az.df_all)
    assert yoy['hr_median'] is not None
    assert 'hr_slope_per_month' not in yoy


def test_yoy_3_valid_months_with_slope():
    """普通课型 ≥3 有效月份且每月≥2：有月斜率，用真实月份间隔"""
    rows = []
    for m, (hr, pace) in zip((8, 9, 10), [(148, 362), (145, 358), (142, 354)]):
        for i in range(2):
            rows.append(_row(m * 10 + i + 1, f'2025-{m}-{5 + i * 10}', hr=hr, pace=pace))
    az = _yoy_analyzer(_yoy_df(rows))
    yoy = az._calc_yoy(_target(), 'easy_run', az.df_all)
    assert yoy.get('hr_slope_per_month') is not None
    assert yoy.get('pace_slope_per_month') is not None
    assert yoy['months_available'] == 3
    # 验证使用真实月份间隔：月均心率下降约 3 bpm/月
    assert yoy['hr_slope_per_month'] == pytest.approx(-3.0, abs=0.3)


def test_yoy_lsd_1_per_month_with_slope():
    """LSD 每月≥1：3 个月有月斜率"""
    rows = [_row(1, '2025-09-05', category='lsd', hr=142, pace=370),
            _row(2, '2025-10-05', category='lsd', hr=141, pace=368),
            _row(3, '2025-11-05', category='lsd', hr=140, pace=366)]
    az = _yoy_analyzer(_yoy_df(rows))
    yoy = az._calc_yoy(_target(category='lsd'), 'lsd', az.df_all)
    assert yoy.get('hr_slope_per_month') is not None


def test_yoy_uneven_month_spacing_uses_real_distance():
    """间隔不等月份（7 月、8 月、10 月）：斜率按真实月份距离计算"""
    rows = []
    for m, (hr, pace) in zip((7, 8, 10), [(148, 362), (145, 358), (142, 354)]):
        for i in range(2):
            rows.append(_row(m * 10 + i + 1, f'2025-{m:02d}-{5 + i * 10}', hr=hr, pace=pace))
    az = _yoy_analyzer(_yoy_df(rows))
    yoy = az._calc_yoy(_target(), 'easy_run', az.df_all)
    # x = [0, 1, 3]；心率月均值 [148,145,142] → 真实间隔斜率
    x = np.array([0.0, 1.0, 3.0])
    hr_y = np.array([148.0, 145.0, 142.0])
    expected = float(np.polyfit(x, hr_y, 1)[0])
    assert yoy['hr_slope_per_month'] == pytest.approx(round(expected, 2), abs=0.05)


def test_yoy_metric_gate_not_replaced_by_total():
    """总活动 ≥3 但心率有效样本不足 3：心率中位数不显示（配速达标仍显示）"""
    rows = [_row(1, '2025-10-05', hr=np.nan, pace=350),
            _row(2, '2025-10-15', hr=np.nan, pace=355),
            _row(3, '2025-10-25', hr=np.nan, pace=360)]
    az = _yoy_analyzer(_yoy_df(rows))
    yoy = az._calc_yoy(_target(), 'easy_run', az.df_all)
    assert yoy['sample_size'] == 3
    assert yoy['hr_valid_samples'] == 0
    assert yoy['hr_median'] is None
    assert yoy['pace_median_sec'] is not None


# ------------------------------------------------------------------
# F5 百分位：有效效率 n≥10 才排名
# ------------------------------------------------------------------
def _pct_baseline(n_valid, n_rows_extra=0, one_invalid=False):
    rows = []
    for i in range(n_valid):
        rows.append({'avg_hr': 150.0, 'avg_pace_sec': 300.0 + i})  # 效率随 i 递减
    for _ in range(n_rows_extra):
        rows.append({'avg_hr': 150.0, 'avg_pace_sec': 310.0})
    if one_invalid:
        rows.append({'avg_hr': 150.0, 'avg_pace_sec': 0.0})  # 无效效率
    return pd.DataFrame(rows)


def test_percentile_9_valid_returns_none():
    az, t = _analyzer(pd.DataFrame())
    assert az._calc_percentile(t, _pct_baseline(9)) is None


def test_percentile_10_valid_computes():
    az, t = _analyzer(pd.DataFrame())
    pct = az._calc_percentile(t, _pct_baseline(10))
    assert pct is not None
    assert pct['sample_size'] == 10
    assert 0 <= pct['value'] <= 100
    assert pct['rank_label'].startswith('P')


def test_percentile_10_rows_but_9_valid_returns_none():
    """dataframe 行数≥10 但有效效率只有 9 个：同样不得排名（第二批 F5）"""
    az, t = _analyzer(pd.DataFrame())
    assert az._calc_percentile(t, _pct_baseline(9, one_invalid=True)) is None
    assert PERCENTILE_MIN_VALID == 10


def test_percentile_formula_unchanged_with_sufficient_samples():
    """充足样本下百分位公式不变：better_count/n 口径核对"""
    az, t = _analyzer(pd.DataFrame())
    pct = az._calc_percentile(t, _pct_baseline(20))
    # 当前效率 3600000/(310*160)=72.58；历史效率 3600000/((300+i)*150) 均高于 72.58
    # better_count=20 → value=(1-20/20)*100=0
    assert pct['value'] == 0
    assert pct['rank_label'].startswith('P0')


# ------------------------------------------------------------------
# HTML 证据：渲染到临时目录，核对 n=3—4 与跨温长期的文本行为
# ------------------------------------------------------------------
def _render_html(tmp_path, comparison):
    from src.analysis_report import AnalysisReportGenerator
    data = {
        'raw_data': {'date': TARGET_DATE, 'activity_id': 123, 'category_name': '轻松跑',
                     'distance_km': 10.0, 'duration_min': 50.0},
        'summary': {'dominant_zone': 'Z2-有氧耐力', 'zone_pct': {}},
        'intensity': {}, 'efficiency': {},
        'comparison': comparison,
        'pa_hr': None, 'pa_hr_context': {'scope': 'full_activity', 'segment_laps': None,
                                         'reason': None},
    }
    gen = AnalysisReportGenerator(output_dir=str(tmp_path))
    return Path(gen.generate(data, llm_report='')).read_text(encoding='utf-8')


from pathlib import Path


def test_html_short_n3_shows_values_with_limited_badge(tmp_path):
    az, t = _analyzer(_short(3))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    html = _render_html(tmp_path, {'sample_size': 3, 'short_term': st})
    assert '样本有限' in html
    assert '当前 160' in html.replace(' ', ' ')  # 数值与中位数仍展示
    for w in DIRECTION_WORDS:
        assert w not in html


def test_html_long_all_temp_shows_descriptive_verdict(tmp_path):
    df = _long_df([(0, 155, 310, 1), (1, 153, 307, 1), (2, 151, 304, 1), (3, 148, 300, 1)])
    az, t = _analyzer(df)
    lt = az._calc_long_term(t, 'easy_run', 'cool', az.df_all)
    html = _render_html(tmp_path, {'sample_size': 12, 'long_term': lt})
    assert '能力证据不足' in html
    assert '未排除温度影响' in html
    assert '进步' not in html and '退步' not in html


# ------------------------------------------------------------------
# 第二批复验边界（验收阻断一/二 + 效率文案）
# ------------------------------------------------------------------
def test_short_total_n5_but_single_metric_insufficient():
    """总样本 5、心率仅 1 次有效：心率无 verdict（保留描述级中位数/差值），配速正常"""
    rows = []
    for i in range(5):
        r = _row(i + 1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10 + i * 5),
                 hr=150, pace=300)
        if i > 0:
            r['avg_hr'] = np.nan  # 仅 1 次心率有效
        rows.append(r)
    az, t = _analyzer(_df(rows), _target(hr=160, pace=310))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    assert st['sample_size'] == 5
    assert st['hr_valid_samples'] == 1 and st['pace_valid_samples'] == 5
    assert st['verdict_hr'] is None               # 单项不足 → 无方向 verdict
    assert st['hr_baseline'] is not None          # 描述级中位数保留
    assert st['hr_diff'] is not None              # 差值保留（带有效样本数说明）
    assert st['verdict_pace'] == '更慢'           # 达标指标不受影响
    assert st['verdict_allowed'] is True
    assert '心率有效 1' in st['evidence_reason']
    assert '样本充足' not in st['evidence_reason']  # 不得统称样本充足


def test_short_total_n5_but_efficiency_insufficient():
    """总样本 5、效率有效不足 5（心率缺失拖累效率有效数）：效率无 verdict"""
    rows = []
    for i in range(5):
        r = _row(i + 1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10 + i * 5),
                 hr=150, pace=300)
        if i >= 2:
            r['avg_hr'] = np.nan  # 3 次心率缺失 → 效率有效仅 2
        rows.append(r)
    az, t = _analyzer(_df(rows), _target(hr=160, pace=310))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    assert st['eff_valid_samples'] == 2
    assert st['verdict_efficiency'] is None
    assert st['verdict_pace'] == '更慢'


def test_short_current_hr_nan_no_verdict_not_stable():
    """当前心率为 NaN：心率无 verdict，且不得判为「持平」"""
    rows = [_row(i + 1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10 + i * 5),
                 hr=150, pace=300) for i in range(5)]
    target = _target(hr=160, pace=310)
    target['avg_hr'] = np.nan
    az, t = _analyzer(_df(rows), target)
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    assert st['verdict_hr'] is None
    assert st['verdict_hr'] != '持平'
    assert st['verdict_pace'] == '更慢'  # 当前配速 310 vs 基线 300（+10 > +5）
    assert st['hr_current'] is None


def test_prompt_short_partial_metric_no_none_text():
    """Prompt 对有效样本不足的指标显示「样本有限（有效 n 次）」，不得出现 None"""
    rows = []
    for i in range(5):
        r = _row(i + 1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10 + i * 5),
                 hr=150, pace=300)
        if i > 0:
            r['avg_hr'] = np.nan
        rows.append(r)
    az, t = _analyzer(_df(rows), _target(hr=160, pace=310))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    text = _prompt_for({'short_term': st})
    assert '样本有限（有效 1 次）' in text
    assert 'None' not in text
    assert '更慢' in text  # 配速方向正常输出


def test_html_short_partial_metric_shows_limited_badge(tmp_path):
    """HTML 对有效样本不足的指标显示中性「样本有限」，不得显示方向词或 None"""
    rows = []
    for i in range(5):
        r = _row(i + 1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10 + i * 5),
                 hr=150, pace=300)
        if i > 0:
            r['avg_hr'] = np.nan
        rows.append(r)
    az, t = _analyzer(_df(rows), _target(hr=160, pace=310))
    st = az._calc_short_term(t, 'easy_run', 'mild', az.df_all)
    html = _render_html(tmp_path, {'sample_size': 5, 'short_term': st})
    assert '样本有限' in html
    assert '>None<' not in html
    assert '更累' not in html  # 心率方向词不得出现


def test_long_stable_but_loo_unstable_becomes_trend_pending():
    """全量阈值内稳定但逐月剔除后方向改变：趋势待确认，不得输出确定「稳定」"""
    # 同温区 4 个月 × 3 次，心率月均值 [150,150,150,153]，配速/效率平稳
    df = _long_df([(0, 150, 300, 1), (1, 150, 300, 1), (2, 150, 300, 1), (3, 153, 300, 1)],
                  temp=MILD)
    az, t = _analyzer(df)
    lt = az._calc_long_term(t, 'easy_run', 'mild', az.df_all)
    assert lt['baseline_scope'] == 'same_temp'
    assert abs(lt['trend']['hr_slope_per_month'] - 0.9) < 0.15  # 全量在阈值内
    assert lt['sensitivity']['hr']['direction_stable'] is False
    assert lt['verdict'] == '趋势待确认'
    assert lt['verdict_allowed'] is False
    assert lt['evidence_level'] == 'descriptive'
    assert '逐月剔除方向分类一致' not in lt['evidence_reason']


def test_long_stable_and_loo_stable_keeps_stable():
    """全量稳定且逐月剔除分类一致：才允许「稳定」与相应理由（保留既有行为）"""
    df = _long_df([(0, 150, 300, 1), (1, 150.2, 300.3, 1), (2, 150, 300, 1), (3, 150.2, 300, 1)],
                  temp=MILD)
    az, t = _analyzer(df)
    lt = az._calc_long_term(t, 'easy_run', 'mild', az.df_all)
    assert lt['verdict'] == '稳定'
    assert lt['verdict_allowed'] is True
    assert '逐月剔除方向分类一致' in lt['evidence_reason']


def test_long_efficiency_negative_slope_reason_text():
    """效率负向斜率：理由必须为「效率月降 X.X」，不得出现「效率月升-」"""
    # 由目标效率值反推每月配速（心率恒 150）：eff [80,79,77.5,75] → 效率斜率负且 LOO 稳定
    effs = [80.0, 79.0, 77.5, 75.0]
    rows = []
    aid = 1
    for m, eff in enumerate(effs):
        month = pd.Period('2026-07', freq='M') + m
        pace = 24000.0 / eff
        for i in range(3):
            rows.append(_row(aid, f'{month}-{5 + i * 10:02d}', hr=150, pace=pace, temp=MILD))
            aid += 1
    df = _df(rows)
    az, t = _analyzer(df)
    lt = az._calc_long_term(t, 'easy_run', 'mild', az.df_all)
    assert lt['baseline_scope'] == 'same_temp'
    assert lt['trend']['efficiency_slope_per_month'] < -1.0
    assert lt['sensitivity']['efficiency']['direction_stable'] is True
    assert lt['verdict'] in ('退步', '分化')  # 效率负向 ± 可能的配速负向
    assert '效率月降' in lt['reason']
    assert '效率月升-' not in lt['reason']


# ------------------------------------------------------------------
# 回归保护：11-12 重点场景口径（PRD 11.1）
# ------------------------------------------------------------------
def test_regression_protection_11_12_fields(df):
    """11-12 轻松跑：短期 13 允许方向、百分位 P73、Pa:Hr +0.92% 不受本批影响"""
    from tests.test_deterministic_scenarios import _analyze
    row, data = _analyze(df, '2026-11-12')
    comp = data['comparison']
    assert comp['short_term']['sample_size'] == 13
    assert comp['short_term']['verdict_allowed'] is True
    assert comp['percentile']['value'] == 73
    assert comp['percentile']['sample_size'] == 30
    assert abs(data['pa_hr']['pa_hr_pct'] - 0.92) < 0.01
    lt = comp['long_term']
    assert lt['baseline_scope'] == 'all_temp'
    assert lt['verdict'] == '能力证据不足'
    assert lt['verdict_allowed'] is False
    # 同比旧斜率必须消失：只有 ≥3 有效月份的新算法才允许斜率
    yoy = lt['yoy']
    assert yoy.get('hr_slope_per_month') is None
    assert yoy.get('pace_slope_per_month') is None
