"""统一每公里历史统计（PowerFun 5.0.1 F1 唯一事实来源）。

图表（chart_generator）、结构化 analysis_data（DeepRunAnalyzer._analyze_laps）
与 Prompt（LLMReportGenerator._format_lap_data）共用本模块的同一份统计结果，
不得各自重新遍历 recent_laps 计算中位数或 P20–P80。

统一过滤与证据规则（5.0.1 PRD 4.2，以原图表实现为准）：
- 残圈：distance_m < 950 剔除；缺距离字段保守保留；
- 中位数：当前公里、当前指标有效样本 ≥ LAP_MEDIAN_MIN_SAMPLES 才提供；
- P20–P80：当前公里、当前指标有效样本 ≥ LAP_BAND_MIN_SAMPLES 才提供；
- IQR：沿用图表启用规则（配速按该公里原始圈数、心率按有效心率样本 ≥10 启用）；
- 配速与心率分别计算有效样本数，独立降级；
- 不足统一用 None，不得以 0 冒充有效数据。
"""

from typing import Optional

import numpy as np

# 每公里历史统计样本门槛（与原图表一致，不降低）
LAP_RESIDUAL_MIN_M = 950     # 历史残圈剔除阈值（米）
LAP_MEDIAN_MIN_SAMPLES = 5   # 每公里历史中位线最低有效样本（普通课型）
RACE_LAP_MEDIAN_MIN_SAMPLES = 3  # 5.0.2 F2：半马/全马比赛分圈中位线最低有效样本
LAP_BAND_MIN_SAMPLES = 10    # 每公里历史 P20–P80 区间最低有效样本（任何课型不降低）


def _iqr_filter(values: list) -> list:
    """IQR 异常值过滤：剔除 [Q1-1.5×IQR, Q3+1.5×IQR] 之外的值。
    样本 <4 时不过滤（小样本分位数不稳定）；全部被剔除时保留原样本。"""
    if len(values) < 4:
        return values
    q1, q3 = np.percentile(values, [25, 75])
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    filtered = [v for v in values if lo <= v <= hi]
    return filtered if filtered else values


def compute_per_km_history_stats(recent_laps: Optional[list], max_km: Optional[int] = None,
                                 median_min_samples: Optional[int] = None) -> dict:
    """计算统一每公里历史统计。

    Args:
        recent_laps: 前 N 次同类型分圈数据列表，每个元素是一次跑步的分圈 list[dict]；
                     None/空 表示无历史。
        max_km: 需要补齐 None 条目的最大公里号（图表横轴 / 分析圈数）；
                None 时只覆盖历史中实际出现的公里号。
        median_min_samples: 中位线每公里最低有效样本（默认 LAP_MEDIAN_MIN_SAMPLES=5）。
                5.0.2 F2：半马/全马比赛分圈传 RACE_LAP_MEDIAN_MIN_SAMPLES=3；
                P20–P80 区间带始终使用 LAP_BAND_MIN_SAMPLES=10，不随此参数降低。

    Returns:
        {
          'by_km': {lap_idx: {
              'median_pace': float | None,   # 有效样本 ≥ median_min_samples 才提供
              'median_hr': float | None,
              'p20_pace': float | None,      # 有效样本 ≥ LAP_BAND_MIN_SAMPLES 才提供
              'p80_pace': float | None,
              'p20_hr': float | None,
              'p80_hr': float | None,
              'pace_samples': int,           # 该公里配速有效样本数
              'hr_samples': int,             # 该公里心率有效样本数
          }},
          'sample_size': int,                # 历史活动数（不是每公里有效样本数）
          'residual_dropped': int,           # 剔除的残圈数（distance_m < 950）
          'median_min_samples': int,         # 实际使用的中位线每公里最低有效样本
        }
    """
    if median_min_samples is None:
        median_min_samples = LAP_MEDIAN_MIN_SAMPLES
    stats = {'by_km': {}, 'sample_size': len(recent_laps or []), 'residual_dropped': 0,
             'median_min_samples': median_min_samples}

    # 残圈过滤：仅纳入完整公里圈（distance_m >= 950），缺距离字段保守保留
    filtered_runs = []
    for run_laps in (recent_laps or []):
        kept = []
        for rl in run_laps or []:
            dist = rl.get('distance_m')
            if dist is not None and dist < LAP_RESIDUAL_MIN_M:
                stats['residual_dropped'] += 1
            else:
                kept.append(rl)
        filtered_runs.append(kept)

    # 收集每个公里序号的原始值
    per_km_paces: dict = {}
    per_km_hrs: dict = {}
    per_km_lap_counts: dict = {}
    for run_laps in filtered_runs:
        for rl in run_laps:
            idx = rl.get('lap_index')
            if idx is None:
                continue
            per_km_lap_counts[idx] = per_km_lap_counts.get(idx, 0) + 1
            p = rl.get('pace_sec_per_km')
            if p is not None and p > 0:
                per_km_paces.setdefault(idx, []).append(float(p))
            h = rl.get('avg_hr')
            if h is not None and not (isinstance(h, float) and np.isnan(h)) and h > 0:
                per_km_hrs.setdefault(idx, []).append(float(h))

    km_indices = sorted(set(per_km_lap_counts) | set(per_km_paces) | set(per_km_hrs))
    if max_km is not None:
        km_indices = sorted(set(km_indices) | set(range(1, max_km + 1)))

    for idx in km_indices:
        paces = per_km_paces.get(idx, [])
        hrs = per_km_hrs.get(idx, [])
        # IQR 启用规则沿用原图表：配速按该公里原始圈数、心率按有效样本数
        if per_km_lap_counts.get(idx, 0) >= LAP_BAND_MIN_SAMPLES:
            paces = _iqr_filter(paces)
        if len(hrs) >= LAP_BAND_MIN_SAMPLES:
            hrs = _iqr_filter(hrs)
        entry = {
            'median_pace': float(np.percentile(paces, 50)) if len(paces) >= median_min_samples else None,
            'median_hr': float(np.percentile(hrs, 50)) if len(hrs) >= median_min_samples else None,
            'p20_pace': float(np.percentile(paces, 20)) if len(paces) >= LAP_BAND_MIN_SAMPLES else None,
            'p80_pace': float(np.percentile(paces, 80)) if len(paces) >= LAP_BAND_MIN_SAMPLES else None,
            'p20_hr': float(np.percentile(hrs, 20)) if len(hrs) >= LAP_BAND_MIN_SAMPLES else None,
            'p80_hr': float(np.percentile(hrs, 80)) if len(hrs) >= LAP_BAND_MIN_SAMPLES else None,
            'pace_samples': len(paces),
            'hr_samples': len(hrs),
        }
        stats['by_km'][idx] = entry

    return stats
