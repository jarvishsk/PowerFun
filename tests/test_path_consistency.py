"""报告路径一致性测试（5.0 第一批 PRD 10.4）

- 正常 latest 与 --deep-analyze latest 对同一活动产生相同核心 analysis_data；
- 指定历史日期不使用未来数据（行为由 _generate_deep_report 统一承载，此处验证合并后两路径一致）。
"""

import pandas as pd
import pytest

import main
from src.activity_overrides import apply_activity_overrides
from src.config import DEFAULT_CONFIG
from src.data_fetcher import GarminDataFetcher


class _StubFetcher:
    """只读分圈缓存的桩 fetcher（复用正式 lap parquet，不建网络连接）"""

    def __init__(self, real):
        self._real = real

    def _load_lap_cache(self, activity_id):
        return self._real._load_lap_cache(activity_id)

    def close(self):
        pass


def _capture_both_paths(df, tmp_path, monkeypatch):
    real = GarminDataFetcher(state_file=DEFAULT_CONFIG['state_file'])
    stub = _StubFetcher(real)
    calls = []

    def fake_resolve(df_, analysis_data, activity_id, **kwargs):
        # 在 brief_summary 等后加字段写入前捕获核心 analysis_data
        calls.append(main._json_safe(analysis_data))
        analysis_data['brief_summary'] = '桩简报'
        return '桩报告', 'KimiWork'

    monkeypatch.setattr(main, '_resolve_llm_report', fake_resolve)
    try:
        stats = main._get_summary_stats(df)
        # 正常模式（最近一次跑步）：第一批 F5 后复用 _generate_deep_report
        main._run_reports(df, tmp_path / 'normal', stats,
                          False, None, False, 188, 60,
                          fetcher=stub, deep_only=True)
        # 显式 --deep-analyze latest
        main._run_reports(df, tmp_path / 'explicit', stats,
                          False, 'latest', False, 188, 60,
                          fetcher=stub, deep_only=True)
    finally:
        real.close()
    return calls


def test_normal_latest_matches_explicit_latest(df, tmp_path, monkeypatch):
    """正常 latest 与显式 latest 共用 _generate_deep_report，核心 analysis_data 一致"""
    df = apply_activity_overrides(df)
    calls = _capture_both_paths(df, tmp_path, monkeypatch)
    assert len(calls) == 2, '两条路径应各走一次统一深析入口'
    normal_data, explicit_data = calls
    # 同一活动（parquet 中最新一次）
    assert normal_data['raw_data']['activity_id'] == explicit_data['raw_data']['activity_id']
    assert normal_data == explicit_data


def test_report_entry_applies_manual_category(df, tmp_path, monkeypatch):
    """统一入口 _run_reports 在分析前应用人工课型（659451010 → 节奏跑）"""
    df = apply_activity_overrides(df)
    real = GarminDataFetcher(state_file=DEFAULT_CONFIG['state_file'])
    stub = _StubFetcher(real)
    captured = {}

    def fake_resolve(df_, analysis_data, activity_id, **kwargs):
        captured.update(main._json_safe(analysis_data))
        analysis_data['brief_summary'] = '桩简报'
        return '桩报告', 'KimiWork'

    monkeypatch.setattr(main, '_resolve_llm_report', fake_resolve)
    try:
        stats = main._get_summary_stats(df)
        main._run_reports(df, tmp_path / 'out', stats,
                          False, '2026-11-06', False, 188, 60,
                          fetcher=stub, deep_only=True)
    finally:
        real.close()
    assert captured['raw_data']['category'] == 'tempo_run'
    assert captured['raw_data']['category_name'] == '节奏跑'
    assert captured['pa_hr']['scope'] == 'manual_segment'
    assert captured['pa_hr']['segment_laps'] == [4, 9]
    assert abs(captured['pa_hr']['pa_hr_pct'] - (-6.14)) < 0.01
