"""分圈 P20-P80 阴影带样本门槛与历史扩池回归测试。

断言更新（旧值→新值→依据）：图表函数第二参数由 recent_laps 改为统一每公里历史
统计结果（5.0.1 PRD 4.1「以 _analyze_laps 为每公里历史统计唯一入口」）；测试场景
（每公里 12/9 次样本的区间带显隐、同温小池扩池）保留不变，改经
compute_per_km_history_stats 生成统一统计后传入图表。
"""
import json

import pandas as pd
import pytest

import main
from src.chart_generator import BAND_MIN_SAMPLES, ChartGenerator
from src.lap_history_stats import (
    LAP_BAND_MIN_SAMPLES,
    LAP_MEDIAN_MIN_SAMPLES,
    compute_per_km_history_stats,
)


def _lap(activity_id, lap_index, pace, hr):
    return {
        'activity_id': activity_id,
        'lap_index': lap_index,
        'distance_m': 1000,
        'duration_sec': pace,
        'pace_sec_per_km': pace,
        'avg_hr': hr,
    }


def _current_laps():
    return [_lap('current', km, 320 + km * 5, 140 + km) for km in (1, 2)]


def _history(run_count):
    return [
        [_lap(f'history-{run}', km, 300 + run + km * 4, 135 + run + km)
         for km in (1, 2)]
        for run in range(run_count)
    ]


def _chart(generator_method, history):
    generator = ChartGenerator()
    method = getattr(generator, generator_method)
    stats = compute_per_km_history_stats(history, max_km=2)
    return json.loads(method(_current_laps(), stats, '有氧耐力'))


@pytest.mark.parametrize('generator_method', ['generate_lap_pace_chart_v2', 'generate_lap_hr_chart'])
def test_band_uses_per_km_samples_without_30_run_gate(generator_method):
    """12 次历史（少于 30）但每公里样本充足时，两张图都应绘制区间带。"""
    assert LAP_MEDIAN_MIN_SAMPLES == 5 and LAP_BAND_MIN_SAMPLES == 10
    chart = _chart(generator_method, _history(12))
    bands = [trace for trace in chart['data'] if trace.get('name') == '历史P20-P80区间']
    assert len(bands) == 1
    band = bands[0]
    assert band['fill'] == 'toself'
    assert band['x'] == [1, 2, 2, 1]
    assert len(band['y']) == 4
    assert chart['data'][0]['name'] == '历史P20-P80区间'


@pytest.mark.parametrize('generator_method', ['generate_lap_pace_chart_v2', 'generate_lap_hr_chart'])
def test_band_stays_hidden_below_per_km_minimum(generator_method):
    """每公里不足 10 个样本时保留中位线，但不绘制区间带。"""
    assert BAND_MIN_SAMPLES == 10
    chart = _chart(generator_method, _history(BAND_MIN_SAMPLES - 1))
    names = [trace.get('name') for trace in chart['data']]
    assert '历史P20-P80区间' not in names
    assert any(name in {'历史中位配速', '历史中位心率'} for name in names)
    assert any(name in {'本次配速', '本次心率'} for name in names)


class _FakeFetcher:
    def __init__(self, history):
        self.history = history

    def _load_lap_cache(self, activity_id):
        return self.history[activity_id]


def test_small_same_temperature_pool_expands_before_charting():
    """同温区只有 5 次时必须扩池，不能让两张图必然丢失阴影。"""
    target_ts = pd.Timestamp('2026-11-12')
    history = _history(12)
    rows = []
    for run in range(12):
        rows.append({
            'activity_id': f'history-{run}',
            'category': 'easy_run',
            'date': target_ts - pd.Timedelta(days=run + 1),
            'min_temperature': 20 if run < 5 else 28,
            'max_temperature': 24 if run < 5 else 32,
        })
    df = pd.DataFrame(rows)

    recent_laps, note = main._load_similar_lap_history(
        df, 'easy_run', target_ts, 'current', 100,
        _FakeFetcher({f'history-{run}': laps for run, laps in enumerate(history)}),
        temp_bucket='mild')

    assert len(recent_laps) == 12
    assert note == '跨温区 12 次'
    stats = compute_per_km_history_stats(recent_laps, max_km=2)
    for generator_method in ('generate_lap_pace_chart_v2', 'generate_lap_hr_chart'):
        generator = ChartGenerator()
        method = getattr(generator, generator_method)
        chart = json.loads(method(_current_laps(), stats, '有氧耐力'))
        assert any(trace.get('name') == '历史P20-P80区间' for trace in chart['data'])
