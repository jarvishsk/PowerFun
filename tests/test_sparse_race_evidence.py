"""稀疏赛事证据修复测试（5.0.1 PRD 第 8 节：8.1 合成分圈边界 / 8.2 整体对比与空状态）

8.3 今天真实场景 662381792 与 8.4 普通课型回归由
.runtime/acceptance/sparse-race/replay_662381792.py 只读回放承担（见交付文档）。

全部使用合成数据直接驱动统一统计入口 src.lap_history_stats、
DeepRunAnalyzer 内核与 LLMReportGenerator 文本；HTML 渲染到 pytest 临时目录。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.chart_generator import ChartGenerator
from src.deep_analyzer import DeepRunAnalyzer, LLMReportGenerator
from src.lap_history_stats import (LAP_BAND_MIN_SAMPLES,
                                   LAP_MEDIAN_MIN_SAMPLES,
                                   LAP_RESIDUAL_MIN_M,
                                   compute_per_km_history_stats)

TARGET_DATE = '2026-11-15'
MILD = (22.0, 26.0)


# ------------------------------------------------------------------
# 构造工具
# ------------------------------------------------------------------
def _hist_lap(idx, pace=300.0, hr=150.0, dist=1000, with_hr=True, with_pace=True):
    d = {'lap_index': idx, 'distance_m': dist}
    if with_pace:
        d['pace_sec_per_km'] = pace
    if with_hr:
        d['avg_hr'] = hr
    return d


def _hist_run(n_laps=5, pace=300.0, hr=150.0, dist=1000, **kw):
    """一次历史跑步的 n 个整公里圈"""
    return [_hist_lap(i, pace=pace + i, hr=hr + i, dist=dist, **kw)
            for i in range(1, n_laps + 1)]


def _runs(n, n_laps=5, **kw):
    return [_hist_run(n_laps, **kw) for _ in range(n)]


def _current_laps(n=5):
    return [_hist_lap(i, pace=310 + i, hr=155 + i) for i in range(1, n + 1)]


def _row(aid, date, category='half_marathon', hr=150.0, pace=300.0, temp=MILD,
         distance=21.1):
    d = {'activity_id': aid, 'date': date, 'category': category,
         'avg_hr': hr, 'avg_pace_sec': pace, 'distance': distance,
         'min_temperature': temp[0], 'max_temperature': temp[1]}
    return d


def _df(rows):
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df['_category_norm'] = df['category'].apply(
        lambda c: 'race' if c in ('full_marathon', 'half_marathon', 'race_event') else c)
    return df


def _target(category='half_marathon', hr=160.0, pace=310.0, temp=MILD,
            distance=21.1):
    return pd.Series(_row(999, TARGET_DATE, category=category, hr=hr, pace=pace,
                          temp=temp, distance=distance))


def _analyzer(df, target=None):
    t = target if target is not None else _target()
    return DeepRunAnalyzer(df, target_date=pd.Timestamp(TARGET_DATE),
                           max_hr=188, resting_hr=60), t


def _chart_traces(fig_json: str):
    fig = json.loads(fig_json)
    return fig.get('data', [])


# ------------------------------------------------------------------
# 8.1.1–8.1.3 每公里 3 / 5 / 9 / 10 样本边界
# ------------------------------------------------------------------
def test_per_km_3_samples_all_none():
    """每公里 3 个有效样本：配速/心率中位数与 P20–P80 均为 None（PRD 8.1-1）"""
    stats = compute_per_km_history_stats(_runs(3, n_laps=5), max_km=5)
    assert stats['sample_size'] == 3
    for km in range(1, 6):
        e = stats['by_km'][km]
        assert e['pace_samples'] == 3 and e['hr_samples'] == 3
        assert e['median_pace'] is None and e['median_hr'] is None
        assert e['p20_pace'] is None and e['p80_pace'] is None
        assert e['p20_hr'] is None and e['p80_hr'] is None


def test_per_km_5_samples_median_only():
    """每公里 5 个有效样本：有中位数，无 P20–P80（PRD 8.1-2）"""
    stats = compute_per_km_history_stats(_runs(LAP_MEDIAN_MIN_SAMPLES, n_laps=5), max_km=5)
    for km in range(1, 6):
        e = stats['by_km'][km]
        assert e['median_pace'] is not None and e['median_hr'] is not None
        assert e['p20_pace'] is None and e['p80_pace'] is None
        assert e['p20_hr'] is None and e['p80_hr'] is None


def test_per_km_9_no_band_10_has_band():
    """每公里 9 个仍无 P20–P80，10 个时才出现（PRD 8.1-3）"""
    stats9 = compute_per_km_history_stats(_runs(9, n_laps=5), max_km=5)
    assert all(stats9['by_km'][km]['p20_pace'] is None for km in range(1, 6))
    assert all(stats9['by_km'][km]['median_pace'] is not None for km in range(1, 6))
    stats10 = compute_per_km_history_stats(_runs(LAP_BAND_MIN_SAMPLES, n_laps=5), max_km=5)
    for km in range(1, 6):
        e = stats10['by_km'][km]
        assert e['p20_pace'] is not None and e['p80_pace'] is not None
        assert e['p20_hr'] is not None and e['p80_hr'] is not None


# ------------------------------------------------------------------
# 8.1.4 配速/心率独立降级
# ------------------------------------------------------------------
def test_pace_sufficient_hr_independent_degrade():
    """配速 10 样本、心率仅 4 有效：配速带齐，心率全 None（PRD 8.1-4）"""
    runs = []
    for r in range(10):
        laps = []
        for i in range(1, 6):
            laps.append(_hist_lap(i, pace=300 + i, hr=None if r < 6 else 150 + i))
        runs.append(laps)
    stats = compute_per_km_history_stats(runs, max_km=5)
    for km in range(1, 6):
        e = stats['by_km'][km]
        assert e['pace_samples'] == 10 and e['median_pace'] is not None
        assert e['p20_pace'] is not None
        assert e['hr_samples'] == 4
        assert e['median_hr'] is None and e['p20_hr'] is None and e['p80_hr'] is None


def test_hr_sufficient_pace_independent_degrade():
    """反向：心率 10 样本、配速仅 4 有效（PRD 8.1-4）"""
    runs = []
    for r in range(10):
        laps = []
        for i in range(1, 6):
            laps.append(_hist_lap(i, pace=None if r < 6 else 300 + i, hr=150 + i))
        runs.append(laps)
    stats = compute_per_km_history_stats(runs, max_km=5)
    for km in range(1, 6):
        e = stats['by_km'][km]
        assert e['hr_samples'] == 10 and e['median_hr'] is not None
        assert e['p20_hr'] is not None
        assert e['pace_samples'] == 4
        assert e['median_pace'] is None and e['p20_pace'] is None and e['p80_pace'] is None


# ------------------------------------------------------------------
# 8.1.5 950–999m 残圈：统一剔除
# ------------------------------------------------------------------
def test_residual_950_999_dropped_unified():
    """<950m 历史残圈在统一统计中剔除，950–999m 保留，残圈计数正确（PRD 8.1-5）"""
    run = [_hist_lap(i, pace=300 + i, hr=150 + i) for i in range(1, 5)]
    # 追加 3 个残圈（940/920/900m）与 2 个 950–999m 圈，均挂在 km1
    run += [_hist_lap(1, pace=500.0, hr=180.0, dist=940),
            _hist_lap(1, pace=510.0, hr=182.0, dist=920),
            _hist_lap(1, pace=520.0, hr=185.0, dist=900),
            _hist_lap(1, pace=305.0, hr=151.0, dist=960),
            _hist_lap(1, pace=306.0, hr=152.0, dist=980)]
    stats = compute_per_km_history_stats([run], max_km=4)
    assert stats['residual_dropped'] == 3
    # km1 完整圈：1（整公里）+2（950–999m 保留）= 3 个样本；若 950–999m 口径不一致会变为 1 或 6
    e = stats['by_km'][1]
    assert e['pace_samples'] == 3
    assert e['median_pace'] is None  # 3 < 5，无中位数


def test_residual_distance_boundary_950_kept():
    """distance_m == 950 保留，949 剔除（阈值边界，PRD 8.1-5）"""
    run = [_hist_lap(1, pace=300.0, dist=950),
           _hist_lap(1, pace=310.0, dist=949)]
    stats = compute_per_km_history_stats([run])
    assert stats['residual_dropped'] == 1
    assert stats['by_km'][1]['pace_samples'] == 1


# ------------------------------------------------------------------
# 8.1.6 部分公里足够：不得全图一刀切
# ------------------------------------------------------------------
def test_partial_km_sufficient_not_all_or_nothing():
    """km1 有 13 样本、km2 仅 3：km1 有统计、km2 为 None（PRD 8.1-6）"""
    runs = [[_hist_lap(1, pace=300.0 + r, hr=150.0 + r)] for r in range(10)]
    for r in range(3):  # 仅 3 次跑到 km2
        runs.append([_hist_lap(1, pace=301.0, hr=151.0),
                     _hist_lap(2, pace=320.0, hr=155.0)])
    stats = compute_per_km_history_stats(runs, max_km=2)
    assert stats['by_km'][1]['median_pace'] is not None
    assert stats['by_km'][2]['median_pace'] is None
    assert stats['by_km'][2]['pace_samples'] == 3


# ------------------------------------------------------------------
# 8.1 一致性：分析器 / 图表 / Prompt 共用同一份统计
# ------------------------------------------------------------------
def test_analyzer_consumes_unified_stats():
    """_analyze_laps 返回的 history_stats 与逐公里条目直接来自统一统计（PRD F1）"""
    recent = _runs(3, n_laps=5)
    az, _ = _analyzer(_df([_row(1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10))]))
    laps = az._analyze_laps(_current_laps(5), recent)
    stats = laps['history_stats']
    assert isinstance(stats, dict) and 'by_km' in stats
    for i, h in enumerate(laps['history_median']):
        e = stats['by_km'][h['lap']]
        assert h['pace_sec'] == e.get('median_pace')
        assert h['avg_hr'] == e.get('median_hr')
        assert laps['history_p20_pace'][i] == e.get('p20_pace')
        assert laps['history_p20_hr'][i] == e.get('p20_hr')
    # 3 样本：中位数全 None，不得用 0 冒充
    assert all(h['pace_sec'] is None and h['avg_hr'] is None for h in laps['history_median'])
    assert laps['sample_size'] == 3


def test_prompt_and_chart_consistent_with_unified_stats():
    """图表与 Prompt 消费统一统计：3 样本时图表无区间、中位 trace 全 None，
    Prompt 无历史中位列且含禁止比较说明（PRD 8.1-1 一致性）"""
    recent = _runs(3, n_laps=5)
    stats = compute_per_km_history_stats(recent, max_km=5)

    gen = LLMReportGenerator(pd.DataFrame())
    az, _ = _analyzer(_df([_row(1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10))]))
    laps = az._analyze_laps(_current_laps(5), recent)
    prompt = gen._format_lap_data(laps)
    assert '历史中位配速 |' not in prompt  # 表格无历史中位列
    assert '历史P20' not in prompt  # 说明文字允许提及 P20-P80 门槛，但无历史区间列
    assert '禁止比较各圈与历史中位数的快慢' in prompt
    assert '每公里配速样本' in prompt  # 各公里有效样本数说明

    cg = ChartGenerator()
    fig_json = cg.generate_lap_pace_chart_v2(_current_laps(5), history_stats=stats)
    traces = _chart_traces(fig_json)
    names = [t.get('name') for t in traces]
    assert '历史P20-P80区间' not in names
    median_trace = next(t for t in traces if t.get('name') == '历史中位配速')
    assert all(v is None for v in median_trace['y'])
    # 心率图同样
    fig_json_hr = cg.generate_lap_hr_chart(_current_laps(5), history_stats=stats)
    traces_hr = _chart_traces(fig_json_hr)
    names_hr = [t.get('name') for t in traces_hr]
    assert not any('P20' in (n or '') for n in names_hr)
    med_hr = next(t for t in traces_hr if '中位' in (t.get('name') or ''))
    assert all(v is None for v in med_hr['y'])


def test_partial_km_prompt_mixed_flags():
    """部分公里足够：Prompt 表格含历史中位列、注明部分公里不足（PRD 8.1-6）"""
    runs = []
    for r in range(10):
        laps = [_hist_lap(1, pace=300.0, hr=150.0)]
        if r < 3:
            laps.append(_hist_lap(2, pace=320.0, hr=155.0))
        runs.append(laps)
    az, _ = _analyzer(_df([_row(1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10))]))
    laps = az._analyze_laps(_current_laps(2), runs)
    gen = LLMReportGenerator(pd.DataFrame())
    prompt = gen._format_lap_data(laps)
    assert '部分公里达到每公里 ≥5 个有效样本' in prompt
    assert '历史中位配速 |' in prompt
    assert '—（该公里样本不足）' in prompt


# ------------------------------------------------------------------
# 8.2.1 跨全年描述性兜底（180 天 <3、全年 ≥3）
# ------------------------------------------------------------------
def _old_race_rows(n, days_back=200, category='half_marathon'):
    base = pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=days_back)
    return [_row(i + 1, base + pd.Timedelta(days=i), category=category,
                 hr=150 + i, pace=300 + i * 5)
            for i in range(n)]


def test_all_history_descriptive_fallback():
    """同距离历史比赛成绩参照：all_history 池、成绩比较允许、纯能力结论禁止
    （5.0.2 PRD 5.3 断言更新记录：旧值 descriptive_only=True、verdict 全部剥离 →
    新值 comparison_kind='same_distance_race_history'、verdict 保留且 verdict_scope='result'）"""
    df = _df(_old_race_rows(4))
    az, t = _analyzer(df)
    comp = az._compare_with_history(t)
    assert comp['sample_size'] == 4
    assert comp.get('baseline_window') == 'all_history'
    assert comp.get('comparison_kind') == 'same_distance_race_history'
    assert comp.get('descriptive_only') is not True  # 旧值 True → 新值不设该键（PRD 5.3）
    assert comp.get('result_comparison_allowed') is True
    assert comp.get('ability_verdict_allowed') is False
    # 成绩/执行比较 verdict 保留，但必须带 verdict_scope='result'（禁止纯能力解读）
    for group in ('ability', 'economy'):
        for metric in comp[group].values():
            assert metric.get('verdict_scope') == 'result'
    gen = LLMReportGenerator(pd.DataFrame())
    text = gen._format_comparison(comp)
    assert '【同距离历史比赛·成绩参照】' in text
    assert '成绩比较，非能力结论' in text
    assert '纯能力' in text


def test_all_history_near_subset_returned():
    """同距离比赛池不执行距离 ±20% 子集：10 km 距离的半马记录仍留在池内
    （5.0.2 PRD 5.2 断言更新记录：旧值 near_subset_size=3、池 5 次 →
    新值无 near_subset_size 键、池仍为 5 次——距离不同的同距离比赛不得被排除）"""
    rows = _old_race_rows(5)
    rows[0]['distance'] = 10.0   # 远离 21.1（±20% 外）——不得因此被排除出半马成绩池
    rows[1]['distance'] = 10.5
    df = _df(rows)
    az, t = _analyzer(df)
    comp = az._compare_with_history(t)
    assert comp['sample_size'] == 5
    assert 'near_subset_size' not in comp  # 旧值 3 → 新值无此键（PRD 5.2）
    assert len(comp.get('pool_activities', [])) == 5
    gen = LLMReportGenerator(pd.DataFrame())
    text = gen._format_comparison(comp)
    assert '参照池为全部 5 场历史半程马拉松' in text
    assert '距离相近子集' not in text


# ------------------------------------------------------------------
# 8.2.2 全年也 <3：整体为空但独立模块仍在
# ------------------------------------------------------------------
def test_empty_baseline_still_returns_independent_modules():
    """同距离比赛池为空：sample_size 0，但 short/long 等键独立返回
    （PRD 5.3/5.4；5.0.1 场景保留：历史行改用 easy_run，使比赛池为空）"""
    df = _df(_old_race_rows(2, category='easy_run'))
    az, t = _analyzer(df)
    comp = az._compare_with_history(t)
    assert comp['sample_size'] == 0
    assert comp.get('comparison_kind') == 'same_distance_race_history'
    assert 'message' in comp
    for key in ('short_term', 'long_term', 'tech_changes', 'percentile', 'expected_pace'):
        assert key in comp, f'空基线丢失独立模块 {key}'
    # 比赛技术参照池 <3 场：明确 insufficient_baseline，不作技术评价（PRD 7.1）
    assert comp['tech_changes']['kind'] == 'race'
    assert comp['tech_changes']['status'] == 'insufficient_baseline'
    gen = LLMReportGenerator(pd.DataFrame())
    text = gen._format_comparison(comp)
    assert '无法形成成绩参照比较' in text
    assert '短期状态' in text


# ------------------------------------------------------------------
# 8.2.5 Prompt 无斜率时禁止趋势推断
# ------------------------------------------------------------------
def test_prompt_no_slope_bans_trend_inference():
    """长期无斜率：Prompt 明确禁止「上升通道/近月训练斜率」等（PRD 8.2-5）"""
    gen = LLMReportGenerator(pd.DataFrame())
    comp = {
        'sample_size': 0, 'message': '最近无同类型跑步记录，无法对比',
        'ability': {}, 'economy': {},
        'short_term': {'window_days': 60, 'sample_size': 0, 'message': '样本不足',
                       'evidence_level': 'insufficient'},
        'long_term': {'window_days': 180, 'verdict': '数据不足',
                      'message': '近180天无同类型跑步', 'baseline_scope': 'all_temp'},
    }
    text = gen._format_comparison(comp)
    assert '禁止写「能力上升/下降/上升通道/近月训练斜率」' in text
    assert '样本不足，禁止判断近期状态方向' in text
    assert 'None' not in text


# ------------------------------------------------------------------
# 8.2.3 HTML 两个区块空状态
# ------------------------------------------------------------------
def _render_html(tmp_path, comparison):
    from src.analysis_report import AnalysisReportGenerator
    data = {
        'raw_data': {'date': TARGET_DATE, 'activity_id': 123, 'category_name': '半程马拉松',
                     'distance_km': 21.1, 'duration_min': 120.0},
        'summary': {'dominant_zone': 'Z3-乳酸阈值', 'zone_pct': {}},
        'intensity': {}, 'efficiency': {},
        'comparison': comparison,
        'pa_hr': None, 'pa_hr_context': {'scope': 'full_activity', 'segment_laps': None,
                                         'reason': None},
    }
    gen = AnalysisReportGenerator(output_dir=str(tmp_path))
    return Path(gen.generate(data, llm_report='')).read_text(encoding='utf-8')


def _insufficient_comparison():
    return {
        'sample_size': 0, 'message': '最近无同类型跑步记录，无法对比',
        'ability': {}, 'economy': {}, 'temp_bucket': 'mild',
        'short_term': {'window_days': 60, 'sample_size': 0, 'message': '样本不足',
                       'evidence_level': 'insufficient'},
        'long_term': {'window_days': 180, 'verdict': '数据不足',
                      'message': '近180天无同类型跑步', 'baseline_scope': 'all_temp'},
        'percentile': {'value': 50, 'rank_label': 'P50'},
        'expected_pace': {'expected_pace_sec': 300, 'actual_pace_sec': 310, 'diff_sec': 10},
    }


def test_html_empty_baseline_keeps_both_sections(tmp_path):
    """整体为空：HTML 同时保留「对比分析」与「状态与趋势」，均有明确空状态（PRD 8.2-3）"""
    html = _render_html(tmp_path, _insufficient_comparison())
    assert '对比分析' in html
    assert '状态与趋势' in html
    assert '无法形成同类型基线' in html  # 对比分析空状态
    assert '样本不足' in html or '数据不足' in html  # 状态与趋势空状态
    assert 'None' not in html
    assert '>nan<' not in html.lower()


def test_html_descriptive_fallback_shows_pool_and_subset(tmp_path):
    """同距离比赛参照：HTML 蓝条注明池 N 场、徽标显示成绩比较 verdict
    （5.0.2 PRD 5.5 断言更新记录：旧值「跨全年描述性基线/仅作描述」 →
    新值「同距离历史比赛成绩参照」+ 结果级 verdict 徽标；普通课型跨全年描述路径不变）"""
    df = _df(_old_race_rows(5))
    az, t = _analyzer(df)
    comp = az._compare_with_history(t)
    html = _render_html(tmp_path, comp)
    assert '同距离历史比赛成绩参照' in html
    assert '参照池共 5 场同距离历史比赛' in html
    assert '仅作描述' not in html  # 比赛成绩参照不再笼统降为「仅作描述」（PRD 5.5）
    assert '状态与趋势' in html
    assert '>nan<' not in html.lower()
