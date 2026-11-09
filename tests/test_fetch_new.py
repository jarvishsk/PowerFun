"""fetch_new 增量写出回归测试（mock 客户端 + 隔离数据目录）

覆盖四种场景：新增活动 / 已有活动字段更新 / 自定义标题保护 / 完全重复记录。
不触碰正式 data/ 与 Garmin 在线服务。
"""

import copy
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import src.personal_api as pa
from conftest import PROJECT_ROOT

FIT_FIXTURE = Path(__file__).parent / 'fixtures' / '659451010.fit'

DATA_FILES = ("running_data.parquet", "running_data_cleaned.csv",
              "activities_cache.json", "lap_data.parquet", "last_fetch.json")

LATEST_ID = 660164388  # 当前缓存中最新的活动（2026-11-08）


class FakeClient:
    """最小 Personal API 客户端替身（fetch_new 只需 search_activities + close）"""

    def __init__(self, activities):
        self._activities = activities
        self.closed = False

    def search_activities(self, **kwargs):
        return list(self._activities)

    def close(self):
        self.closed = True


def _fake_laps_factory(calls: list):
    def _fake_laps(client, activity_id):
        calls.append(activity_id)
        return [{
            'activity_id': activity_id, 'lap_index': 1, 'distance_m': 1000.0,
            'duration_sec': 400.0, 'pace_sec_per_km': 400.0, 'avg_hr': 140.0,
            'max_hr': 150.0, 'avg_power': 240.0, 'cadence': 188.0,
            'elevation_gain_m': 1.0,
        }]
    return _fake_laps


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """隔离数据目录（复制正式数据文件到 tmp），mock 客户端与分圈拉取"""
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    for name in DATA_FILES:
        src = PROJECT_ROOT / 'data' / name
        if src.exists():
            (data_dir / name).write_bytes(src.read_bytes())
    monkeypatch.setitem(pa.DEFAULT_CONFIG, 'data_dir', str(data_dir))
    monkeypatch.setitem(pa.DEFAULT_CONFIG, 'state_file', str(data_dir / 'last_fetch.json'))
    monkeypatch.setattr(pa.time, 'sleep', lambda s: None)
    # 备份动作也隔离，避免测试向正式 .runtime/backups/ 写副本
    monkeypatch.setattr(pa, '_backup_data_files', lambda: None)
    lap_calls = []
    monkeypatch.setattr(pa, '_fetch_laps_from_fit', _fake_laps_factory(lap_calls))

    cache = json.loads((data_dir / 'activities_cache.json').read_text(encoding='utf-8'))
    box = SimpleNamespace(data_dir=data_dir, cache=cache, lap_calls=lap_calls,
                          parquet_before=pd.read_parquet(data_dir / 'running_data.parquet'),
                          csv_bytes_before=(data_dir / 'running_data_cleaned.csv').read_bytes())
    yield box


def _client_for(activities, monkeypatch):
    fake = FakeClient(activities)
    monkeypatch.setattr(pa, '_build_client', lambda: (fake, None))
    return fake


def _latest_record(box):
    rec = next(a for a in box.cache if a.get('activityId') == LATEST_ID)
    return rec


def _read_parquet(box):
    df = pd.read_parquet(box.data_dir / 'running_data.parquet')
    return df


def _read_csv(box):
    return pd.read_csv(box.data_dir / 'running_data_cleaned.csv')


def _assert_parquet_csv_consistent(box):
    """Parquet 与 CSV 行数一致、活动集合一致、无重复 activity_id"""
    df = _read_parquet(box)
    csv = _read_csv(box)
    assert len(csv) == len(df)
    assert df['activity_id'].nunique() == len(df), "主表出现重复 activity_id"
    key = ['date_str', 'distance', 'avg_hr', 'max_hr']
    csv_keys = sorted(map(tuple, csv[key].astype(str).values.tolist()))
    df_keys = sorted(map(tuple, df[key].astype(str).values.tolist()))
    assert csv_keys == df_keys, "CSV 与 Parquet 活动集合不一致"


# ------------------------------------------------------------------
# 场景 1：新增活动 → 主表 +1、CSV 同步、无重复
# ------------------------------------------------------------------
def test_new_activity_appends_to_parquet_and_csv(sandbox, monkeypatch):
    new_rec = copy.deepcopy(_latest_record(sandbox))
    new_rec['activityId'] = 661000001
    new_rec['startTimeLocal'] = '2026-11-10 19:45:38'
    new_rec['startTimeGMT'] = '2026-11-10 11:45:38.0'
    new_rec['activityName'] = '杭州市 跑步'
    _client_for([new_rec], monkeypatch)

    assert pa.fetch_new() is True
    df = _read_parquet(sandbox)
    assert len(df) == len(sandbox.parquet_before) + 1
    assert '661000001' in set(df['activity_id'].astype(str))
    csv = _read_csv(sandbox)
    assert len(csv) == len(df)
    assert csv['date_str'].max() == '2026-11-10', "CSV 最后日期未同步"
    assert sandbox.lap_calls == [661000001]
    _assert_parquet_csv_consistent(sandbox)


# ------------------------------------------------------------------
# 场景 2：已有活动字段更新 → 回流主表与 CSV
# ------------------------------------------------------------------
def test_existing_activity_field_update_upserts_main_table(sandbox, monkeypatch):
    rec = copy.deepcopy(_latest_record(sandbox))
    rec['calories'] = float(rec.get('calories') or 0) + 100.0
    _client_for([rec], monkeypatch)

    assert pa.fetch_new() is True
    df = _read_parquet(sandbox)
    row = df[df['activity_id'].astype(str) == str(LATEST_ID)].iloc[0]
    assert row['calories'] == rec['calories'], "字段更新未回流主表"
    assert len(df) == len(sandbox.parquet_before), "行数不应变化"
    assert sandbox.lap_calls, "已有活动更新应同步刷新分圈"
    _assert_parquet_csv_consistent(sandbox)


# ------------------------------------------------------------------
# 场景 3：自定义标题保护 → 缓存保留自定义标题，但其他字段照常更新
# ------------------------------------------------------------------
def test_custom_title_protection_does_not_block_field_updates(sandbox, monkeypatch):
    cache_file = sandbox.data_dir / 'activities_cache.json'
    cache = json.loads(cache_file.read_text(encoding='utf-8'))
    rec = next(a for a in cache if a.get('activityId') == LATEST_ID)
    rec['activityName'] = '出差归来的恢复跑'  # 用户在 Connect 自定义的标题
    cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')

    fetched = copy.deepcopy(_latest_record(sandbox))
    assert str(fetched.get('activityName')).endswith('跑步'), "拉取记录应为自动标题"
    fetched['calories'] = float(fetched.get('calories') or 0) + 50.0
    _client_for([fetched], monkeypatch)

    assert pa.fetch_new() is True
    after = json.loads(cache_file.read_text(encoding='utf-8'))
    rec_after = next(a for a in after if a.get('activityId') == LATEST_ID)
    assert rec_after['activityName'] == '出差归来的恢复跑', "自定义标题被覆盖"
    assert rec_after['calories'] == fetched['calories'], "标题保护不应阻断其他字段更新"

    df = _read_parquet(sandbox)
    row = df[df['activity_id'].astype(str) == str(LATEST_ID)].iloc[0]
    assert row['calories'] == fetched['calories'], "其他字段更新未回流主表"
    assert row['title'] == '出差归来的恢复跑', "主表标题未保留自定义标题"
    _assert_parquet_csv_consistent(sandbox)


# ------------------------------------------------------------------
# 场景 4：完全重复记录 → 不重复处理、不拉分圈、主表与 CSV 不变
# ------------------------------------------------------------------
def test_identical_record_is_noop(sandbox, monkeypatch):
    duplicate = copy.deepcopy(_latest_record(sandbox))
    parquet_bytes_before = (sandbox.data_dir / 'running_data.parquet').read_bytes()
    _client_for([duplicate], monkeypatch)

    assert pa.fetch_new() is True
    assert sandbox.lap_calls == [], "完全重复记录不应触发分圈拉取"
    assert (sandbox.data_dir / 'running_data.parquet').read_bytes() == parquet_bytes_before
    assert (sandbox.data_dir / 'running_data_cleaned.csv').read_bytes() == sandbox.csv_bytes_before


# ------------------------------------------------------------------
# FIT 分圈基准回归：659451010 与历史缓存逐圈零差异
# ------------------------------------------------------------------
def test_fit_laps_match_historical_cache():
    """基准 FIT 的逐圈零差异结论回归（distance/时长/心率/功率/步频/爬升/配速）"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('659451010_ACTIVITY.fit', FIT_FIXTURE.read_bytes())

    laps = pa._parse_fit_laps(buf.getvalue(), 659451010)
    assert len(laps) == 16

    hist = pd.read_parquet(PROJECT_ROOT / 'data' / 'lap_data.parquet')
    old = hist[hist['activity_id'] == 659451010].sort_values('lap_index')
    merged = old.merge(pd.DataFrame(laps), on='lap_index', suffixes=('_hist', '_fit'))
    assert len(merged) == 16
    for col in ['distance_m', 'duration_sec', 'avg_hr', 'max_hr',
                'avg_power', 'cadence', 'elevation_gain_m', 'pace_sec_per_km']:
        diff = (merged[f'{col}_hist'].astype(float) - merged[f'{col}_fit'].astype(float)).abs().max()
        assert diff == 0, f"{col} 与历史缓存差异 {diff}"
