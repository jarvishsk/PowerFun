"""人工课型覆盖测试（5.0 第一批 PRD 10.1）

- 正确加载三个初始活动；
- 非法 category、非法 TOML、非法段落在报告前失败；
- 未配置活动保持原样；重复应用幂等；
- 人工显示名、颜色和来源正确；报告运行不回写 parquet。
"""

import hashlib

import pandas as pd
import pytest

from src.activity_overrides import (
    ActivityOverrideError,
    apply_activity_overrides,
    load_activity_overrides,
)


def _mini_df():
    return pd.DataFrame({
        'activity_id': [659451010, 660460268, 656543045, 661585068],
        'category': ['aerobic_run', 'aerobic_run', 'easy_run', 'easy_run'],
        'category_name': ['有氧耐力跑', '有氧耐力跑', '轻松跑', '轻松跑'],
        'category_color': ['#87CEEB', '#87CEEB', '#808080', '#808080'],
        'category_icon': ['💨', '💨', '😌', '😌'],
        'date': pd.to_datetime(['2026-11-06', '2026-11-09', '2026-10-29', '2026-11-12']),
    })


# ------------------------------------------------------------------
# 配置加载与校验
# ------------------------------------------------------------------
def test_load_three_initial_activities():
    overrides = load_activity_overrides()
    assert overrides == {
        '659451010': {'category': 'tempo_run', 'pa_hr_laps': [4, 9]},
        '660460268': {'category': 'tempo_run', 'pa_hr_laps': [5, 11]},
        '656543045': {'category': 'intensity_run', 'pa_hr_laps': None},
    }


def test_invalid_category_rejected(tmp_path):
    cfg = tmp_path / 'overrides.toml'
    cfg.write_text('schema_version = 1\n[activities."1"]\ncategory = "easy_run"\n', encoding='utf-8')
    with pytest.raises(ActivityOverrideError, match='category 不允许'):
        load_activity_overrides(cfg)


def test_invalid_toml_rejected(tmp_path):
    cfg = tmp_path / 'overrides.toml'
    cfg.write_text('schema_version = 1\n[activities."1"\ncategory = "tempo_run"\n', encoding='utf-8')
    with pytest.raises(ActivityOverrideError, match='无法解析'):
        load_activity_overrides(cfg)


@pytest.mark.parametrize('laps', ['[4]', '[4, 9, 10]', '[0, 9]', '["4", 9]', '[9, 4]'])
def test_invalid_segment_rejected(tmp_path, laps):
    cfg = tmp_path / 'overrides.toml'
    cfg.write_text(f'schema_version = 1\n[activities."1"]\ncategory = "tempo_run"\npa_hr_laps = {laps}\n',
                   encoding='utf-8')
    with pytest.raises(ActivityOverrideError):
        load_activity_overrides(cfg)


def test_unknown_activity_in_config_warns_not_blocks(tmp_path, caplog):
    cfg = tmp_path / 'overrides.toml'
    cfg.write_text('schema_version = 1\n[activities."999999999"]\ncategory = "tempo_run"\npa_hr_laps = [1, 2]\n',
                   encoding='utf-8')
    with caplog.at_level('WARNING'):
        df = apply_activity_overrides(_mini_df(), path=cfg)
    assert '999999999' in caplog.text
    # 其他活动不受影响
    assert (df['category'] == _mini_df()['category']).all()


# ------------------------------------------------------------------
# 应用语义：来源、显示名、颜色、幂等
# ------------------------------------------------------------------
def test_apply_sets_source_name_color():
    df = apply_activity_overrides(_mini_df())
    r1 = df[df['activity_id'] == 659451010].iloc[0]
    assert r1['category'] == 'tempo_run'
    assert r1['category_auto'] == 'aerobic_run'
    assert r1['category_source'] == 'manual'
    assert r1['category_name'] == '节奏跑'
    assert r1['category_color'] == '#32CD32'  # 复用 RunClassifier 颜色
    assert r1['pa_hr_lap_start'] == 4 and r1['pa_hr_lap_end'] == 9

    r3 = df[df['activity_id'] == 656543045].iloc[0]
    assert r3['category'] == 'intensity_run'
    assert r3['category_source'] == 'manual'
    assert r3['category_name'] == '间歇跑'
    assert pd.isna(r3['pa_hr_lap_start']) and pd.isna(r3['pa_hr_lap_end'])


def test_unconfigured_activity_unchanged():
    df = apply_activity_overrides(_mini_df())
    r4 = df[df['activity_id'] == 661585068].iloc[0]
    assert r4['category'] == 'easy_run'
    assert r4['category_auto'] == 'easy_run'
    assert r4['category_source'] == 'auto'
    assert r4['category_name'] == '轻松跑'


def test_apply_is_idempotent():
    df1 = apply_activity_overrides(_mini_df())
    df2 = apply_activity_overrides(df1)
    # 重复应用不会把已覆盖分类误存为 category_auto
    assert (df2['category_auto'] == df1['category_auto']).all()
    assert (df2['category'] == df1['category']).all()
    assert (df2['category_source'] == df1['category_source']).all()


def test_apply_does_not_mutate_input():
    original = _mini_df()
    apply_activity_overrides(original)
    assert 'category_auto' not in original.columns


# ------------------------------------------------------------------
# 报告入口不回写 parquet（集成：真实 parquet 字节不变）
# ------------------------------------------------------------------
def test_report_run_does_not_write_parquet(tmp_path):
    import subprocess, os
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    parquet = root / 'data' / 'running_data.parquet'
    before = hashlib.sha256(parquet.read_bytes()).hexdigest()
    iso_cache = tmp_path / 'cache'
    iso_cache.mkdir()
    env = os.environ.copy()
    env.update({
        'POWERFUN_CACHE_DIR': str(iso_cache),
        'POWERFUN_LLM_RUNTIME_DIR': str(tmp_path / 'runtime'),
    })
    # 正常模式会走完整报告（含缓存未命中的 prepare 阶段，exit 0 不写报告）
    proc = subprocess.run(
        [str(root / '.venv' / 'bin' / 'python'), str(root / 'main.py'),
         '--load-parquet', '--deep-analyze', '2026-11-06', '--deep-only',
         '--output', str(tmp_path / 'out')],
        capture_output=True, text=True, cwd=str(root), env=env, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    # parquet 是唯一数据源，报告入口只读
    after = hashlib.sha256(parquet.read_bytes()).hexdigest()
    assert before == after
