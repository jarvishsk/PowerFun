"""PowerFun 5.0.2 F5：结构化比赛计划（可选配置 + 确定性赛段证据）

职责：
- 用 Python 3.14 标准库 tomllib 读取 config/race_plans.toml，按比赛日期关联；
- 严格校验（schema、类别、赛段递增、配速上下限、检查点窗口、天气调整数值），
  配置非法时抛 RacePlanError，报告入口清晰报错并停止，不静默忽略；
- compute_plan_evidence() 用本次分圈数据计算确定性赛段证据：
  赛段配速 = 总时长/总距离；心率、功率按分圈时长加权；爬升求和；
  天气触发时由内核按结构化秒数计算调整后配速区间与调整后目标；
  湿度缺失时明确「未参与判断」，不得由模型自行估算；
- 无配置返回 None，调用方禁止计划偏离判断；
- 计划配置与赛段证据整体进入 analysis_data（进而 analysis_hash），
  修改计划后旧 LLM 缓存不得误命中。

不让程序自由解析训练 Markdown，不让模型凭记忆补比赛计划。
"""
import logging
import tomllib
from pathlib import Path
from typing import Optional

from src.config import PROJECT_ROOT

logger = logging.getLogger("PowerFun.race_plans")

DEFAULT_RACE_PLANS_PATH = PROJECT_ROOT / 'config' / 'race_plans.toml'

# 与 F1 同距离原则一致：计划只允许挂在半马/全马比赛上
VALID_RACE_CATEGORIES = ('half_marathon', 'full_marathon')


class RacePlanError(ValueError):
    """比赛计划配置非法：报告入口必须给出清晰错误并停止，不得静默忽略。"""


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _check(cond, msg):
    if not cond:
        raise RacePlanError(msg)


def load_race_plan(date_str: str, path: Path = None) -> Optional[dict]:
    """加载并校验指定日期的比赛计划；无配置返回 None（不阻断报告）

    Args:
        date_str: 比赛日期 'YYYY-MM-DD'
        path: 配置路径（默认 config/race_plans.toml）

    Returns:
        规范化计划 dict，或 None（文件不存在 / 该日期无配置）

    Raises:
        RacePlanError: TOML 无法解析、schema 不支持、字段非法。
    """
    path = Path(path) if path else DEFAULT_RACE_PLANS_PATH
    if not path.exists():
        return None

    try:
        with open(path, 'rb') as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise RacePlanError(f"比赛计划配置无法解析: {path}: {e}") from e

    _check(isinstance(data, dict), f"比赛计划配置格式非法（顶层必须是表）: {path}")
    schema = data.get('schema_version')
    _check(schema == 1, f"比赛计划配置 schema_version 不支持: {schema!r}（当前仅支持 1）: {path}")

    races = data.get('races')
    if races is None:
        return None
    _check(isinstance(races, dict), f"比赛计划配置 races 必须是表: {path}")

    entry = races.get(date_str)
    if entry is None:
        return None
    _check(isinstance(entry, dict), f"比赛 {date_str} 的计划必须是表: {path}")

    category = entry.get('category')
    _check(category in VALID_RACE_CATEGORIES,
           f"比赛 {date_str} 的 category 不允许: {category!r}（只允许 {list(VALID_RACE_CATEGORIES)}）: {path}")
    for field in ('name', 'target', 'strategy'):
        _check(isinstance(entry.get(field), str) and entry[field].strip(),
               f"比赛 {date_str} 缺少非空字段 {field}: {path}")

    # 天气调整：阈值、降速秒数、调整后目标必须为合法数值/文本
    heat_thr = entry.get('heat_threshold_c')
    _check(_is_num(heat_thr), f"比赛 {date_str} 的 heat_threshold_c 必须是数值: {path}")
    pen_min = entry.get('heat_pace_penalty_min_sec')
    pen_max = entry.get('heat_pace_penalty_max_sec')
    for v, label in ((pen_min, 'heat_pace_penalty_min_sec'), (pen_max, 'heat_pace_penalty_max_sec')):
        _check(isinstance(v, int) and not isinstance(v, bool) and v > 0,
               f"比赛 {date_str} 的 {label} 必须是正整数: {path}")
    _check(pen_min <= pen_max,
           f"比赛 {date_str} 的降速秒数下限大于上限: {pen_min} > {pen_max}: {path}")
    _check(isinstance(entry.get('heat_adjusted_target'), str) and entry['heat_adjusted_target'].strip(),
           f"比赛 {date_str} 缺少非空 heat_adjusted_target: {path}")
    weather_rule = entry.get('weather_rule')
    _check(isinstance(weather_rule, str) and weather_rule.strip(),
           f"比赛 {date_str} 缺少非空 weather_rule: {path}")

    # 赛段：按公里递增，配速上下限合法
    segments = entry.get('segments')
    _check(isinstance(segments, list) and len(segments) > 0,
           f"比赛 {date_str} 必须至少有一个赛段: {path}")
    norm_segments = []
    prev_end = 0.0
    for i, seg in enumerate(segments):
        _check(isinstance(seg, dict), f"比赛 {date_str} 赛段 {i + 1} 必须是表: {path}")
        start_km, end_km = seg.get('start_km'), seg.get('end_km')
        _check(_is_num(start_km) and _is_num(end_km) and 0 < start_km <= end_km,
               f"比赛 {date_str} 赛段 {i + 1} 的公里范围非法: {start_km}-{end_km}: {path}")
        _check(start_km > prev_end,
               f"比赛 {date_str} 赛段必须按公里严格递增且不重叠: 第 {i + 1} 段 {start_km} 未接续 {prev_end}: {path}")
        p_min, p_max = seg.get('pace_min_sec'), seg.get('pace_max_sec')
        _check(isinstance(p_min, int) and isinstance(p_max, int)
               and 0 < p_min <= p_max,
               f"比赛 {date_str} 赛段 {i + 1} 的配速上下限非法: {p_min}-{p_max}: {path}")
        note = seg.get('note', '')
        _check(isinstance(note, str), f"比赛 {date_str} 赛段 {i + 1} 的 note 必须是字符串: {path}")
        norm_segments.append({'start_km': float(start_km), 'end_km': float(end_km),
                              'pace_min_sec': p_min, 'pace_max_sec': p_max, 'note': note})
        prev_end = end_km

    # 检查点：距离递增，锚点/窗口合法
    checkpoints = entry.get('checkpoints')
    _check(isinstance(checkpoints, list) and len(checkpoints) > 0,
           f"比赛 {date_str} 必须至少有一个检查点: {path}")
    norm_cps = []
    prev_dist = 0.0
    for i, cp in enumerate(checkpoints):
        _check(isinstance(cp, dict), f"比赛 {date_str} 检查点 {i + 1} 必须是表: {path}")
        dist = cp.get('distance_km')
        anchor, upper = cp.get('anchor_sec'), cp.get('upper_sec')
        _check(_is_num(dist) and dist > prev_dist,
               f"比赛 {date_str} 检查点必须按距离严格递增: 第 {i + 1} 个 {dist} 未接续 {prev_dist}: {path}")
        _check(isinstance(anchor, int) and isinstance(upper, int) and 0 < anchor <= upper,
               f"比赛 {date_str} 检查点 {i + 1} 的锚点/窗口上限非法: {anchor}/{upper}: {path}")
        action = cp.get('action', '')
        _check(isinstance(action, str), f"比赛 {date_str} 检查点 {i + 1} 的 action 必须是字符串: {path}")
        norm_cps.append({'distance_km': float(dist), 'anchor_sec': anchor,
                         'upper_sec': upper, 'action': action})
        prev_dist = dist

    return {
        'date': date_str,
        'name': entry['name'],
        'category': category,
        'target': entry['target'],
        'strategy': entry['strategy'],
        'weather_rule': weather_rule,
        'heat_threshold_c': float(heat_thr),
        'heat_pace_penalty_min_sec': pen_min,
        'heat_pace_penalty_max_sec': pen_max,
        'heat_adjusted_target': entry['heat_adjusted_target'],
        'segments': norm_segments,
        'checkpoints': norm_cps,
    }


def _norm_laps(laps: list) -> list:
    """提取分圈的 距离(m)/时长(s)/心率/功率/爬升 有效字段；圈号从 1 起（顺序即 lap_index）"""
    out = []
    for i, lap in enumerate(laps or [], start=1):
        dist = lap.get('distance_m', lap.get('distance', 0)) or 0
        dur = lap.get('duration_sec', lap.get('duration', 0)) or 0
        if dist <= 0 or dur <= 0:
            continue
        out.append({
            'lap_no': float(lap.get('lap_index') or i),
            'distance_m': float(dist),
            'duration_sec': float(dur),
            'avg_hr': lap.get('avg_hr'),
            'avg_power': lap.get('avg_power'),
            'elevation_gain_m': float(lap.get('elevation_gain_m') or 0),
        })
    return out


def compute_plan_evidence(plan: dict, laps: list,
                          temp_mid: Optional[float] = None,
                          humidity: Optional[float] = None) -> dict:
    """计算确定性赛段证据（PRD 9.3）

    - 赛段配速 = 赛段总时长 / 赛段总距离（不得用逐公里简单平均）；
    - 心率、功率按分圈时长加权；爬升求和；
    - 检查点实际累计时间按距离线性插值到整公里；
    - 天气触发（中值气温 > 阈值）时给出调整后配速区间与调整后目标；
      湿度缺失明确「未参与判断」；原始计划与调整后计划同时提供；
    - 每个赛段/检查点给出与原计划及（触发时）调整后计划窗口的确定性偏差。

    Returns:
        evidence dict（进入 analysis_data / analysis_hash 与 Prompt）。
    """
    norm = _norm_laps(laps)
    total_dist_m = sum(l['distance_m'] for l in norm)

    # 每圈的累计距离区间
    spans = []
    cum = 0.0
    for l in norm:
        spans.append((cum, cum + l['distance_m'], l))
        cum += l['distance_m']

    def _laps_between(start_km: float, end_km: float) -> list:
        """取圈号落在 [start_km, end_km] 内的圈（赛段按公里编号对应整公里圈）"""
        return [l for l in norm if start_km - 1e-9 <= l['lap_no'] <= end_km + 1e-9]

    def _weighted(picked: list, key: str):
        """按分圈时长加权平均；有效样本不足返回 None"""
        num = den = 0.0
        for l in picked:
            v = l.get(key)
            if v is None or (isinstance(v, float) and v != v):
                continue
            num += l['duration_sec'] * float(v)
            den += l['duration_sec']
        return round(num / den, 1) if den > 0 else None

    # 天气触发与调整后计划（内核计算，不得让模型自行换算）
    heat_triggered = temp_mid is not None and temp_mid > plan['heat_threshold_c']
    humidity_used = humidity is not None
    adj_min = plan['heat_pace_penalty_min_sec'] if heat_triggered else 0
    adj_max = plan['heat_pace_penalty_max_sec'] if heat_triggered else 0

    segments = []
    for seg in plan['segments']:
        picked = _laps_between(seg['start_km'], seg['end_km'])
        dur = sum(l['duration_sec'] for l in picked)
        dist = sum(l['distance_m'] for l in picked)
        pace = round(dur / dist * 1000.0, 1) if dist > 0 and dur > 0 else None
        entry = {
            'start_km': seg['start_km'], 'end_km': seg['end_km'],
            'note': seg['note'],
            'planned_pace_min_sec': seg['pace_min_sec'],
            'planned_pace_max_sec': seg['pace_max_sec'],
            'actual_pace_sec': pace,
            'avg_hr_weighted': _weighted(picked, 'avg_hr'),
            'avg_power_weighted': _weighted(picked, 'avg_power'),
            'elevation_gain_m': round(sum(l['elevation_gain_m'] for l in picked), 1),
            'lap_count': len(picked),
        }
        if pace is not None:
            entry['deviation'] = ('in_range' if seg['pace_min_sec'] <= pace <= seg['pace_max_sec']
                                  else ('faster' if pace < seg['pace_min_sec'] else 'slower'))
            entry['adjusted_pace_min_sec'] = seg['pace_min_sec'] + adj_min
            entry['adjusted_pace_max_sec'] = seg['pace_max_sec'] + adj_max
            entry['adjusted_deviation'] = (
                'in_range' if entry['adjusted_pace_min_sec'] <= pace <= entry['adjusted_pace_max_sec']
                else ('faster' if pace < entry['adjusted_pace_min_sec'] else 'slower'))
        segments.append(entry)

    checkpoints = []
    for cp in plan['checkpoints']:
        target_m = cp['distance_km'] * 1000.0
        # 累计时间线性插值（整公里落在圈边界或圈中部）
        elapsed = None
        if target_m <= total_dist_m + 1e-9:
            elapsed_cum = 0.0
            for s, e, l in spans:
                if target_m <= e + 1e-9:
                    frac = 0.0 if e <= s else (target_m - s) / (e - s)
                    frac = min(max(frac, 0.0), 1.0)
                    elapsed = round(elapsed_cum + l['duration_sec'] * frac, 1)
                    break
                elapsed_cum += l['duration_sec']
        entry = {
            'distance_km': cp['distance_km'],
            'anchor_sec': cp['anchor_sec'], 'upper_sec': cp['upper_sec'],
            'action': cp['action'],
            'actual_elapsed_sec': elapsed,
        }
        if elapsed is not None:
            if elapsed <= cp['anchor_sec']:
                entry['deviation'] = 'ahead_of_anchor'
            elif elapsed <= cp['upper_sec']:
                entry['deviation'] = 'within_window'
            else:
                entry['deviation'] = 'beyond_upper'
        checkpoints.append(entry)

    return {
        'plan': {k: plan[k] for k in ('date', 'name', 'category', 'target', 'strategy',
                                      'weather_rule', 'heat_threshold_c',
                                      'heat_pace_penalty_min_sec', 'heat_pace_penalty_max_sec',
                                      'heat_adjusted_target', 'segments', 'checkpoints')},
        'weather': {
            'temp_mid_c': temp_mid,
            'humidity_pct': humidity,
            'humidity_participated': humidity_used,
            'heat_triggered': heat_triggered,
            'adjusted_target': plan['heat_adjusted_target'] if heat_triggered else None,
            'adjusted_pace_penalty_sec': [adj_min, adj_max] if heat_triggered else None,
        },
        'segments': segments,
        'checkpoints': checkpoints,
    }
