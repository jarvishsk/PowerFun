"""PowerFun 回归测试公共 fixtures"""

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / 'data'
CACHE_LLM_DIR = PROJECT_ROOT / 'cache' / 'llm'
REPORTS_DIR = PROJECT_ROOT / 'reports'
DEEP_DIR = REPORTS_DIR / 'PowerFun_Reports'


@pytest.fixture(scope='session')
def df() -> pd.DataFrame:
    """分析主表（唯一报告数据源）"""
    d = pd.read_parquet(DATA_DIR / 'running_data.parquet')
    d['date'] = pd.to_datetime(d['date'])
    return d.sort_values('date').reset_index(drop=True)


@pytest.fixture(scope='session')
def activities_cache() -> list:
    import json
    return json.loads((DATA_DIR / 'activities_cache.json').read_text(encoding='utf-8'))


@pytest.fixture(scope='session')
def lap_df() -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / 'lap_data.parquet')
