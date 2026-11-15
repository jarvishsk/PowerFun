"""PowerFun 5.0 第一批：人工课型覆盖（PRD F1）

职责：
- 用 Python 3.14 标准库 tomllib 读取 config/activity_overrides.toml；
- 只允许覆盖为现有键 tempo_run / intensity_run，人工显示名为「节奏跑」「间歇跑」；
- 在统一报告入口以复制方式应用覆盖：保留 category_auto / category_source，
  不回写 parquet，不全局修改 RunClassifier.CATEGORIES；
- 配置无法解析、category 不允许、段落非法时，在报告前给出清晰错误并停止。
"""

import logging
import tomllib
from pathlib import Path

import pandas as pd

from src.classifier import RunClassifier
from src.config import PROJECT_ROOT

logger = logging.getLogger("PowerFun.activity_overrides")

# 人工覆盖允许的课型键及人工显示名（PRD F2：不全局修改 RunClassifier.CATEGORIES）
MANUAL_CATEGORY_NAMES = {
    'tempo_run': '节奏跑',
    'intensity_run': '间歇跑',
}

DEFAULT_OVERRIDES_PATH = PROJECT_ROOT / 'config' / 'activity_overrides.toml'


class ActivityOverrideError(ValueError):
    """人工课型配置非法：报告入口必须给出清晰错误并停止，不得静默忽略。"""


def load_activity_overrides(path: Path = None) -> dict:
    """加载并校验人工课型覆盖配置

    Returns:
        {activity_id_str: {'category': str, 'pa_hr_laps': [start, end] | None}}

    Raises:
        ActivityOverrideError: TOML 无法解析、schema 版本不支持、category 不允许、
                               pa_hr_laps 不是两个正整数或起点大于终点。
    """
    path = Path(path) if path else DEFAULT_OVERRIDES_PATH
    if not path.exists():
        logger.warning(f"人工课型配置不存在: {path}，按无覆盖处理")
        return {}

    try:
        with open(path, 'rb') as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ActivityOverrideError(f"人工课型配置无法解析: {path}: {e}") from e

    if not isinstance(data, dict):
        raise ActivityOverrideError(f"人工课型配置格式非法（顶层必须是表）: {path}")

    schema_version = data.get('schema_version')
    if schema_version != 1:
        raise ActivityOverrideError(
            f"人工课型配置 schema_version 不支持: {schema_version!r}（当前仅支持 1）: {path}")

    activities = data.get('activities')
    if activities is None:
        return {}
    if not isinstance(activities, dict):
        raise ActivityOverrideError(f"人工课型配置 activities 必须是表: {path}")

    overrides = {}
    for activity_id, entry in activities.items():
        if not isinstance(entry, dict):
            raise ActivityOverrideError(f"活动 {activity_id} 的覆盖必须是表: {path}")
        category = entry.get('category')
        if category not in MANUAL_CATEGORY_NAMES:
            raise ActivityOverrideError(
                f"活动 {activity_id} 的 category 不允许: {category!r}"
                f"（只允许 {sorted(MANUAL_CATEGORY_NAMES)}）: {path}")
        laps = entry.get('pa_hr_laps')
        if laps is not None:
            if (not isinstance(laps, list) or len(laps) != 2
                    or not all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in laps)):
                raise ActivityOverrideError(
                    f"活动 {activity_id} 的 pa_hr_laps 必须是两个正整数 [起点, 终点]: {laps!r}: {path}")
            if laps[0] > laps[1]:
                raise ActivityOverrideError(
                    f"活动 {activity_id} 的 pa_hr_laps 起点大于终点: {laps!r}: {path}")
        overrides[str(activity_id)] = {
            'category': category,
            'pa_hr_laps': list(laps) if laps is not None else None,
        }
    return overrides


def apply_activity_overrides(df: pd.DataFrame, overrides: dict = None,
                             path: Path = None) -> pd.DataFrame:
    """以复制方式应用人工课型覆盖（幂等，可重复调用）

    每行保留/新增列：
    - category_auto:   原 parquet 自动分类（首次应用时固化，重复调用不改写）
    - category_source: 'auto' 或 'manual'
    - category:        实际生效分类
    - category_name / category_color / category_icon: 实际生效显示信息
    - pa_hr_lap_start / pa_hr_lap_end: 人工 Pa:Hr 工作段（仅节奏跑/间歇跑，未指定为 NaN）

    不修改入参 DataFrame，不回写 parquet；配置中出现当前数据不存在的
    activity_id 只警告，不阻断其他活动。
    """
    if overrides is None:
        overrides = load_activity_overrides(path)

    df = df.copy()
    if 'category' not in df.columns:
        return df

    # 显示信息列兜底（--load-parquet 的 parquet 已含这些列，防御合成数据缺列）
    for col, default in (('category_name', '跑步'), ('category_color', '#999999'), ('category_icon', '🏃')):
        if col not in df.columns:
            df[col] = default

    # 固化原自动分类：重复调用时以已有 category_auto 为准，避免把人工分类误存为 auto
    if 'category_auto' not in df.columns:
        df['category_auto'] = df['category']
    if 'category_source' not in df.columns:
        df['category_source'] = 'auto'
    df['pa_hr_lap_start'] = pd.NA
    df['pa_hr_lap_end'] = pd.NA

    if not overrides:
        return df

    id_to_idx = {}
    if 'activity_id' in df.columns:
        for idx, aid in df['activity_id'].items():
            if aid is not None and not pd.isna(aid):
                id_to_idx.setdefault(str(aid), idx)

    found = set()
    for activity_id, entry in overrides.items():
        idx = id_to_idx.get(str(activity_id))
        if idx is None:
            logger.warning(f"人工课型配置中的 activity_id 不在当前数据中，跳过: {activity_id}")
            continue
        found.add(str(activity_id))
        category = entry['category']
        cat_info = RunClassifier.CATEGORIES.get(category, {})
        df.at[idx, 'category'] = category
        df.at[idx, 'category_source'] = 'manual'
        df.at[idx, 'category_name'] = MANUAL_CATEGORY_NAMES[category]
        df.at[idx, 'category_color'] = cat_info.get('color', '#999999')
        df.at[idx, 'category_icon'] = cat_info.get('icon', '🏃')
        if entry['pa_hr_laps']:
            df.at[idx, 'pa_hr_lap_start'] = entry['pa_hr_laps'][0]
            df.at[idx, 'pa_hr_lap_end'] = entry['pa_hr_laps'][1]

    if found:
        logger.info(f"已应用人工课型覆盖 {len(found)} 次活动: {sorted(found)}（不回写 parquet）")
    return df
