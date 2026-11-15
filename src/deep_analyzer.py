"""跑步深度分析器"""

import json
import logging
import math
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.config import DEFAULT_CONFIG, HR_ZONE_PERCENTAGES, USER_CONFIG
from src.classifier import HeartRateClassifier
from src.lap_history_stats import (
    LAP_RESIDUAL_MIN_M,
    RACE_LAP_MEDIAN_MIN_SAMPLES,
    compute_per_km_history_stats,
)
from src.race_plans import compute_plan_evidence
from src.utils import format_pace_chinese

logger = logging.getLogger("PowerFun.deep_analyzer")

# ============ 比赛参照池（5.0.2 F1：同距离是比赛参照池边界）============
# 老板决策：半马与全部历史半马比较、全马与全部历史全马比较；
# 赛道、气温、海拔、人数、比赛目标等用于解释差异，不用于排除样本。
RACE_CATEGORIES = ('half_marathon', 'full_marathon')
# 比赛技术参照最少同距离历史场次数（不足时只保留逐场背景，不给技术结论）
RACE_TECH_MIN_SAMPLES = 3

# ============ 技术指标基线参数（PRD F1：功率口径）============
TECH_BASELINE_MIN_DAYS = 90      # 基线最小时间跨度：拉开 90 天排除近期体能红利
TECH_BASELINE_MIN_SAMPLES = 3    # 基线最少样本数
TECH_POWER_TOLERANCE_W = 8       # 相近功率容差 ±8W（主口径：机械输出与步频/步幅/VR/GCT 直接耦合）
TECH_PACE_TOLERANCE_SEC = 15     # 相近配速容差 ±15 秒（功率缺失样本的兜底口径）

# 进步判定阈值（只报进步，阈值不动）
TECH_IMPROVE_VR = -0.2           # 垂直振幅比下降 ≥0.2% 算进步
TECH_IMPROVE_GCT = -5            # 触地时间缩短 ≥5ms 算进步
TECH_IMPROVE_CADENCE = 2         # 步频提升 ≥2spm 算进步
TECH_IMPROVE_STRIDE = 1          # 步幅提升 ≥1cm 算进步

# ============ 问题探测器阈值（PRD F2，模块级常量便于调整）============
# 依据：easy 课高强度占比应极低；有氧课 Z4+ 超 1/5 即 threshold 课型失效；LSD 应以 Z2 为主
ISSUE_INTENSITY_LIMITS = {'easy_run': (3, 8.0), 'aerobic_run': (4, 20.0), 'lsd': (2, 25.0)}
ISSUE_PA_HR_PCT = 5.0            # 有氧解耦 <= -5% 判定心率漂移（负值 = 后半程速度/心率效率下降）
ISSUE_LOAD_RATIO = 1.5           # 负荷 > 近 4 次均值 ×1.5 判定激增
ISSUE_LOAD_RECENT_N = 4          # 负荷对比取近 4 次（不限类型，排除本次）
ISSUE_LOAD_MIN_SAMPLES = 2       # 近 4 次有效负荷 <2 则跳过
ISSUE_MAX_HR_WINDOW_DAYS = 90    # 心率异常 P95 口径：近 90 天同类型
ISSUE_MAX_HR_P95_MIN_SAMPLES = 5 # P95 口径最少样本数

# ============ 趋势窗口、参照样本与新鲜度门槛 ============
# 依据：45 天新鲜度门槛误伤长期回归（跨温区基线只覆盖近两个月 → 样本不足）；
# 短期窗口与新鲜度均放宽到 60 天，让基线样本更稳（体能月漂移 ~1.5bpm 可吸收）
LONG_TERM_WINDOW_DAYS = 180      # 长期趋势窗口：180 天全量，取消新鲜度门槛（保留月份护栏）
SHORT_TERM_WINDOW_DAYS = 60      # 短期状态窗口：30 → 60 天（2026-10-22 PRD）
SHORT_TERM_FRESHNESS_DAYS = 60   # 短期基线新鲜度门槛：45 → 60 天
BASELINE_MIN_SAMPLES = 10        # 优先池不足 10 次时扩容，避免 3-6 次小样本提前命中
BASELINE_FALLBACK_MIN_SAMPLES = 3  # 全部候选仍不足 10 次时，保留最宽可用池的降级能力

# ============ 夏季规则（PRD F2：模块级常量）============
# 依据：老板体感 25-27°C 舒适、28°C+ 才是热；25°C 阈值会让 56/60 次训练都成"夏季"
SUMMER_MONTHS = {6, 7, 8, 9}     # 夏季日期维度：6-9 月
SUMMER_TEMP_THRESHOLD = 28.0     # 夏季气温维度：中值温度 > 此值
SUMMER_SLOPE_MULT = 2.0          # 夏季内长期判定阈值放宽倍数（心率±1→±2、配速±2→±4、效率±1→±2）

# ============ 温度过滤豁免课型（PRD F1：模块级常量）============
# 依据：老板 2026-10-25 指令——LSD 是「时间、天气、状态都合适才安排」的条件自筛选课型，
# 跑了 LSD 即说明当天具备比较基础，因此 LSD 对比不需要温度过滤、直接全部同池对比
NO_TEMP_FILTER_CATEGORIES = {'lsd'}

# ============ 统计证据门槛（5.0 第二批：F1—F5，模块级常量）============
# 原则：中位数/差值/斜率等描述级数据尽量保留；方向性 verdict 由样本量、
# 温度可比性与单月敏感性共同决定，证据等级只由本内核计算。
SHORT_TERM_DESCRIPTIVE_MIN = 3     # 短期 n≥3 才形成基线描述（以下 n<3 数据不足）
SHORT_TERM_DIRECTIONAL_MIN = 5     # 短期 n≥5 才允许沿用现有阈值输出方向 verdict；3≤n<5 仅作描述
YOY_METRIC_MIN_SAMPLES = 3         # 同比每指标有效样本 ≥3 才展示该指标中位数
YOY_MIN_MONTHS = 3                 # 同比月斜率至少 3 个有效月份
LONG_TERM_MIN_MONTHS = 3           # 长期回归至少 3 个有效月份
PERCENTILE_MIN_VALID = 10          # 历史百分位有效效率样本 ≥10 才排名（第二批由 5 提高到 10）


# ============ Pa:Hr 统一选段（5.0 第一批 F2：当前活动与历史趋势图共用）============
# 普通课型（轻松跑/LSD/比赛/有氧耐力跑等）：全部有效分圈，保持现状；
# tempo_run：仅人工 pa_hr_laps 指定的连续分圈；缺段或选段失败不回退整场；
# intensity_run：默认不计算（interval_not_applicable），明确指定连续稳态段才计算该段。
PA_HR_MANUAL_CATEGORIES = ('tempo_run', 'intensity_run')


def _norm_lap_index(value):
    """把 lap_index 归一为 int；缺失/非法（含 pandas NA）返回 None"""
    if value is None or pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def select_pa_hr_scope(category: str, laps: list, lap_start=None, lap_end=None) -> dict:
    """统一 Pa:Hr 选段（当前活动与历史 Pa:Hr 趋势图共用同一规则）

    Args:
        category: 有效课型（已应用人工覆盖后的 category）
        laps: 原始分圈列表（含 lap_index / distance(_m) / duration(_sec) / avg_hr）
        lap_start / lap_end: 人工工作段起止 lap_index（两端均包含，仅节奏跑/间歇跑使用）

    Returns:
        {'scope': 'full_activity' | 'manual_segment' | 'not_applicable',
         'segment_laps': [start, end] | None,
         'reason': None | 'missing_manual_segment' | 'interval_not_applicable' | 'insufficient_lap_data',
         'laps': 选段后的分圈列表 | None}
        人工课型选段失败时 scope='not_applicable'，绝不回退整场。
    """
    category = category or ''
    if category not in PA_HR_MANUAL_CATEGORIES:
        return {'scope': 'full_activity', 'segment_laps': None, 'reason': None, 'laps': laps}

    lap_start = _norm_lap_index(lap_start)
    lap_end = _norm_lap_index(lap_end)
    if lap_start is None or lap_end is None:
        reason = 'missing_manual_segment' if category == 'tempo_run' else 'interval_not_applicable'
        return {'scope': 'not_applicable', 'segment_laps': None, 'reason': reason, 'laps': None}

    segment = []
    for lap in laps or []:
        idx = _norm_lap_index(lap.get('lap_index', lap.get('lap')))
        if idx is not None and lap_start <= idx <= lap_end:
            segment.append(lap)
    if not segment:
        return {'scope': 'not_applicable', 'segment_laps': [lap_start, lap_end],
                'reason': 'insufficient_lap_data', 'laps': None}
    return {'scope': 'manual_segment', 'segment_laps': [lap_start, lap_end],
            'reason': None, 'laps': segment}


class DeepRunAnalyzer:
    """跑步深度分析器"""

    # 心率默认值（从 DEFAULT_CONFIG 统一读取）
    DEFAULT_MAX_HR = DEFAULT_CONFIG.get('max_hr')
    DEFAULT_RESTING_HR = DEFAULT_CONFIG.get('resting_hr')

    def __init__(self, df_all: pd.DataFrame, target_date=None, max_hr: int = None, resting_hr: int = None,
                 lap_data: dict = None, raw_laps: list = None, race_plan: dict = None):
        """
        Args:
            df_all: 完整 DataFrame（包含所有跑步记录，用于对比分析）
            target_date: 对比基准日期，取该日期之前的历史数据
            max_hr: 最大心率（默认从 DEFAULT_CONFIG 读取）
            resting_hr: 静息心率（默认从 DEFAULT_CONFIG 读取）
            lap_data: 分圈数据 dict，格式见需求文档（current/history_median/history_p20_pace/history_p80_pace/sample_size）
            raw_laps: 原始分圈数据列表（含 distance_m/duration_sec/avg_hr），用于 Pa:Hr 计算
            race_plan: 结构化比赛计划（5.0.2 F5，load_race_plan 的规范化输出）；
                       仅当活动 category 与计划一致时计算赛段证据，无配置为 None
        """
        self.df_all = df_all
        self.target_date = target_date
        # 使用传入值，未传入时从 DEFAULT_CONFIG 读取
        self.max_hr = max_hr or self.DEFAULT_MAX_HR
        self.resting_hr = resting_hr or self.DEFAULT_RESTING_HR
        self.lap_data = lap_data or {}
        self.raw_laps = raw_laps or []
        self.race_plan = race_plan
        # 技术基线状态（5.0.2 F3）：'comparable' / 'insufficient_baseline'，普通课型 Prompt 区分使用
        self._tech_status = None
    
    def analyze(self, row: pd.Series) -> dict:
        """对单次跑步进行深度分析
        
        Returns:
            结构化分析结果 dict，包含以下键：
            - summary: 本次跑步总结
            - intensity: 强度与负荷分析
            - efficiency: 效率与技术分析
            - comparison: 对比分析结果
            - findings: 关键发现
            - raw_data: 原始数据（供 LLM 使用）
        """
        result = {}
        result['raw_data'] = self._extract_raw_data(row)
        result['summary'] = self._build_summary(row)
        result['intensity'] = self._analyze_intensity(row)
        result['efficiency'] = self._analyze_efficiency(row)
        result['comparison'] = self._compare_with_history(row)
        result['findings'] = self._extract_findings(result)
        result['hr_zone_ranges'] = self._get_hr_zone_ranges(row)
        # 分圈分析结果
        result['laps'] = self.lap_data
        
        # Pa:Hr 有氧解耦分析（统一选段：普通课型整场；节奏跑人工工作段；间歇跑默认不适用）
        result['pa_hr'], result['pa_hr_context'] = self._calc_pa_hr_scoped(row)

        # 确定性问题探测器（PRD F2）
        result['issues'] = self._detect_issues(row, result)

        # 5.0.2 F4：数据/配置提示（当前仅比赛 max_hr 超配置一种；非比赛为空列表）
        result['data_notes'] = self._detect_data_notes(row)

        # 5.0.2 F5：结构化比赛计划赛段证据（仅当计划 category 与本场一致时计算）
        result['race_plan'] = None
        if self.race_plan and row.get('category') == self.race_plan.get('category'):
            mn_temp = row.get('min_temperature')
            mx_temp = row.get('max_temperature')
            temp_mid = None
            if (mn_temp is not None and mx_temp is not None
                    and not pd.isna(mn_temp) and not pd.isna(mx_temp)):
                temp_mid = round((float(mn_temp) + float(mx_temp)) / 2, 1)
            humidity = row.get('avg_humidity')
            if humidity is not None and pd.isna(humidity):
                humidity = None
            try:
                result['race_plan'] = compute_plan_evidence(
                    self.race_plan, self.raw_laps,
                    temp_mid=temp_mid, humidity=humidity)
            except Exception as e:
                logger.error(f"比赛计划证据计算失败: {e}")

        return result
    
    def _get_hr_zone_ranges(self, row: pd.Series) -> dict:
        """获取心率区间范围（bpm）
        
        始终使用用户配置的 max_hr 和 resting_hr（来自 USER_CONFIG），
        不使用单次跑步的实际 max_hr（那是当次峰值，不是用户生理上限）。
        """
        # 固定使用用户配置的心率参数
        max_hr = self.max_hr
        resting_hr = self.resting_hr
        
        # 使用 HR_ZONE_PERCENTAGES 定义（Karvonen HRR 法固定百分比）
        HRR = max_hr - resting_hr
        result = {}
        prev_high = None
        for zone_key, zone_info in HR_ZONE_PERCENTAGES.items():
            min_hr = int(resting_hr + HRR * zone_info['min_pct'])
            max_hr_val = int(resting_hr + HRR * zone_info['max_pct'])
            if prev_high is not None and min_hr <= prev_high:
                min_hr = prev_high + 1
            result[zone_key] = {
                'label': zone_info['name'],
                'min_hr': min_hr,
                'max_hr': max_hr_val
            }
            prev_high = max_hr_val
        return result
    
    def _extract_raw_data(self, row: pd.Series) -> dict:
        """提取用于 LLM 的原始数据"""
        def safe(val, default=0):
            if val is None or pd.isna(val): return default
            return val
        
        return {
            'date': str(row.get('date', ''))[:10],
            'title': safe(row.get('title'), ''),
            'distance_km': safe(row.get('distance'), 0),
            'duration_min': safe(row.get('duration_min'), 0),
            'avg_pace': safe(row.get('avg_pace_fmt'), '--'),
            'avg_hr': safe(row.get('avg_hr'), 0),
            'max_hr': safe(row.get('max_hr'), 0),
            'avg_power': safe(row.get('avg_power'), 0),
            'max_power': safe(row.get('max_power'), 0),
            'norm_power': safe(row.get('normalized_power'), 0),
            'cadence': safe(row.get('cadence'), 0),
            'stride_length_cm': safe(row.get('stride_length'), 0),
            'vertical_ratio_pct': safe(row.get('vertical_ratio'), 0),
            'ground_contact_ms': safe(row.get('ground_contact_time'), 0),
            'calories': safe(row.get('calories'), 0),
            'aerobic_te': safe(row.get('aerobic_training_effect'), 0),
            'anaerobic_te': safe(row.get('anaerobic_training_effect'), 0),
            'te_label': safe(row.get('training_effect_label'), ''),
            'vO2_max': safe(row.get('vO2_max'), 0),
            'category': safe(row.get('category'), ''),
            'category_name': safe(row.get('category_name'), '跑步'),
            'activity_id': safe(row.get('activity_id'), 'unknown'),
            'bmr_calories': safe(row.get('bmr_calories'), 0),
            'min_temperature': row.get('min_temperature'),
            'max_temperature': row.get('max_temperature'),
            # 分圈数据：圈数
            'lap_count': len(self.lap_data.get('current', [])) if self.lap_data else 0,
        }
    
    def _build_summary(self, row: pd.Series) -> dict:
        """本次跑步总结"""
        # 主区间判定：按 hrTimeInZone 占比最大者
        hr_zones = {
            'Z1-有氧基础': row.get('hr_zone_1_sec', 0),
            'Z2-有氧耐力': row.get('hr_zone_2_sec', 0),
            'Z3-乳酸阈值': row.get('hr_zone_3_sec', 0),
            'Z4-无氧耐力': row.get('hr_zone_4_sec', 0),
            'Z5-最大强度': row.get('hr_zone_5_sec', 0),
        }
        total_hr_time = sum(hr_zones.values())
        hr_zone_pct = {k: v/total_hr_time*100 if total_hr_time > 0 else 0 for k, v in hr_zones.items()}
        dominant_zone = max(hr_zone_pct, key=hr_zone_pct.get) if total_hr_time > 0 else '未知'
        
        return {
            'dominant_zone': dominant_zone,
            'zone_pct': hr_zone_pct,
            'distance': row.get('distance', 0),
            'duration_min': row.get('duration_min', 0),
            'avg_hr': row.get('avg_hr', 0),
            'max_hr': row.get('max_hr', 0),
            'avg_power': row.get('avg_power', 0),
            'cadence': row.get('cadence', 0),
            'vertical_ratio': row.get('vertical_ratio', 0),
        }
    
    def _analyze_intensity(self, row: pd.Series) -> dict:
        """强度与负荷分析"""
        total_hr = sum(row.get(f'hr_zone_{i}_sec', 0) for i in range(1, 6))
        total_power = sum(row.get(f'power_zone_{i}_sec', 0) for i in range(1, 6))
        
        hr_pct = {f'Z{i}': row.get(f'hr_zone_{i}_sec', 0)/total_hr*100 if total_hr > 0 else 0 for i in range(1, 6)}
        power_pct = {f'Z{i}': row.get(f'power_zone_{i}_sec', 0)/total_power*100 if total_power > 0 else 0 for i in range(1, 6)}
        
        return {
            'avg_hr': row.get('avg_hr', 0),
            'max_hr': row.get('max_hr', 0),
            'hr_zone_pct': hr_pct,
            'avg_power': row.get('avg_power', 0),
            'max_power': row.get('max_power', 0),
            'norm_power': row.get('normalized_power', 0),
            'power_zone_pct': power_pct,
            'aerobic_te': row.get('aerobic_training_effect', 0),
            'anaerobic_te': row.get('anaerobic_training_effect', 0),
            'te_label': row.get('training_effect_label', ''),
            'calories': row.get('calories', 0),
            'bmr_calories': row.get('bmr_calories', 0),
        }
    
    def _analyze_efficiency(self, row: pd.Series) -> dict:
        """效率与技术分析"""
        cadence = row.get('cadence', 0)
        stride = row.get('stride_length', 0)
        vr = row.get('vertical_ratio', 0)
        gct = row.get('ground_contact_time', 0)
        
        # 处理 None/NaN
        if pd.isna(cadence): cadence = 0
        if pd.isna(stride): stride = 0
        if pd.isna(vr): vr = 0
        if pd.isna(gct): gct = 0
        
        # 评价参考
        cadence_eval = self._eval_cadence(cadence)
        vr_eval = self._eval_vertical_ratio(vr) if vr > 0 else '暂无数据'
        gct_eval = self._eval_ground_contact(gct) if gct > 0 else '暂无数据'
        
        return {
            'cadence': cadence,
            'cadence_eval': cadence_eval,
            'stride_length_cm': stride,
            'vertical_ratio_pct': vr,
            'vertical_ratio_eval': vr_eval,
            'ground_contact_ms': gct,
            'ground_contact_eval': gct_eval,
        }
    
    def _eval_cadence(self, cadence: float) -> str:
        if cadence >= 180: return '优秀'
        elif cadence >= 170: return '良好'
        elif cadence >= 160: return '一般'
        else: return '偏低，建议提高步频训练'
    
    def _eval_vertical_ratio(self, vr: float) -> str:
        if vr <= 6.3: return '优秀'
        elif vr <= 8.0: return '良好'
        elif vr <= 10.0: return '一般'
        else: return '偏高，建议加强核心和下肢力量'
    
    def _eval_ground_contact(self, gct: float) -> str:
        if gct <= 210: return '优秀'
        elif gct <= 240: return '良好'
        elif gct <= 270: return '一般'
        else: return '偏长，建议加强弹跳和节奏训练'
    
    def _compare_with_history(self, row: pd.Series) -> dict:
        """对比分析：同类型 + 同温区 + 90天滚动窗口 + 中位数/P20-P80 + 状态评估与趋势分析"""
        df = self.df_all.copy()

        # 类型归一化
        df['_category_norm'] = df['category'].apply(
            lambda c: 'race' if c in ('full_marathon', 'half_marathon', 'race_event') else c
        )
        category = row.get('category', '')
        category_norm = 'race' if category in ('full_marathon', 'half_marathon', 'race_event') else category

        # 5.0.2 F1：半马/全马走同距离比赛成绩参照池（不混池、无任何窗口/温区/强度过滤）
        if category in RACE_CATEGORIES:
            return self._compare_race_history(row, df)

        # 同类筛选
        if category and '_category_norm' in df.columns:
            df_same = df[df['_category_norm'] == category_norm]
        else:
            df_same = df
        
        # 排除本次
        activity_id = row.get('activity_id')
        if activity_id:
            df_same = df_same[df_same['activity_id'] != activity_id]
        elif self.target_date is not None:
            df_same = df_same[df_same['date'] != pd.Timestamp(self.target_date)]
        
        if self.target_date is not None:
            target_ts = pd.Timestamp(self.target_date)
            df_same = df_same[df_same['date'] <= target_ts]
        
        # 温区分桶匹配（三档：<15℃ / 15-25℃ / >25℃）
        target_bucket = self._get_temp_bucket(row)

        # 中位数基线放宽链：90天同温区 → 90天不限温区 → 180天不限温区。
        # 优先池至少 10 次才直接采用；若所有池都不足 10 次，保留最宽的 ≥3 次池兜底。
        target_ts = pd.Timestamp(self.target_date) if self.target_date is not None else None

        def _base_candidates() -> pd.DataFrame:
            """同类型候选，排除本次与目标日之后的数据"""
            d = df[df['_category_norm'] == category_norm] if (category_norm and '_category_norm' in df.columns) else df
            if activity_id:
                d = d[d['activity_id'] != activity_id]
            elif target_ts is not None:
                d = d[d['date'] != target_ts]
            if target_ts is not None:
                d = d[d['date'] <= target_ts]
            return d

        baseline_scope = None
        baseline_window = None  # 5.0.1 F2：'90d' / '180d' / 'all_history'
        if target_ts is not None:
            fallback = None
            for window_days, scope in ((90, 'same_temp'), (90, 'all_temp'), (180, 'all_temp')):
                d = _base_candidates()
                d = d[d['date'] >= target_ts - pd.Timedelta(days=window_days)]
                if 'min_temperature' in d.columns and 'max_temperature' in d.columns:
                    d = d.copy()
                    d['_temp_bucket'] = d.apply(lambda r: self._get_temp_bucket(r), axis=1)
                    # 无温区记录不进入基线，避免把缺失温度误判为冷天
                    d = d[d['_temp_bucket'].notna()]
                    if scope == 'same_temp' and target_bucket is not None:
                        d = d[d['_temp_bucket'] == target_bucket]
                if len(d) >= BASELINE_MIN_SAMPLES:
                    df_same = d.sort_values('date', ascending=False)
                    baseline_scope = scope
                    baseline_window = f'{window_days}d'
                    break
                if len(d) >= BASELINE_FALLBACK_MIN_SAMPLES:
                    fallback = (d.sort_values('date', ascending=False), scope, f'{window_days}d')
            else:
                if fallback is not None:
                    df_same, baseline_scope, baseline_window = fallback
                else:
                    # 5.0.1 F2：跨全年描述性兜底（同类型归并池、不限温区、≥3 次）
                    d = _base_candidates()
                    if len(d) >= BASELINE_FALLBACK_MIN_SAMPLES:
                        df_same = d.sort_values('date', ascending=False)
                        baseline_scope = 'all_temp'
                        baseline_window = 'all_history'
                    else:
                        df_same = pd.DataFrame(columns=df.columns)
        else:
            # 无目标日期：不限制窗口与温区（保持原行为）
            df_same = _base_candidates()
            baseline_scope = 'all_temp'
        
        # 上限15次，避免样本过多时过度平均
        if len(df_same) > 15:
            df_same = df_same.head(15)
        
        # 独立模块（5.0.1 F3：即使整体基线为空也必须计算，不得提前丢弃）
        indep_modules = self._independent_modules(row, category_norm, target_bucket, df)

        if len(df_same) < 1:
            # 整体对比为空：保留空状态与原因，但短期/长期等模块独立计算返回
            result = {
                'sample_size': 0,
                'message': '最近无同类型跑步记录，无法对比',
                'ability': {},
                'economy': {},
                'temp_bucket': target_bucket,
                'baseline_scope': baseline_scope,
            }
            result.update(indep_modules)
            return result

        # 3.1 能力变化
        dist = row.get('distance', 0)
        dist_tolerance = dist * 0.2  # ±20% 距离容忍
        df_near = df_same[(df_same['distance'] >= dist * 0.8) & (df_same['distance'] <= dist * 1.2)]
        # 距离相近样本不足时降级为同温区样本
        near_subset_size = len(df_near) if len(df_near) >= 3 else None
        df_compare = df_near if len(df_near) >= 3 else df_same

        # 统计工具函数
        def stats(series):
            """返回中位数、P20、P80"""
            return {
                'median': round(series.median(), 2),
                'p20': round(series.quantile(0.20), 2),
                'p80': round(series.quantile(0.80), 2),
            }

        # 5.0.1 F2：跨全年兜底只作描述，展示与判断分离
        descriptive_only = baseline_window == 'all_history'

        result = {
            'sample_size': len(df_same),
            'ability': {},
            'economy': {},
            'temp_bucket': target_bucket,
            'baseline_scope': baseline_scope,
            'near_subset_size': near_subset_size,
        }
        if baseline_window:
            result['baseline_window'] = baseline_window
        if descriptive_only:
            result['descriptive_only'] = True
        
        # 心率变化
        if 'avg_hr' in df_compare.columns and df_compare['avg_hr'].notna().any():
            s = df_compare['avg_hr'].dropna()
            st = stats(s)
            curr_hr = row.get('avg_hr', 0)
            hr_diff = curr_hr - st['median'] if st['median'] > 0 else 0
            result['ability']['hr_trend'] = {
                'current': round(curr_hr, 0),
                'history_median': st['median'],
                'history_p20': st['p20'],
                'history_p80': st['p80'],
                'diff': round(hr_diff, 0),
                'verdict': '更轻松' if hr_diff < -3 else ('更累' if hr_diff > 3 else '持平'),
            }
        
        # 配速变化
        if 'avg_pace_sec' in df_compare.columns and df_compare['avg_pace_sec'].notna().any():
            s = df_compare['avg_pace_sec'].dropna()
            st = stats(s)
            curr_pace = row.get('avg_pace_sec', 0)
            pace_diff = curr_pace - st['median']
            result['ability']['pace_trend'] = {
                'current': round(curr_pace, 0),
                'history_median': st['median'],
                'history_p20': st['p20'],
                'history_p80': st['p80'],
                'diff': round(pace_diff, 0),
                'verdict': '更快' if pace_diff < -5 else ('更慢' if pace_diff > 5 else '持平'),
            }
        
        # 功率变化
        if 'avg_power' in df_compare.columns and df_compare['avg_power'].notna().any():
            s = df_compare['avg_power'].dropna()
            st = stats(s)
            curr_power = row.get('avg_power', 0)
            power_diff = curr_power - st['median']
            result['ability']['power_trend'] = {
                'current': round(curr_power, 0),
                'history_median': st['median'],
                'history_p20': st['p20'],
                'history_p80': st['p80'],
                'diff': round(power_diff, 0),
                'verdict': '更高' if power_diff > 10 else ('更低' if power_diff < -10 else '持平'),
            }
        
        # 3.2 跑步经济性
        if 'vertical_ratio' in df_same.columns and df_same['vertical_ratio'].notna().any():
            s = df_same['vertical_ratio'].dropna()
            st = stats(s)
            curr_vr = row.get('vertical_ratio', 0)
            vr_diff = curr_vr - st['median']
            result['economy']['vr_trend'] = {
                'current': round(curr_vr, 1),
                'history_median': st['median'],
                'history_p20': st['p20'],
                'history_p80': st['p80'],
                'diff': round(vr_diff, 1),
                'verdict': '更经济' if vr_diff < -0.2 else ('更费力' if vr_diff > 0.2 else '持平'),
            }
        
        if 'cadence' in df_same.columns and df_same['cadence'].notna().any():
            s = df_same['cadence'].dropna()
            st = stats(s)
            curr_cad = row.get('cadence', 0)
            cad_diff = curr_cad - st['median']
            result['economy']['cadence_trend'] = {
                'current': round(curr_cad, 0),
                'history_median': st['median'],
                'history_p20': st['p20'],
                'history_p80': st['p80'],
                'diff': round(cad_diff, 0),
                'verdict': '更稳定' if abs(cad_diff) < 3 else ('波动较大' if abs(cad_diff) > 8 else '基本稳定'),
            }
        
        # 效率：时速(m/h)÷心率(bpm)，值越大越好
        if ('avg_hr' in df_compare.columns and 'avg_pace_sec' in df_compare.columns
            and df_compare['avg_hr'].notna().any() and df_compare['avg_pace_sec'].notna().any()):
            df_valid = df_compare[(df_compare['avg_hr'] > 0) & (df_compare['avg_pace_sec'] > 0)].copy()
            if len(df_valid) > 0:
                # 效率 = 时速(m/h) ÷ 心率(bpm) = (3600×1000/配速秒) ÷ 心率 = 3600000 / (配速秒 × 心率)
                df_valid['efficiency'] = 3600000.0 / (df_valid['avg_pace_sec'] * df_valid['avg_hr'])
                st = stats(df_valid['efficiency'])
                curr_hr = row.get('avg_hr', 0)
                curr_pace = row.get('avg_pace_sec', 0)
                curr_eff = 3600000.0 / (curr_pace * curr_hr) if curr_pace > 0 and curr_hr > 0 else 0
                eff_diff = curr_eff - st['median']
                result['economy']['hr_pace_ratio'] = {
                    'current': round(curr_eff, 2),
                    'history_median': st['median'],
                    'history_p20': st['p20'],
                    'history_p80': st['p80'],
                    'diff': round(eff_diff, 2),
                    'verdict': '更经济' if eff_diff > 3 else ('更费力' if eff_diff < -3 else '持平'),
                    'unit': '(m/h)/bpm',
                }
        
        # 5.0.1 F2：跨全年兜底只作描述——剥离方向 verdict，禁止「更快/更累/更经济」等判断
        if descriptive_only:
            for group in ('ability', 'economy'):
                for metric in result[group].values():
                    metric.pop('verdict', None)

        # 新增：状态评估与趋势分析（5.0.1 F3：独立模块，与整体基线是否为空无关）
        result.update(indep_modules)

        return result

    def _independent_modules(self, row, category_norm, target_bucket, df,
                             tech_changes_marker: Optional[str] = None) -> dict:
        """短期/长期/技术/百分位/预期配速独立模块（5.0.1 F3）

        tech_changes_marker：None 时按普通课型计算 _calc_tech_changes（list）；
        'race' 时按同距离比赛池计算 _calc_tech_changes_race（dict，5.0.2 F3）。
        """
        st = self._calc_short_term(row, category_norm, target_bucket, df)
        lt = self._calc_long_term(row, category_norm, target_bucket, df)
        if tech_changes_marker == 'race':
            tc = self._calc_tech_changes_race(row, df, row.get('category', ''))
        else:
            tc = self._calc_tech_changes(row, df, category_norm)
        df_long_term, _lt_scope = self._get_long_term_baseline(row, category_norm, target_bucket, df)
        return {
            'short_term': st,
            'long_term': lt,
            'tech_changes': tc,
            'tech_status': getattr(self, '_tech_status', None),
            'percentile': self._calc_percentile(row, df_long_term),
            'expected_pace': self._calc_expected_pace(row, df_long_term),
        }

    def _compare_race_history(self, row: pd.Series, df: pd.DataFrame) -> dict:
        """5.0.2 F1：同距离比赛成绩参照池

        池 = 同一精确 category + 目标日期之前 + 排除当前 activity_id 的全部历史比赛。
        不执行 90/180 天窗口、温区、功率/配速相近、距离 ±20% 子集、赛道/爬升/海拔/
        比赛目标等任何排除；条件差异只用于解释差异，不用于排除样本（老板决策）。
        成绩/执行比较允许；纯能力方向结论不得仅凭该池推出。
        """
        category = row.get('category', '')
        category_norm = 'race'  # 短期/长期等独立模块沿用既有归一化口径（5.0.1 行为不变）
        activity_id = row.get('activity_id')
        target_ts = pd.Timestamp(self.target_date) if self.target_date is not None else None

        pool = df[df['category'] == category]
        if activity_id:
            pool = pool[pool['activity_id'] != activity_id]
        if target_ts is not None:
            pool = pool[pool['date'] <= target_ts]
        pool = pool.sort_values('date', ascending=False)
        n = len(pool)

        result = {
            'comparison_kind': 'same_distance_race_history',
            'pool_category': category,
            'baseline_window': 'all_history',
            'baseline_scope': 'all_temp',
            'result_comparison_allowed': True,
            'ability_verdict_allowed': False,
            'sample_size': n,
            'temp_bucket': self._get_temp_bucket(row),
            'ability': {},
            'economy': {},
        }

        # 逐场上下文字段（供解释差异；缺失字段明确未知，不补 0）
        activities = []
        for _, r in pool.iterrows():
            def _f(col):
                v = r.get(col)
                return float(v) if v is not None and not pd.isna(v) else None
            pace = _f('avg_pace_sec')
            hr = _f('avg_hr')
            activities.append({
                'date': str(r.get('date', ''))[:10],
                'title': r.get('title') if pd.notna(r.get('title')) else None,
                'distance_km': _f('distance'),
                'duration_min': _f('duration_min'),
                'avg_pace_sec': pace,
                'avg_hr': hr,
                'avg_power': _f('avg_power'),
                'efficiency': (round(3600000.0 / (pace * hr), 2)
                               if pace and hr and pace > 0 and hr > 0 else None),
                'min_temperature': _f('min_temperature'),
                'max_temperature': _f('max_temperature'),
                'elevation_gain': _f('elevation_gain'),
            })
        if activities:
            result['pool_activities'] = activities

        if n < 1:
            result['message'] = f'无历史{category}比赛记录，无法对比'
            result.update(self._independent_modules(
                row, category_norm, result['temp_bucket'], df, tech_changes_marker='race'))
            return result

        def _pool_stats(col: str) -> Optional[dict]:
            """中位数+范围（n≥2）；n==1 返回唯一值不包装成统计中位数"""
            if col not in pool.columns or not pool[col].notna().any():
                return None
            s = pool[col].dropna()
            st = {'median': round(float(s.median()), 2),
                  'min': round(float(s.min()), 2),
                  'max': round(float(s.max()), 2),
                  'n': int(len(s))}
            return st

        def _add_trend(group: str, key: str, col: str, curr, verdict_fn):
            st = _pool_stats(col)
            if st is None or curr is None or pd.isna(curr):
                return
            diff = round(float(curr) - st['median'], 2)
            trend = {
                'current': round(float(curr), 2),
                'history_median': st['median'],
                'history_min': st['min'],
                'history_max': st['max'],
                'sample_size': st['n'],
                'diff': diff,
                'verdict': verdict_fn(diff),
                'verdict_scope': 'result',  # 成绩/执行级描述，禁止解读为纯能力方向
            }
            result[group][key] = trend

        # 心率/配速/功率：与同距离历史中位数差值（成绩比较允许）
        _add_trend('ability', 'hr_trend', 'avg_hr', row.get('avg_hr'),
                   lambda d: '更低' if d < -3 else ('更高' if d > 3 else '持平'))
        _add_trend('ability', 'pace_trend', 'avg_pace_sec', row.get('avg_pace_sec'),
                   lambda d: '更快' if d < -5 else ('更慢' if d > 5 else '持平'))
        _add_trend('ability', 'power_trend', 'avg_power', row.get('avg_power'),
                   lambda d: '更高' if d > 10 else ('更低' if d < -10 else '持平'))

        # 效率（(m/h)/bpm）：同距离池内逐场计算后取中位数
        if 'avg_hr' in pool.columns and 'avg_pace_sec' in pool.columns:
            pv = pool[(pool['avg_hr'] > 0) & (pool['avg_pace_sec'] > 0)]
            if len(pv) > 0:
                eff = 3600000.0 / (pv['avg_pace_sec'] * pv['avg_hr'])
                st = {'median': round(float(eff.median()), 2),
                      'min': round(float(eff.min()), 2),
                      'max': round(float(eff.max()), 2),
                      'n': int(len(pv))}
                curr_hr = row.get('avg_hr', 0)
                curr_pace = row.get('avg_pace_sec', 0)
                if curr_pace and curr_hr and curr_pace > 0 and curr_hr > 0:
                    curr_eff = 3600000.0 / (curr_pace * curr_hr)
                    diff = round(curr_eff - st['median'], 2)
                    result['economy']['hr_pace_ratio'] = {
                        'current': round(curr_eff, 2),
                        'history_median': st['median'],
                        'history_min': st['min'],
                        'history_max': st['max'],
                        'sample_size': st['n'],
                        'diff': diff,
                        'verdict': '更高' if diff > 1 else ('更低' if diff < -1 else '持平'),
                        'verdict_scope': 'result',
                        'unit': '(m/h)/bpm',
                    }

        # 状态评估与趋势分析（5.0.1 F3 独立模块；比赛技术走同距离池 F3）
        result.update(self._independent_modules(
            row, category_norm, result['temp_bucket'], df, tech_changes_marker='race'))
        return result

    def _calc_tech_changes_race(self, row: pd.Series, df_all: pd.DataFrame, category: str) -> dict:
        """5.0.2 F3：比赛技术参照 = 同距离全部历史比赛

        - 不混全马/半马，不执行功率 ±8W / 配速 ±15s 硬筛选，不宣称「相近功率基线」；
        - 同距离池 <3 场：status='insufficient_baseline'，不作技术评价，
          问题探测器同步不触发（self._tech_baseline_info 置 None）；
        - 步幅/步频只作配速/功率变化的机械背景（background），不进变化清单；
        - VR/GCT 返回 direction='change'，不得自动写 improved。
        """
        self._tech_baseline_info = None
        pool = df_all[df_all['category'] == category]
        activity_id = row.get('activity_id')
        if activity_id:
            pool = pool[pool['activity_id'] != activity_id]
        target_ts = pd.Timestamp(self.target_date) if self.target_date is not None else None
        if target_ts is not None:
            pool = pool[pool['date'] <= target_ts]
        pool = pool.sort_values('date', ascending=False)

        result = {
            'kind': 'race',
            'pool_category': category,
            'sample_size': len(pool),
        }
        if len(pool) < RACE_TECH_MIN_SAMPLES:
            self._tech_status = 'insufficient_baseline'
            result['status'] = 'insufficient_baseline'
            return result

        # 与问题探测器共用同一口径（F3：技术异常探测器必须使用同一参照池）
        self._tech_status = 'comparable'
        self._tech_baseline_info = {
            'df': pool,
            'sample_size': len(pool),
            'dates': [str(x)[:10] for x in pool['date']] if 'date' in pool.columns else [],
            'kind': 'race',
        }
        result['status'] = 'comparable'

        def hist_median(col: str):
            if col in pool.columns and pool[col].notna().any():
                return float(pool[col].dropna().median())
            return None

        changes = []
        for col, label, unit in (('vertical_ratio', '垂直振幅比', '%'),
                                 ('ground_contact_time', '触地时间', 'ms')):
            baseline = hist_median(col)
            curr = row.get(col)
            if baseline is None or curr is None or pd.isna(curr):
                continue
            diff = round(float(curr) - baseline, 2)
            if diff == 0:
                continue
            changes.append({
                'metric': label,
                'field': col,
                'current': round(float(curr), 2),
                'baseline': round(baseline, 2),
                'diff': diff,
                'unit': unit,
                'direction': 'change',  # 只称变化，不自动等同改善
            })
        result['changes'] = changes

        background = {}
        for col, label, unit in (('stride_length', '步幅', 'cm'), ('cadence', '步频', 'spm')):
            baseline = hist_median(col)
            curr = row.get(col)
            if curr is None or pd.isna(curr):
                continue
            background[label] = {
                'current': round(float(curr), 2),
                'pool_median': round(baseline, 2) if baseline is not None else None,
                'unit': unit,
            }
        result['background'] = background
        return result
    
    def _extract_findings(self, result: dict) -> list:
        """从分析结果中提取原始信号（指标/差值/方向），供 LLM 选择性融合进点评"""
        findings = []
        comparison = result.get('comparison', {})
        # 5.0.1 F2：跨全年描述性兜底不得产出方向性原始信号，避免点评写出方向结论
        if comparison.get('descriptive_only'):
            return findings
        ability = comparison.get('ability', {})
        economy = comparison.get('economy', {})

        if 'hr_trend' in ability:
            t = ability['hr_trend']
            if abs(t['diff']) > 3:
                findings.append({'metric': '心率', 'diff': t['diff'], 'unit': 'bpm', 'direction': '下降' if t['diff'] < 0 else '上升'})

        if 'pace_trend' in ability:
            t = ability['pace_trend']
            if abs(t['diff']) > 5:
                findings.append({'metric': '配速', 'diff': t['diff'], 'unit': '秒/公里', 'direction': '提升' if t['diff'] < 0 else '下降'})

        if 'power_trend' in ability:
            t = ability['power_trend']
            if abs(t['diff']) > 10:
                findings.append({'metric': '功率', 'diff': t['diff'], 'unit': 'W', 'direction': '增强' if t['diff'] > 0 else '下降'})

        if 'vr_trend' in economy:
            t = economy['vr_trend']
            if abs(t['diff']) > 0.5:
                findings.append({'metric': '垂直振幅比', 'diff': t['diff'], 'unit': '%', 'direction': '改善' if t['diff'] < 0 else '下降'})

        if 'hr_pace_ratio' in economy:
            t = economy['hr_pace_ratio']
            if abs(t['diff']) > 1:
                findings.append({'metric': '效率((m/h)/bpm)', 'diff': t['diff'], 'unit': '', 'direction': '提升' if t['diff'] > 0 else '下降'})

        return findings
    
    def _analyze_laps(self, lap_data: list[dict], recent_laps: list[list[dict]],
                      median_min_samples: Optional[int] = None,
                      race_history_label: Optional[str] = None) -> dict:
        """分析分圈数据，对比历史同类型（5.0.1 F1：每公里历史统计唯一入口）

        每公里历史中位数/P20-P80/有效样本统一由
        src.lap_history_stats.compute_per_km_history_stats 计算，
        结构化 analysis_data、Prompt 与两张分圈图表共用同一份结果。
        残圈口径与图表一致：历史 distance_m < 950 剔除（缺距离保守保留）。

        Args:
            lap_data: 本次分圈数据列表
            recent_laps: 前 N 次同类型分圈数据列表，每个元素是一次跑步的分圈列表
            median_min_samples: 中位线每公里最低有效样本（5.0.2 F2 比赛传
                                RACE_LAP_MEDIAN_MIN_SAMPLES=3；None 用默认 5）
            race_history_label: 比赛参考标签（如「3 场半马参考中位」），
                                传入时结果附 race_ref 元数据供 Prompt/图表注明实际场次数

        Returns:
            分圈分析结果 dict
        """
        # 本次残圈过滤保持原 Prompt 口径（>=1000m）；本次曲线与横轴展示不在本批调整
        if lap_data:
            lap_data = [lap for lap in lap_data if lap.get('distance_m', 0) >= 1000]
        if not lap_data:
            return {}

        # 构建本次每圈数据
        current = []
        for lap in sorted(lap_data, key=lambda x: x.get('lap_index', 0)):
            current.append({
                'lap': lap.get('lap_index', 0),
                'pace_sec': lap.get('pace_sec_per_km', 0),
                'avg_hr': lap.get('avg_hr', 0) if not pd.isna(lap.get('avg_hr', 0)) else None,
                'avg_power': lap.get('avg_power', 0) if not pd.isna(lap.get('avg_power', 0)) else None,
                'elevation_gain': lap.get('elevation_gain_m', 0),
            })

        # 统一每公里历史统计（图表/Prompt 共用；不足值为 None，不以 0 冒充）
        history_stats = compute_per_km_history_stats(
            recent_laps, max_km=len(current),
            median_min_samples=median_min_samples)
        if history_stats['residual_dropped']:
            logger.info(
                f"分圈历史基线：剔除残圈 {history_stats['residual_dropped']} 圈"
                f"（distance_m<{LAP_RESIDUAL_MIN_M}）")

        history_median = []
        history_p20_pace, history_p80_pace = [], []
        history_p20_hr, history_p80_hr = [], []
        per_km_samples = []
        for lap_idx in range(1, len(current) + 1):
            e = history_stats['by_km'].get(lap_idx, {})
            history_median.append({
                'lap': lap_idx,
                'pace_sec': e.get('median_pace'),
                'avg_hr': e.get('median_hr'),
            })
            history_p20_pace.append(e.get('p20_pace'))
            history_p80_pace.append(e.get('p80_pace'))
            history_p20_hr.append(e.get('p20_hr'))
            history_p80_hr.append(e.get('p80_hr'))
            per_km_samples.append({
                'lap': lap_idx,
                'pace': e.get('pace_samples', 0),
                'hr': e.get('hr_samples', 0),
            })

        return {
            'current': current,
            'history_median': history_median,
            'history_p20_pace': history_p20_pace,
            'history_p80_pace': history_p80_pace,
            'history_p20_hr': history_p20_hr,
            'history_p80_hr': history_p80_hr,
            'per_km_samples': per_km_samples,
            'history_stats': history_stats,
            'sample_size': history_stats['sample_size'],
            'median_min_samples': history_stats.get('median_min_samples'),
            **({'race_ref': {
                'median_min_samples': RACE_LAP_MEDIAN_MIN_SAMPLES,
                'label': race_history_label,
                'sample_size': history_stats['sample_size'],
            }} if race_history_label else {}),
        }

    def _calc_tech_changes(self, row: pd.Series, df_all: pd.DataFrame, category_norm: str) -> list:
        """对比本次 vs 长期基线（3 个月前同类型相近功率跑步），仅列出有进步的指标

        基线选择链（PRD F1：心率口径 → 功率口径，避免体能/季节漂移误报技术进步）：
        1. 同类型 + date < 目标日-90天 + avg_power 与本次差值 ≤8W（≥3 样本，主口径）
        2. 样本 <3 → 同类型 + ≥90天前 + avg_pace_sec 与本次差值 ≤15 秒（≥3 样本，功率缺失兜底）
        3. 仍 <3 → 同类型 + ≥90天前（≥3 样本）
        4. 仍 <3 → 无基线，返回空列表

        进步判定阈值：vertical_ratio ≤-0.2、ground_contact_time ≤-5ms、
                      cadence ≥+2spm、stride_length ≥+1cm（退步/持平不进列表）

        选中的基线存入 self._tech_baseline_info（供验收打印与问题探测器 P80 使用）

        Returns:
            进步项列表，每项含 metric/current/baseline/diff/unit/direction('improved')
        """
        # 同类型候选，排除本次
        if category_norm and '_category_norm' in df_all.columns:
            d = df_all[df_all['_category_norm'] == category_norm]
        else:
            d = df_all
        activity_id = row.get('activity_id')
        if activity_id:
            d = d[d['activity_id'] != activity_id]

        target_ts = pd.Timestamp(self.target_date) if self.target_date is not None else None
        if target_ts is not None:
            d = d[d['date'] < target_ts - pd.Timedelta(days=TECH_BASELINE_MIN_DAYS)]

        self._tech_baseline_info = None
        self._tech_status = 'insufficient_baseline'
        if len(d) < TECH_BASELINE_MIN_SAMPLES:
            return []

        # 第一级：相近功率（±8W，主口径）；本次功率缺失时跳过该级
        baseline_df = None
        curr_power = row.get('avg_power')
        if curr_power is not None and not pd.isna(curr_power) and 'avg_power' in d.columns:
            dp = d[d['avg_power'].notna() & (abs(d['avg_power'] - curr_power) <= TECH_POWER_TOLERANCE_W)]
            if len(dp) >= TECH_BASELINE_MIN_SAMPLES:
                baseline_df = dp

        # 第二级：相近配速（±15 秒，功率缺失样本的兜底口径）
        if baseline_df is None:
            curr_pace = row.get('avg_pace_sec')
            if curr_pace is not None and not pd.isna(curr_pace) and 'avg_pace_sec' in d.columns:
                dpc = d[d['avg_pace_sec'].notna() & (abs(d['avg_pace_sec'] - curr_pace) <= TECH_PACE_TOLERANCE_SEC)]
                if len(dpc) >= TECH_BASELINE_MIN_SAMPLES:
                    baseline_df = dpc

        # 第三级：同类型 ≥90 天前全量（放宽链）
        if baseline_df is None:
            if len(d) < TECH_BASELINE_MIN_SAMPLES:
                return []
            baseline_df = d

        self._tech_status = 'comparable'
        self._tech_baseline_info = {
            'df': baseline_df,
            'sample_size': len(baseline_df),
            'dates': [str(x)[:10] for x in baseline_df['date']] if 'date' in baseline_df.columns else [],
            'powers': [round(float(x)) for x in baseline_df['avg_power'].dropna()] if 'avg_power' in baseline_df.columns else [],
        }

        def hist_median(col: str):
            if col in baseline_df.columns and baseline_df[col].notna().any():
                return baseline_df[col].dropna().median()
            return None

        specs = [
            ('vertical_ratio', '垂直振幅比', TECH_IMPROVE_VR, '%'),
            ('ground_contact_time', '触地时间', TECH_IMPROVE_GCT, 'ms'),
            ('cadence', '步频', TECH_IMPROVE_CADENCE, 'spm'),
            ('stride_length', '步幅', TECH_IMPROVE_STRIDE, 'cm'),
        ]

        changes = []
        for col, label, threshold, unit in specs:
            baseline = hist_median(col)
            curr = row.get(col)
            if baseline is None or curr is None or pd.isna(curr):
                continue
            diff = curr - baseline
            # 只报进步：阈值带符号，diff 需越过阈值才算进步
            if threshold < 0:
                if diff > threshold:
                    continue
            else:
                if diff < threshold:
                    continue
            changes.append({
                'metric': label,
                'field': col,
                'current': round(curr, 2),
                'baseline': round(baseline, 2),
                'diff': round(diff, 2),
                'unit': unit,
                'direction': 'improved',
            })
        return changes

    def _detect_issues(self, row: pd.Series, analysis_data: dict) -> list:
        """确定性问题探测器（PRD F2）：返回问题清单，每项含 title + evidence；全部不满足返回空列表

        探测器（阈值均为模块级常量，依据见常量注释）：
        1. 强度偏离课型：easy_run Z3+ 占比 >8%；aerobic_run Z4+ >20%；lsd Z2+ >25%（其他类型不检测）
        2. 心率漂移：Pa:Hr 有氧解耦 <= -5%（负值 = 后半程速度/心率效率下降；字段缺失/不适用则跳过）
        3. 负荷激增：training_load > 近4次（不限类型，排除本次）均值 × 1.5（有效样本 <2 则跳过）
        4. 心率异常：max_hr > USER_CONFIG['max_hr'] 或 > 近90天同类型 max_hr 的 P95（样本≥5 才启用后者）
        5. 技术指标异常：VR 或 GCT 劣于 F1 长跨度基线的 P80（基线存在才启用；仅作问题信号）

        5.0.2 F4：半马/全马比赛——探测器 2（Pa:Hr）、3（负荷激增）不适用；
        探测器 4（max_hr 超配置）不生成执行问题，转入 data_notes 数据提示；
        探测器 5 必须使用 F3 同距离比赛池（不足 3 场不触发，见 _calc_tech_changes_race）。
        非比赛课型全部探测器保持现状。
        """
        issues = []

        def _num(val):
            """取数值，None/NaN 返回 None"""
            if val is None or pd.isna(val):
                return None
            return float(val)

        category = row.get('category', '')
        is_race = category in RACE_CATEGORIES

        # 1. 强度偏离课型（占比 = 区间秒数 / 心率总时长）
        if category in ISSUE_INTENSITY_LIMITS:
            zone_start, limit_pct = ISSUE_INTENSITY_LIMITS[category]
            zones = [_num(row.get(f'hr_zone_{i}_sec', 0)) or 0 for i in range(1, 6)]
            total_sec = sum(zones)
            if total_sec > 0:
                high_sec = sum(zones[zone_start - 1:])
                high_pct = high_sec / total_sec * 100
                if high_pct > limit_pct:
                    zone_label = f'Z{zone_start}+'
                    issues.append({
                        'title': f'强度偏离课型：{zone_label} 时间占比 {high_pct:.1f}%（阈值 {limit_pct:.0f}%）',
                        'evidence': f'{zone_label} 区间 {high_sec:.0f} 秒 / 总时长 {total_sec:.0f} 秒 = {high_pct:.1f}%，超过 {category} 课型 {limit_pct:.0f}% 上限',
                    })

        # 2. 心率漂移（Pa:Hr 有氧解耦；负值 = 后半程速度/心率效率下降，如 -6.1% 触发，-4.99% 不触发）
        # 5.0.2 F4：比赛负分段前后强度不同，Pa:Hr 保留数值但不自动生成执行问题
        if not is_race:
            pa_hr = analysis_data.get('pa_hr')
            if pa_hr:
                pa_pct = _num(pa_hr.get('pa_hr_pct'))
                if pa_pct is not None and pa_pct <= -ISSUE_PA_HR_PCT:
                    issues.append({
                        'title': f'心率漂移：Pa:Hr 有氧解耦 {pa_pct:.1f}%（阈值 -{ISSUE_PA_HR_PCT:.0f}%）',
                        'evidence': f'后半程相比前半程速度/心率效率下降 {abs(pa_pct):.1f}%（Pa:Hr {pa_pct:+.1f}%），判定「{pa_hr.get("verdict", "未知")}」',
                    })

        # 3. 负荷激增（近 N 次不限类型，排除本次）
        # 5.0.2 F4：比赛负荷与赛前减量期近 4 次混合课型均值比较无意义，不适用
        if not is_race and 'training_load' in self.df_all.columns:
            df_hist = self.df_all
            activity_id = row.get('activity_id')
            if activity_id:
                df_hist = df_hist[df_hist['activity_id'] != activity_id]
            if self.target_date is not None:
                df_hist = df_hist[df_hist['date'] <= pd.Timestamp(self.target_date)]
            recent = df_hist.sort_values('date', ascending=False).head(ISSUE_LOAD_RECENT_N)
            loads = recent['training_load'].dropna()
            curr_load = _num(row.get('training_load'))
            if len(loads) >= ISSUE_LOAD_MIN_SAMPLES and curr_load is not None:
                mean_load = float(loads.mean())
                if mean_load > 0 and curr_load > mean_load * ISSUE_LOAD_RATIO:
                    issues.append({
                        'title': f'负荷激增：训练负荷 {curr_load:.0f} 为近{ISSUE_LOAD_RECENT_N}次均值 {mean_load:.0f} 的 {curr_load / mean_load:.1f} 倍（阈值 {ISSUE_LOAD_RATIO:.1f}）',
                        'evidence': f'近{ISSUE_LOAD_RECENT_N}次负荷：{"、".join(f"{x:.0f}" for x in loads)}，均值 {mean_load:.0f}，本次 {curr_load:.0f}',
                    })

        # 4. 心率异常（配置上限 或 近90天同类型 P95）
        # 5.0.2 F4：比赛 max_hr 超配置为设备/配置待核验，不进入执行问题（转 data_notes，见 _detect_data_notes）
        max_hr = _num(row.get('max_hr'))
        if max_hr is not None and not is_race:
            hr_parts = []
            config_max = USER_CONFIG.get('max_hr')
            if config_max and max_hr > config_max:
                hr_parts.append(f'超过配置最大心率 {config_max:.0f} bpm')
            # 近90天同类型 max_hr P95（样本≥5 才启用）
            if self.target_date is not None and '_category_norm' in self.df_all.columns:
                category_norm = 'race' if category in ('full_marathon', 'half_marathon', 'race_event') else category
                target_ts = pd.Timestamp(self.target_date)
                d = self.df_all[self.df_all['_category_norm'] == category_norm]
                if activity_id:
                    d = d[d['activity_id'] != activity_id]
                d = d[(d['date'] >= target_ts - pd.Timedelta(days=ISSUE_MAX_HR_WINDOW_DAYS))
                      & (d['date'] <= target_ts)]
                d = d[d['max_hr'].notna()]
                if len(d) >= ISSUE_MAX_HR_P95_MIN_SAMPLES:
                    p95 = float(d['max_hr'].quantile(0.95))
                    if max_hr > p95:
                        hr_parts.append(f'超过近{ISSUE_MAX_HR_WINDOW_DAYS}天同类型 max_hr P95（{p95:.0f} bpm，样本 {len(d)}）')
            if hr_parts:
                issues.append({
                    'title': f'心率异常：最大心率 {max_hr:.0f} bpm 偏高（{"；".join(hr_parts)}）',
                    'evidence': f'本次最大心率 {max_hr:.0f} bpm，{"；".join(hr_parts)}',
                })

        # 5. 技术指标异常（劣于长跨度基线 P80；基线存在才启用）
        # 5.0.2 F3/F4：比赛使用同距离比赛池（<3 场时 _tech_baseline_info 为 None，本探测器不触发）
        baseline_info = getattr(self, '_tech_baseline_info', None)
        if baseline_info and baseline_info.get('df') is not None:
            baseline_df = baseline_info['df']
            is_race_baseline = baseline_info.get('kind') == 'race'
            baseline_desc = (f'{baseline_info["sample_size"]} 场同距离历史比赛'
                             if is_race_baseline
                             else f'长期基线（≥{TECH_BASELINE_MIN_DAYS}天前同类型，样本 {baseline_info["sample_size"]}）')
            tech_specs = [('vertical_ratio', '垂直振幅比', '%'), ('ground_contact_time', '触地时间', 'ms')]
            for col, label, unit in tech_specs:
                curr = _num(row.get(col))
                if curr is None or curr <= 0:
                    continue
                if col not in baseline_df.columns:
                    continue
                s = baseline_df[col].dropna()
                if len(s) < TECH_BASELINE_MIN_SAMPLES:
                    continue
                p80 = float(s.quantile(0.80))
                if curr > p80:
                    issues.append({
                        'title': f'技术指标异常：{label} {curr:.1f}{unit} 劣于技术参照 P80（{p80:.1f}{unit}）',
                        'evidence': f'本次 {label} {curr:.1f}{unit}，{baseline_desc} P80 = {p80:.1f}{unit}',
                    })

        return issues

    def _detect_data_notes(self, row: pd.Series) -> list:
        """5.0.2 F4：数据/配置提示（不是执行问题，不进问题清单）

        当前唯一场景：比赛 max_hr 超过配置上限（PRD 8.2）——
        提示结合连续高强度记录和设备可靠性核验；核验前谨慎解释依赖当前 max_hr 的
        心率区间占比；不给出「提高比赛配速」「增加强度课」等无关修正。
        非比赛课型返回空列表。
        """
        category = row.get('category', '')
        if category not in RACE_CATEGORIES:
            return []
        notes = []
        max_hr = row.get('max_hr')
        config_max = USER_CONFIG.get('max_hr')
        if (max_hr is not None and not pd.isna(max_hr)
                and config_max and float(max_hr) > float(config_max)):
            notes.append({
                'title': f'最大心率 {float(max_hr):.0f} bpm 超过配置上限 {float(config_max):.0f} bpm（数据/配置提示）',
                'evidence': ('当前峰值与配置不一致，需要结合连续高强度记录和设备可靠性核验；'
                             '在核验前，谨慎解释依赖当前 max_hr 的心率区间占比；'
                             '本条为数据提示而非执行问题，不据此给出「提高比赛配速」「增加强度课」等修正。'),
            })
        return notes

    @staticmethod
    def _get_temp_bucket(row_data):
        """获取温区桶（内部辅助方法）"""
        min_temp = row_data.get('min_temperature')
        max_temp = row_data.get('max_temperature')
        if min_temp is None or max_temp is None or pd.isna(min_temp) or pd.isna(max_temp):
            return None
        mid = (float(min_temp) + float(max_temp)) / 2
        if mid < 15:
            return 'cool'
        elif mid <= 25:
            return 'mild'
        else:
            return 'hot'

    def _select_baseline(self, df_window: pd.DataFrame, temp_bucket: Optional[str],
                         freshness_days: Optional[int] = None,
                         category: Optional[str] = None) -> tuple:
        """三级基线选择（PRD F1）：同温区 → 不限温区 → 数据不足

        新鲜度门槛（最新样本距目标日 ≤ freshness_days）仅短期启用；
        长期趋势传 None = 180 天窗口全量、取消新鲜度门槛（PRD F1）。
        豁免温度过滤课型（NO_TEMP_FILTER_CATEGORIES，PRD F1）：跳过同温区 tier，
        直接不限温区池，scope='no_temp'。

        Args:
            df_window: 已按时间窗口/类型筛选的候选样本（未做温区筛选）
            temp_bucket: 目标温区（None 表示目标无温区数据，跳过第一级）
            freshness_days: 新鲜度门槛天数（None 表示不要求新鲜）

        Returns:
            (df_baseline, baseline_scope, insufficient_reason, max_sample)
            采用时 scope 为 'same_temp'/'all_temp'/'no_temp'，reason 为 None；数据不足时返回
            (空 DataFrame, None, '样本不足'/'基线过旧', 各级尝试的最大样本数)。
            '基线过旧' 仅在设了新鲜度门槛且最新样本超期时出现。
        """
        target_ts = pd.Timestamp(self.target_date)
        df_temp = df_window.copy()
        if 'min_temperature' in df_temp.columns and 'max_temperature' in df_temp.columns:
            df_temp['_temp_bucket'] = df_temp.apply(lambda r: self._get_temp_bucket(r), axis=1)
            # 无温区记录不进入基线，避免把缺失温度误判为冷天
            df_temp = df_temp[df_temp['_temp_bucket'].notna()]

        def _fresh(d: pd.DataFrame) -> bool:
            """最新样本距目标日 ≤ freshness_days；None = 无新鲜度要求（长期全量窗口）"""
            if freshness_days is None:
                return True
            return (target_ts - d['date'].max()).days <= freshness_days

        # 记录各级尝试样本数，数据不足时报告最宽口径的实际样本数（占位行显示用）
        max_sample = 0

        # 0. 豁免温度过滤课型：只有一个不限温区池，≥3 次即可使用， freshness 要求不变。
        if category in NO_TEMP_FILTER_CATEGORIES:
            max_sample = max(max_sample, len(df_temp))
            if len(df_temp) >= BASELINE_FALLBACK_MIN_SAMPLES and _fresh(df_temp):
                return df_temp, 'no_temp', None, len(df_temp)
            if len(df_temp) >= BASELINE_FALLBACK_MIN_SAMPLES and freshness_days is not None:
                return pd.DataFrame(), None, '基线过旧', max_sample
            return pd.DataFrame(), None, '样本不足', max_sample

        # 1. 窗口内同温区：≥10 次才直接采用；3-9 次只作为最终兜底，避免小池提前命中。
        fallback = None
        if temp_bucket is not None and '_temp_bucket' in df_temp.columns:
            d_same = df_temp[df_temp['_temp_bucket'] == temp_bucket]
            max_sample = max(max_sample, len(d_same))
            if len(d_same) >= BASELINE_MIN_SAMPLES and _fresh(d_same):
                return d_same, 'same_temp', None, len(d_same)
            if len(d_same) >= BASELINE_FALLBACK_MIN_SAMPLES and _fresh(d_same):
                fallback = (d_same, 'same_temp')

        # 2. 窗口内不限温区：优先 ≥10 次；若全池也只有 3-9 次，保留可用数据。
        max_sample = max(max_sample, len(df_temp))
        if len(df_temp) >= BASELINE_MIN_SAMPLES and _fresh(df_temp):
            return df_temp, 'all_temp', None, len(df_temp)
        if len(df_temp) >= BASELINE_FALLBACK_MIN_SAMPLES and _fresh(df_temp):
            return df_temp, 'all_temp', None, len(df_temp)
        if fallback is not None:
            d_same, scope = fallback
            return d_same, scope, None, len(d_same)

        # 3. 数据不足：区分样本不足(n<3) / 基线过旧(设了新鲜度门槛且最新样本超期)
        if len(df_temp) >= BASELINE_FALLBACK_MIN_SAMPLES and freshness_days is not None:
            return pd.DataFrame(), None, '基线过旧', max_sample
        return pd.DataFrame(), None, '样本不足', max_sample
    
    def _get_long_term_baseline(self, row: pd.Series, category: str, temp_bucket: str, df_all: pd.DataFrame) -> tuple:
        """获取长期基线数据（PRD F1：180 天窗口全量、取消新鲜度门槛，口径与 _calc_long_term 一致）

        Returns:
            (df_baseline, baseline_scope)：数据不足（含基线过旧）时返回 (空 DataFrame, None)，
            调用方 percentile/expected_pace 据此返回 None（模板已有降级显示）
        """
        if self.target_date is None:
            return pd.DataFrame(), None
        target_ts = pd.Timestamp(self.target_date)
        
        # 筛选同类型数据
        df_filtered = df_all[df_all['_category_norm'] == category].copy()
        
        # 排除本次
        activity_id = row.get('activity_id')
        if activity_id:
            df_filtered = df_filtered[df_filtered['activity_id'] != activity_id]
        else:
            df_filtered = df_filtered[df_filtered['date'] != target_ts]
        
        # 时间窗口：前180天全量（PRD F1：取消新鲜度门槛）
        cutoff_ts = target_ts - pd.Timedelta(days=LONG_TERM_WINDOW_DAYS)
        df_filtered = df_filtered[df_filtered['date'] >= cutoff_ts]
        df_filtered = df_filtered[df_filtered['date'] <= target_ts]

        # 三级基线选择（PRD F1 同步）：同温区 → 不限温区 → 数据不足（长期无新鲜度门槛）
        # LSD 等豁免课型直接不限温区池，scope='no_temp'
        df_baseline, baseline_scope, _reason, _max_sample = self._select_baseline(
            df_filtered, temp_bucket, category=category)
        if df_baseline.empty:
            return pd.DataFrame(), None
        
        # 限制样本上限为30次
        if len(df_baseline) > 30:
            df_baseline = df_baseline.sort_values('date', ascending=False).head(30)
        
        return df_baseline, baseline_scope
    
    def _calc_short_term(self, row: pd.Series, category: str, temp_bucket: str, df_all: pd.DataFrame) -> dict:
        """计算短期状态（近60天同类型，优先同温区）"""
        # 获取目标日期
        if self.target_date is None:
            return None
        target_ts = pd.Timestamp(self.target_date)
        
        # 筛选同类型数据
        df_filtered = df_all[df_all['_category_norm'] == category].copy()
        
        # 排除本次
        activity_id = row.get('activity_id')
        if activity_id:
            df_filtered = df_filtered[df_filtered['activity_id'] != activity_id]
        else:
            df_filtered = df_filtered[df_filtered['date'] != target_ts]
        
        # 时间窗口：前60天
        cutoff_ts = target_ts - pd.Timedelta(days=SHORT_TERM_WINDOW_DAYS)
        df_filtered = df_filtered[df_filtered['date'] >= cutoff_ts]
        df_filtered = df_filtered[df_filtered['date'] <= target_ts]
        
        # 三级基线选择（PRD F1）：同温区(≥3次且新鲜) → 不限温区(≥3次且新鲜) → 数据不足
        # LSD 等豁免课型直接不限温区池，scope='no_temp'
        # 窗口和新鲜度门槛均为 60 天（PRD F1）
        df_same_temp, baseline_scope, insufficient_reason, max_sample = self._select_baseline(
            df_filtered, temp_bucket, SHORT_TERM_FRESHNESS_DAYS, category=category)

        # n<3：不形成短期基线结论（数据不足）
        if len(df_same_temp) < SHORT_TERM_DESCRIPTIVE_MIN:
            return {
                'window_days': SHORT_TERM_WINDOW_DAYS,
                'sample_size': max_sample,
                'temp_bucket': temp_bucket,
                'baseline_scope': baseline_scope,
                'message': insufficient_reason or '样本不足',
                'evidence_level': 'insufficient',
                'verdict_allowed': False,
                'evidence_reason': insufficient_reason or '同类型样本不足 3 次',
            }
        
        # 计算中位数（全缺失时为 NaN，统一转为 None，便于判空）
        hr_median = df_same_temp['avg_hr'].dropna().median() if 'avg_hr' in df_same_temp.columns else None
        pace_median = df_same_temp['avg_pace_sec'].dropna().median() if 'avg_pace_sec' in df_same_temp.columns else None
        hr_median = None if hr_median is not None and pd.isna(hr_median) else hr_median
        pace_median = None if pace_median is not None and pd.isna(pace_median) else pace_median
        
        # 计算效率中位数 (m/h)/bpm
        df_eff_valid = df_same_temp[(df_same_temp['avg_pace_sec'] > 0) & (df_same_temp['avg_hr'] > 0)].copy() if 'avg_pace_sec' in df_same_temp.columns and 'avg_hr' in df_same_temp.columns else pd.DataFrame()
        efficiency_median = None
        if not df_eff_valid.empty:
            df_eff_valid['efficiency'] = 3600000.0 / (df_eff_valid['avg_pace_sec'] * df_eff_valid['avg_hr'])
            efficiency_median = df_eff_valid['efficiency'].dropna().median()
            efficiency_median = None if pd.isna(efficiency_median) else efficiency_median
        
        # 各指标有效样本数（第二批复验阻断一：总样本达标不得掩盖单项有效样本不足）
        hr_valid_n = int(df_same_temp['avg_hr'].notna().sum()) if 'avg_hr' in df_same_temp.columns else 0
        pace_valid_n = int(df_same_temp['avg_pace_sec'].notna().sum()) if 'avg_pace_sec' in df_same_temp.columns else 0
        eff_valid_n = int(len(df_eff_valid))

        # 当前值
        curr_hr = row.get('avg_hr', 0)
        curr_pace = row.get('avg_pace_sec', 0)
        curr_hr_valid = curr_hr is not None and not pd.isna(curr_hr) and curr_hr > 0
        curr_pace_valid = curr_pace is not None and not pd.isna(curr_pace) and curr_pace > 0
        curr_eff = 0
        if curr_pace_valid and curr_hr_valid:
            curr_eff = 3600000.0 / (curr_pace * curr_hr)

        # 计算差值（第二批 F1：显式返回，无效值为 None）
        hr_diff = round(curr_hr - hr_median, 1) if (hr_median is not None and curr_hr_valid) else None
        pace_diff = round(curr_pace - pace_median, 1) if (pace_median is not None and curr_pace_valid) else None
        eff_diff = round(curr_eff - efficiency_median, 2) if (efficiency_median is not None and curr_eff) else None

        # 判读逻辑（第二批 F1：n≥5 才允许方向 verdict；3≤n<5 保留数值、verdict=None；
        # 每指标独立处理缺失值：该指标有效样本 <5 或当前值/差值无效时，该指标 verdict 为 None）
        n_samples = len(df_same_temp)

        def _dir_verdict(diff, below_word, above_word, thr, prefer_high):
            """方向 verdict：diff 为 None 时返回 None；prefer_high=True 表示差值越大越优（效率）"""
            if diff is None:
                return None
            if prefer_high:
                return below_word if diff > thr else (above_word if diff < -thr else '持平')
            return below_word if diff < -thr else (above_word if diff > thr else '持平')

        if n_samples >= SHORT_TERM_DIRECTIONAL_MIN:
            # 每项仍须自身有效样本 ≥5 且当前值有效，才允许该项 verdict
            hr_verdict = _dir_verdict(hr_diff, '更轻松', '更累', 3, False) if hr_valid_n >= SHORT_TERM_DIRECTIONAL_MIN else None
            pace_verdict = _dir_verdict(pace_diff, '更快', '更慢', 5, False) if pace_valid_n >= SHORT_TERM_DIRECTIONAL_MIN else None
            eff_verdict = _dir_verdict(eff_diff, '更经济', '更费力', 3, True) if eff_valid_n >= SHORT_TERM_DIRECTIONAL_MIN else None
            evidence_level = 'directional'
            verdict_allowed = True
            if hr_verdict is None or pace_verdict is None or eff_verdict is None:
                evidence_reason = (
                    f'总样本 n={n_samples}；心率有效 {hr_valid_n}、配速有效 {pace_valid_n}、'
                    f'效率有效 {eff_valid_n}；有效样本不足 {SHORT_TERM_DIRECTIONAL_MIN} '
                    f'或当前值缺失的指标仅作描述，不给方向判断')
            else:
                evidence_reason = f'样本充足（n={n_samples}），沿用现有阈值（心率±3bpm、配速±5秒、效率±3）'
        else:
            hr_verdict = pace_verdict = eff_verdict = None
            evidence_level = 'descriptive'
            verdict_allowed = False
            evidence_reason = (f'样本有限（n={n_samples}），仅作描述，不输出方向判断；'
                               f'心率有效 {hr_valid_n}、配速有效 {pace_valid_n}、效率有效 {eff_valid_n}')
        
        temp_bucket_label = 'all' if baseline_scope == 'all_temp' else temp_bucket

        # 当前值与基线值（供模板渲染数据解释；0/NaN 视为数据不足）
        def _clean_num(val):
            if val is None or pd.isna(val) or val == 0:
                return None
            return val

        return {
            'window_days': SHORT_TERM_WINDOW_DAYS,
            'sample_size': n_samples,
            'temp_bucket': temp_bucket_label,
            'baseline_scope': baseline_scope,
            'hr': {'median': hr_median},
            'pace_median': pace_median,
            'efficiency_median': efficiency_median,
            'verdict_hr': hr_verdict,
            'verdict_pace': pace_verdict,
            'verdict_efficiency': eff_verdict,
            'hr_current': _clean_num(curr_hr),
            'hr_baseline': _clean_num(hr_median),
            'pace_current_sec': _clean_num(curr_pace),
            'pace_baseline_sec': _clean_num(pace_median),
            'eff_current': round(curr_eff, 2) if _clean_num(curr_eff) is not None else None,
            'eff_baseline': round(efficiency_median, 2) if _clean_num(efficiency_median) is not None else None,
            # 第二批 F1：显式差值与证据等级（HTML/Prompt 只消费，不各自判门槛）
            'hr_diff': hr_diff,
            'pace_diff': pace_diff,
            'eff_diff': eff_diff,
            'hr_valid_samples': hr_valid_n,
            'pace_valid_samples': pace_valid_n,
            'eff_valid_samples': eff_valid_n,
            'evidence_level': evidence_level,
            'verdict_allowed': verdict_allowed,
            'evidence_reason': evidence_reason,
        }
    
    def _calc_long_term(self, row: pd.Series, category: str, temp_bucket: str, df_all: pd.DataFrame) -> dict:
        """计算长期趋势（近180天同类型同温区线性回归），含去年同期对比"""
        # 获取目标日期
        if self.target_date is None:
            return None
        target_ts = pd.Timestamp(self.target_date)

        # 去年同期等价窗口（对齐月日，向前相同天数），无数据时为 {'message': '数据不足'}
        yoy = self._calc_yoy(row, category, df_all)
        # 夏季同比（PRD F2）：非夏季目标返回 None，去年窗口无数据返回 {'message': '数据不足'}
        summer_yoy = self._calc_summer_yoy(row, df_all)
        
        # 筛选同类型数据
        df_filtered = df_all[df_all['_category_norm'] == category].copy()
        
        # 排除本次
        activity_id = row.get('activity_id')
        if activity_id:
            df_filtered = df_filtered[df_filtered['activity_id'] != activity_id]
        else:
            df_filtered = df_filtered[df_filtered['date'] != target_ts]
        
        # 时间窗口：前180天全量（PRD F1：取消新鲜度门槛，保留月份护栏）
        cutoff_ts = target_ts - pd.Timedelta(days=LONG_TERM_WINDOW_DAYS)
        df_filtered = df_filtered[df_filtered['date'] >= cutoff_ts]
        df_filtered = df_filtered[df_filtered['date'] <= target_ts]

        # 三级基线选择（PRD F1）：同温区(≥3次) → 不限温区(≥3次) → 数据不足（长期无新鲜度门槛）
        # 同温区选中但月度回归护栏不过时（如秋季 mild 桶仅零星样本），降级跨温区基线再试；
        # 护栏数值不变，仅扩大样本池，避免稀疏同温区样本阻塞长期趋势（验收 1）
        insufficient = None
        reg = None
        n_months = 0
        baseline_scope = None
        df_sel = pd.DataFrame()
        for tb in ([temp_bucket, None] if temp_bucket is not None else [None]):
            df_sel, baseline_scope, insufficient_reason, max_sample = self._select_baseline(
                df_filtered, tb, category=category)

            # 不限样本上限：月度回归只用每月中位数，样本多不改变口径；
            # 原 30 次上限会截掉早期月份，与 PRD F1「180 天全量」冲突（验收 1 要求覆盖 4-10 月）

            if len(df_sel) < 3:
                insufficient = {
                    'window_days': LONG_TERM_WINDOW_DAYS,
                    'sample_size': max_sample,
                    'months_available': 0,
                    'months_with_data': 0,
                    'verdict': '数据不足',
                    'verdict_allowed': False,
                    'evidence_level': 'insufficient',
                    'message': insufficient_reason,
                    'yoy': yoy,
                    'is_summer': self._is_summer(row),
                    'summer_yoy': summer_yoy,
                }
                continue

            # 月度分组门槛（PRD F2）：LSD 每月≥1样本纳入回归，其他类型保持≥2；总≥3有效月份不变
            _monthly_min = 1 if category in NO_TEMP_FILTER_CATEGORIES else 2
            reg, n_months = self._long_term_regression(df_sel, min_monthly_samples=_monthly_min)
            if reg is not None:
                break
            insufficient = {
                'window_days': LONG_TERM_WINDOW_DAYS,
                'sample_size': len(df_sel),
                'months_available': 0,
                'months_with_data': n_months,
                'baseline_scope': baseline_scope,
                'verdict': '数据不足',
                'verdict_allowed': False,
                'evidence_level': 'insufficient',
                'message': '样本不足',
                'yoy': yoy,
                'is_summer': self._is_summer(row),
                'summer_yoy': summer_yoy,
            }

        if reg is None:
            return insufficient

        hr_slope = reg['hr_slope']  # bpm/月
        pace_slope = reg['pace_slope']  # 秒/月
        efficiency_slope = reg['efficiency_slope']  # 效率单位/月

        # 夏季宽阈值（PRD F2）：夏季内判定阈值 ×2（心率±1→±2、配速±2→±4、效率±1→±2），
        # 同数据下夏季更不易触发正负信号；非夏季阈值不变
        is_summer = self._is_summer(row)
        _mult = SUMMER_SLOPE_MULT if is_summer else 1.0
        thresholds = {
            'hr': 1.0 * _mult,        # bpm/月
            'pace': 2.0 * _mult,      # 秒/月
            'efficiency': 1.0 * _mult,  # 效率单位/月
        }

        # ---- 第二批 F3：逐月剔除敏感性（对进入回归的月份做 leave-one-month-out）----
        reg_sens, _n = self._monthly_median_regression(
            df_sel, min_monthly_samples=_monthly_min, direction_thresholds=thresholds)
        sensitivity = (reg_sens or {}).get('sensitivity') or {}

        metric_names = {'hr': '心率', 'pace': '配速', 'efficiency': '效率'}
        classes = {m: self._slope_direction(m, reg[f'{m}_slope'], thresholds[m])
                   for m in ('hr', 'pace', 'efficiency')}
        direction_metrics = [m for m in ('hr', 'pace', 'efficiency') if classes[m] != 'stable']
        stable_metrics = [m for m in direction_metrics
                          if (sensitivity.get(m) or {}).get('direction_stable', True)]
        sensitive_metrics = [m for m in direction_metrics if m not in stable_metrics]

        def _signal_reasons(metrics: list) -> tuple:
            """由给定指标的全量斜率生成正负信号文本"""
            neg_signals = []
            pos_signals = []
            for m in metrics:
                slope = reg[f'{m}_slope']
                if m == 'hr':
                    if slope < -thresholds[m]:
                        pos_signals.append(f'心率月降{abs(slope):.1f}bpm')
                    else:
                        neg_signals.append(f'心率月升{slope:.1f}bpm')
                elif m == 'pace':
                    if slope < -thresholds[m]:
                        pos_signals.append(f'配速月升{abs(slope):.1f}秒')
                    else:
                        neg_signals.append(f'配速月降{slope:.1f}秒')
                else:
                    if slope > thresholds[m]:
                        pos_signals.append(f'效率月升{slope:.1f}')
                    else:
                        neg_signals.append(f'效率月降{abs(slope):.1f}')
            return neg_signals, pos_signals

        # ---- 第二批 F2：温度与能力 verdict 分离 ----
        loo_unstable_stable: list = []  # 全量稳定但逐月剔除方向不稳的指标（复验阻断二）
        if baseline_scope in ('all_temp', 'no_temp'):
            # 跨温/未分层池：斜率与月度中位点保留作描述，禁止能力 verdict
            verdict = '能力证据不足'
            verdict_allowed = False
            evidence_level = 'descriptive'
            scope_desc = ('跨温区参照池' if baseline_scope == 'all_temp'
                          else '全部 LSD 同池（未按温区分层）')
            evidence_reason = f'{scope_desc}未排除温度影响，仅描述该参照池中的表现变化'
            reason = evidence_reason
        elif not direction_metrics:
            # 全量阈值内（稳定类）指标同样消费 direction_stable（第二批复验阻断二）：
            # 若某指标全量稳定但逐月剔除后转为方向性变化，不得输出确定的「稳定」
            stable_class = [m for m in ('hr', 'pace', 'efficiency') if classes[m] == 'stable']
            loo_unstable_stable = [m for m in stable_class
                                   if not (sensitivity.get(m) or {}).get('direction_stable', True)]
            if loo_unstable_stable:
                sens_txt = '、'.join(metric_names[m] for m in loo_unstable_stable)
                verdict = '趋势待确认'
                verdict_allowed = False
                evidence_level = 'descriptive'
                reason = f'{sens_txt}全量在阈值内但逐月剔除后方向不稳，稳定结论待确认'
                evidence_reason = reason
            else:
                verdict = '稳定'
                verdict_allowed = True
                evidence_level = 'directional'
                evidence_reason = '各项指标变化在正常范围内，逐月剔除方向分类一致'
                reason = '各项指标变化在正常范围内'
        elif stable_metrics:
            # same_temp：只有全量超阈值且逐月剔除方向一致的指标支撑 verdict
            neg_signals, pos_signals = _signal_reasons(stable_metrics)
            reasons = neg_signals + pos_signals
            if neg_signals and pos_signals:
                verdict = '分化'
            elif pos_signals:
                verdict = '进步'
            else:
                verdict = '退步'
            verdict_allowed = True
            evidence_level = 'directional'
            if sensitive_metrics:
                sens_txt = '、'.join(metric_names[m] for m in sensitive_metrics)
                reason = f"{('，'.join(reasons))}（{sens_txt}对单月敏感，未纳入判断）"
            else:
                reason = '，'.join(reasons)
            evidence_reason = f'同温区基线，{reason}'
        else:
            # 方向指标全部对单月敏感：趋势待确认，不得退化为「稳定」
            sens_txt = '、'.join(metric_names[m] for m in direction_metrics)
            verdict = '趋势待确认'
            verdict_allowed = False
            evidence_level = 'descriptive'
            reason = f'{sens_txt}对单月敏感，趋势待确认'
            evidence_reason = reason

        return {
            'window_days': LONG_TERM_WINDOW_DAYS,
            'sample_size': len(df_sel),
            'months_available': reg['months_in_regression'],
            'months_with_data': reg['months_with_data'],
            'monthly_points': reg['monthly_points'],
            'sensitivity': sensitivity,
            'loo_unstable_stable': loo_unstable_stable,
            'baseline_scope': baseline_scope,
            'is_summer': is_summer,
            'summer_yoy': summer_yoy,
            'trend': {
                'hr_slope_per_month': round(float(hr_slope), 2),
                'pace_slope_per_month': round(float(pace_slope), 2),
                'efficiency_slope_per_month': round(float(efficiency_slope), 2),
            },
            'verdict': verdict,
            'verdict_allowed': verdict_allowed,
            'evidence_level': evidence_level,
            'evidence_reason': evidence_reason,
            'reason': reason,
            'yoy': yoy,
        }
    
    @staticmethod
    def _slope_direction(metric: str, slope: float, threshold: float) -> str:
        """斜率方向分类（第二批 F3：沿用现有阈值与夏季倍率）

        正向 = 训练学意义上的改善方向（心率下降/配速加快/效率上升）。
        """
        if metric == 'hr':
            if slope < -threshold:
                return 'positive'
            if slope > threshold:
                return 'negative'
        elif metric == 'pace':
            if slope < -threshold:
                return 'positive'
            if slope > threshold:
                return 'negative'
        elif metric == 'efficiency':
            if slope > threshold:
                return 'positive'
            if slope < -threshold:
                return 'negative'
        return 'stable'

    def _monthly_median_regression(self, df_baseline: pd.DataFrame,
                                   min_monthly_samples: int = 2,
                                   direction_thresholds: Optional[dict] = None) -> tuple:
        """月度中位数 + 真实月份间隔的未加权线性回归（长期 F1 与同比 F4 共用）

        护栏：总≥3个有效月份；月度点进回归需每月样本数 ≥ min_monthly_samples
        （LSD 等豁免课型为 1，其他类型保持 2）。x 轴用真实月份间隔，不用活动序号。

        Args:
            df_baseline: 已进入基线池的样本
            min_monthly_samples: 每月样本门槛
            direction_thresholds: 敏感性方向分类阈值 {'hr':x,'pace':x,'efficiency':x}；
                传入时额外计算逐月剔除（leave-one-month-out）的斜率范围与方向稳定性；
                None 时（同比）只算斜率不做敏感性。

        Returns:
            (result dict 或 None, months_with_data)
            result 含：hr_slope / pace_slope / efficiency_slope（bpm、秒、效率单位，每月）、
            monthly_points（进入回归的月份：月、月内有效数、心率/配速中位数、效率值）、
            months_in_regression、sensitivity（传入阈值时）。
            护栏不过时返回 (None, 有数据月份数)，调用方据此降级或不给斜率。
        """
        df_b = df_baseline.copy()
        df_b['year_month'] = df_b['date'].dt.to_period('M')
        monthly_stats = df_b.groupby('year_month').agg(
            avg_hr=('avg_hr', 'median'),
            avg_pace_sec=('avg_pace_sec', 'median'),
            count=('avg_pace_sec', 'size'),
        ).reset_index()

        # 过滤掉无效值
        monthly_stats = monthly_stats.dropna(subset=['avg_hr', 'avg_pace_sec'])

        # 回归只纳入每月样本数达标的月份（PRD F2：LSD ≥1/月，其他类型 ≥2/月；样本总数报告不变）
        regress_stats = monthly_stats[monthly_stats['count'] >= min_monthly_samples]

        # 剔除后至少需要3个有效月份
        if len(regress_stats) < LONG_TERM_MIN_MONTHS:
            return None, len(monthly_stats)

        # 准备线性回归数据：x 轴用真实月份间隔
        months_numeric = np.array(
            [(p - regress_stats['year_month'].iloc[0]).n for p in regress_stats['year_month']],
            dtype=float,
        )
        hr_values = regress_stats['avg_hr'].values.astype(float)
        pace_values = regress_stats['avg_pace_sec'].values.astype(float)
        efficiency_values = np.array(
            [3600000.0 / (p * h) if (p > 0 and h > 0) else np.nan
             for p, h in zip(pace_values, hr_values)],
        )

        def _fit(y):
            return float(np.polyfit(months_numeric, y, 1)[0]) if len(y) > 1 else 0.0

        slopes = {
            'hr': _fit(hr_values),
            'pace': _fit(pace_values),
            'efficiency': _fit(efficiency_values),
        }

        # 月度中位点（回放、敏感性与模型事实上下文用）
        monthly_points = [
            {
                'month': str(r['year_month']),
                'count': int(r['count']),
                'hr_median': round(float(r['avg_hr']), 1),
                'pace_median_sec': round(float(r['avg_pace_sec']), 1),
                'efficiency': round(3600000.0 / (float(r['avg_pace_sec']) * float(r['avg_hr'])), 2),
            }
            for _, r in regress_stats.iterrows()
        ]

        result = {
            'hr_slope': slopes['hr'],
            'pace_slope': slopes['pace'],
            'efficiency_slope': slopes['efficiency'],
            'monthly_points': monthly_points,
            'months_in_regression': len(regress_stats),
            'months_with_data': len(monthly_stats),
        }

        # 逐月剔除敏感性（第二批 F3）：不删除原活动，不改变原回归值
        if direction_thresholds is not None:
            n_months = len(regress_stats)
            sensitivity = {}
            for metric, y in (('hr', hr_values), ('pace', pace_values), ('efficiency', efficiency_values)):
                loo_slopes = []
                for i in range(n_months):
                    if n_months - 1 < 2:
                        break  # 剔除后不足 2 个点，无法回归
                    mask = np.arange(n_months) != i
                    loo_slopes.append(float(np.polyfit(months_numeric[mask], y[mask], 1)[0]))
                if loo_slopes:
                    thr = direction_thresholds[metric]
                    full_cls = self._slope_direction(metric, slopes[metric], thr)
                    sensitivity[metric] = {
                        'leave_one_out_min': round(min(loo_slopes), 2),
                        'leave_one_out_max': round(max(loo_slopes), 2),
                        # 方向稳定 = 每次逐月剔除后的方向分类都与全量分类一致
                        'direction_stable': all(
                            self._slope_direction(metric, s, thr) == full_cls for s in loo_slopes),
                    }
                else:
                    sensitivity[metric] = {
                        'leave_one_out_min': None,
                        'leave_one_out_max': None,
                        'direction_stable': True,  # 月份太少无法检验，视为不额外降级
                    }
            result['sensitivity'] = sensitivity

        return result, len(monthly_stats)

    def _long_term_regression(self, df_baseline: pd.DataFrame,
                              min_monthly_samples: int = 2) -> tuple:
        """长期月度回归（PRD F1/F3 护栏），委托 _monthly_median_regression 实现

        Returns:
            (回归结果 dict 或 None, 有数据月份数)。护栏不过时返回 (None, 实际月份数)，
            调用方据此降级下一级（跨温区）基线再试。
        """
        return self._monthly_median_regression(df_baseline, min_monthly_samples=min_monthly_samples)

    def _calc_yoy(self, row: pd.Series, category: str, df_all: pd.DataFrame) -> Optional[dict]:
        """去年同期等价窗口对比：本次日期 -1 年，向前取与长期窗口一致的天数（180 天）

        第二批 F4：心率、配速分别要求 ≥3 个有效样本才展示中位数（不用「总活动≥3」替代）；
        月趋势斜率删除旧的「累计 3 次按日期逐点回归」，改用与长期一致的月度中位数回归
        （普通课型每月≥2、LSD 每月≥1，≥3 个有效月份，真实月份间隔）。
        无数据时返回 {'message': '数据不足'}
        """
        if self.target_date is None:
            return None
        target_ts = pd.Timestamp(self.target_date)
        window_days = 180
        yoy_end = target_ts - pd.DateOffset(years=1)
        yoy_start = yoy_end - pd.Timedelta(days=window_days - 1)

        df_cat = df_all[df_all['_category_norm'] == category].copy()
        activity_id = row.get('activity_id')
        if activity_id:
            df_cat = df_cat[df_cat['activity_id'] != activity_id]
        df_win = df_cat[(df_cat['date'] >= yoy_start) & (df_cat['date'] <= yoy_end)]

        def _clean(val):
            if val is None or pd.isna(val):
                return None
            return val

        # 每指标有效样本门槛：各自 ≥3 个有效值才展示该指标中位数
        hr_valid = df_win['avg_hr'].dropna() if 'avg_hr' in df_win.columns else pd.Series(dtype=float)
        pace_valid = df_win['avg_pace_sec'].dropna() if 'avg_pace_sec' in df_win.columns else pd.Series(dtype=float)
        hr_median = _clean(hr_valid.median()) if len(hr_valid) >= YOY_METRIC_MIN_SAMPLES else None
        pace_median = _clean(pace_valid.median()) if len(pace_valid) >= YOY_METRIC_MIN_SAMPLES else None

        if hr_median is None and pace_median is None:
            return {'message': '数据不足'}

        result = {
            'window_days': window_days,
            'sample_size': len(df_win),
            'hr_valid_samples': len(hr_valid),
            'pace_valid_samples': len(pace_valid),
            'hr_median': round(hr_median, 0) if hr_median is not None else None,
            'pace_median_sec': round(pace_median, 0) if pace_median is not None else None,
            'current_hr': round(row.get('avg_hr', 0), 0),
            'current_pace_sec': row.get('avg_pace_sec', 0),
        }

        # 月斜率：月度中位数回归；≥3 个有效月份才返回，否则字段缺失（None）
        _min_monthly = 1 if category in NO_TEMP_FILTER_CATEGORIES else 2
        reg, _months_with_data = self._monthly_median_regression(df_win, min_monthly_samples=_min_monthly)
        if reg is not None and reg['months_in_regression'] >= YOY_MIN_MONTHS:
            result['hr_slope_per_month'] = round(reg['hr_slope'], 2)
            result['pace_slope_per_month'] = round(reg['pace_slope'], 2)
            result['months_available'] = reg['months_in_regression']

        return result

    def _is_summer(self, row: pd.Series) -> bool:
        """夏季判定（PRD F2）：目标跑步日期在 SUMMER_MONTHS(6-9月) 或 中值气温 > 28°C"""
        if self.target_date is not None and pd.Timestamp(self.target_date).month in SUMMER_MONTHS:
            return True
        min_temp = row.get('min_temperature')
        max_temp = row.get('max_temperature')
        # 温度缺失不判夏季（显式 None 检查，禁止 or 数值 fallback）
        if min_temp is None or max_temp is None or pd.isna(min_temp) or pd.isna(max_temp):
            return False
        return (float(min_temp) + float(max_temp)) / 2 > SUMMER_TEMP_THRESHOLD

    def _calc_summer_yoy(self, row: pd.Series, df_all: pd.DataFrame) -> Optional[dict]:
        """夏季同比（PRD F2）：今年 6-1 至目标日 vs 去年 6-1 至去年同日（对齐月日，同温区优先）

        目标跑步非夏季 → 返回 None；去年窗口无数据 → {'message': '数据不足'}
        （两者模板与 prompt 均不显示，参照现有 yoy 处理）
        """
        if self.target_date is None:
            return None
        if not self._is_summer(row):
            return None
        target_ts = pd.Timestamp(self.target_date)

        # 类型归一化（与 _compare_with_history 口径一致）
        category = row.get('category', '')
        category_norm = 'race' if category in ('full_marathon', 'half_marathon', 'race_event') else category
        if not category_norm or '_category_norm' not in df_all.columns:
            return {'message': '数据不足'}

        activity_id = row.get('activity_id')

        def _pick_window(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
            """同类型窗口样本（排除本次）"""
            d = df_all[(df_all['_category_norm'] == category_norm) &
                       (df_all['date'] >= start) & (df_all['date'] <= end)].copy()
            if activity_id:
                d = d[d['activity_id'] != activity_id]
            else:
                d = d[d['date'] != target_ts]
            return d

        # 今年窗口：当年 6-1 至目标日
        curr_win = _pick_window(pd.Timestamp(target_ts.year, 6, 1), target_ts)
        # 去年窗口：去年 6-1 至去年同日（对齐月日）
        prev_win = _pick_window(pd.Timestamp(target_ts.year - 1, 6, 1),
                                pd.Timestamp(target_ts.year - 1, target_ts.month, target_ts.day))

        # 去年窗口同温区优先：样本 <3 放宽为同类型全温区
        target_bucket = self._get_temp_bucket(row)
        scope = None
        prev_sel = pd.DataFrame()
        if 'min_temperature' in prev_win.columns and 'max_temperature' in prev_win.columns:
            prev_win['_temp_bucket'] = prev_win.apply(lambda r: self._get_temp_bucket(r), axis=1)
            prev_win = prev_win[prev_win['_temp_bucket'].notna()]
            if target_bucket is not None:
                d_same = prev_win[prev_win['_temp_bucket'] == target_bucket]
                if len(d_same) >= 3:
                    prev_sel, scope = d_same, 'same_temp'
        if prev_sel.empty and len(prev_win) >= 3:
            prev_sel, scope = prev_win, 'all_temp'

        def _clean(val):
            if val is None or pd.isna(val):
                return None
            return val

        def _medians(d: pd.DataFrame) -> tuple:
            """心率/配速/效率中位数（效率需配速与心率均有效），无数据为 None"""
            if d.empty:
                return None, None, None
            hr = d['avg_hr'].dropna().median() if 'avg_hr' in d.columns else None
            pace = d['avg_pace_sec'].dropna().median() if 'avg_pace_sec' in d.columns else None
            eff = None
            if 'avg_hr' in d.columns and 'avg_pace_sec' in d.columns:
                dv = d[(d['avg_pace_sec'] > 0) & (d['avg_hr'] > 0)]
                if not dv.empty:
                    eff = (3600000.0 / (dv['avg_pace_sec'] * dv['avg_hr'])).median()
            return _clean(hr), _clean(pace), _clean(eff)

        curr_hr, curr_pace, curr_eff = _medians(curr_win)
        prev_hr, prev_pace, prev_eff = _medians(prev_sel)

        # 去年窗口无数据 → 数据不足（模板与 prompt 均不显示）
        if prev_hr is None and prev_pace is None:
            return {'message': '数据不足'}

        return {
            'curr_sample_size': len(curr_win),
            'prev_sample_size': len(prev_sel),
            'temp_scope': scope,
            'curr_hr_median': round(curr_hr, 0) if curr_hr is not None else None,
            'prev_hr_median': round(prev_hr, 0) if prev_hr is not None else None,
            'curr_pace_median_sec': round(curr_pace, 0) if curr_pace is not None else None,
            'prev_pace_median_sec': round(prev_pace, 0) if prev_pace is not None else None,
            'curr_eff_median': round(curr_eff, 2) if curr_eff is not None else None,
            'prev_eff_median': round(prev_eff, 2) if prev_eff is not None else None,
        }

    def _calc_percentile(self, row: pd.Series, df_baseline: pd.DataFrame) -> dict:
        """计算百分位排名（第二批 F5：按实际参与排名的有效效率值判断，n≥10 才排名）

        门槛只看有效效率值数量：dataframe 行数≥10 但有效效率不足 10 个时同样返回 None。
        百分位公式、30 次上限（基线选择侧）和基线池选择不变。
        """
        if df_baseline is None or len(df_baseline) < 1:
            return None

        # 计算当前效率
        curr_hr = row.get('avg_hr', 0)
        curr_pace = row.get('avg_pace_sec', 0)
        curr_eff = 0
        if curr_pace > 0 and curr_hr > 0:
            curr_eff = 3600000.0 / (curr_pace * curr_hr)

        # 计算历史效率
        df_valid = df_baseline[(df_baseline['avg_pace_sec'] > 0) & (df_baseline['avg_hr'] > 0)].copy()
        if df_valid.empty:
            return None

        df_valid['efficiency'] = 3600000.0 / (df_valid['avg_pace_sec'] * df_valid['avg_hr'])
        history_effs = df_valid['efficiency'].dropna().tolist()

        if len(history_effs) < PERCENTILE_MIN_VALID:
            return None
        
        # 计算百分位：效率越高越好。
        # better_count 为历史效率中严格优于当前值（比当前更高）的次数。
        # 用 (1 - better_count / n) * 100 表示当前超过多少比例的历史记录。
        better_count = sum(1 for e in history_effs if e > curr_eff)
        percentile_value = round((1 - better_count / len(history_effs)) * 100, 0)
        
        # 标签与实际百分位值保持一致
        if percentile_value >= 90:
            rank_label = f'P{int(percentile_value)} 优秀'
            rank_emoji = '🟢'
        elif percentile_value >= 75:
            rank_label = f'P{int(percentile_value)} 良好'
            rank_emoji = '🟢'
        elif percentile_value >= 50:
            rank_label = f'P{int(percentile_value)} 正常'
            rank_emoji = '🟡'
        elif percentile_value >= 25:
            rank_label = f'P{int(percentile_value)} 偏低'
            rank_emoji = '🟠'
        else:
            rank_label = f'P{int(percentile_value)} 以下'
            rank_emoji = '🔴'
        
        return {
            'metric': 'efficiency',
            'value': round(percentile_value, 1),
            'rank_label': rank_label,
            'sample_size': len(history_effs),
        }
    
    def _calc_expected_pace(self, row: pd.Series, df_baseline: pd.DataFrame) -> dict:
        """计算预期配速偏差"""
        if len(df_baseline) < 3:
            return None
        
        # 计算历史配速中位数作为预期
        pace_series = df_baseline['avg_pace_sec'].dropna()
        if len(pace_series) < 3:
            return None
        
        expected_pace = pace_series.median()
        actual_pace = row.get('avg_pace_sec', 0)
        diff = actual_pace - expected_pace
        
        return {
            'expected_pace_sec': round(expected_pace, 1),
            'actual_pace_sec': round(actual_pace, 1),
            'diff_sec': round(diff, 1),
            'sample_size': len(pace_series),
        
    }
    
    def _calc_pa_hr_scoped(self, row: pd.Series) -> tuple:
        """按课型统一选段计算 Pa:Hr（5.0 第一批 F2）

        Returns:
            (pa_hr_dict | None, context)：context 结构
            {'scope': 'full_activity' | 'manual_segment' | 'not_applicable',
             'segment_laps': [start, end] | None,
             'reason': None | 'missing_manual_segment' | 'interval_not_applicable' | 'insufficient_lap_data'}
            计算成功的 pa_hr_dict 带 scope / segment_laps 段落说明；
            人工课型选段失败时返回 (None, not_applicable)，绝不回退整场。
        """
        category = row.get('category', '') or ''
        laps = self.raw_laps or []
        sel = select_pa_hr_scope(category, laps, row.get('pa_hr_lap_start'), row.get('pa_hr_lap_end'))
        if sel['scope'] == 'not_applicable':
            return None, sel
        pa = self._calc_pa_hr(sel['laps']) if laps else None
        if pa is None:
            if sel['scope'] == 'manual_segment':
                return None, {'scope': 'not_applicable', 'segment_laps': sel['segment_laps'],
                              'reason': 'insufficient_lap_data'}
            return None, {'scope': 'full_activity', 'segment_laps': None,
                          'reason': 'insufficient_lap_data' if laps else None}
        pa['scope'] = sel['scope']
        pa['segment_laps'] = sel['segment_laps']
        return pa, {'scope': sel['scope'], 'segment_laps': sel['segment_laps'], 'reason': None}

    def _calc_pa_hr(self, laps: List[dict]) -> Optional[dict]:
        """
        计算 Pa:Hr 有氧解耦指标
        
        Args:
            laps: 分圈数据列表，每个 dict 包含:
                - distance: 圈距离（米）
                - duration: 圈时长（秒）
                - avg_hr: 平均心率（bpm，可能为 None/NaN）
        
        Returns:
            dict 或 None（lap 数据不足或总距离 <3km）
        """
        # 过滤有效圈数据（兼容不同字段名：distance/distance_m, duration/duration_sec）
        valid_laps = []
        for lap in laps:
            dist = lap.get('distance', lap.get('distance_m', 0))
            dur = lap.get('duration', lap.get('duration_sec', 0))
            hr = lap.get('avg_hr')
            if dist > 0 and dur > 0 and hr is not None and not pd.isna(hr) and hr > 0:
                valid_laps.append({
                    'distance': dist,
                    'duration': dur,
                    'avg_hr': hr
                })
        
        # 计算总距离
        total_distance = sum(lap['distance'] for lap in valid_laps)
        
        # 距离不足3km则跳过
        if total_distance < 3000:
            return None
        
        # 按距离中点拆分前后半程
        half_dist = total_distance / 2
        
        first_half_laps = []
        second_half_laps = []
        
        cumulative_dist = 0
        for lap in valid_laps:
            lap_start = cumulative_dist
            lap_end = cumulative_dist + lap['distance']
            
            if lap_end <= half_dist:
                # 完全在前半程
                first_half_laps.append(lap)
            elif lap_start >= half_dist:
                # 完全在后半程
                second_half_laps.append(lap)
            else:
                # 跨越中点，按比例拆分
                first_part_dist = half_dist - lap_start
                second_part_dist = lap_end - half_dist
                
                # 按距离比例分配时长（心率不变）
                total_lap_dist = lap['distance']
                first_part_dur = lap['duration'] * (first_part_dist / total_lap_dist)
                second_part_dur = lap['duration'] * (second_part_dist / total_lap_dist)
                
                first_half_laps.append({
                    'distance': first_part_dist,
                    'duration': first_part_dur,
                    'avg_hr': lap['avg_hr']
                })
                
                second_half_laps.append({
                    'distance': second_part_dist,
                    'duration': second_part_dur,
                    'avg_hr': lap['avg_hr']
                })
            
            cumulative_dist = lap_end
        
        # 计算前后半程的速度和心率
        def calculate_metrics(half_laps):
            if not half_laps:
                return 0, 0
            
            total_dist = sum(lap['distance'] for lap in half_laps)
            total_dur = sum(lap['duration'] for lap in half_laps)
            
            if total_dur <= 0:
                return 0, 0
            
            speed = total_dist / total_dur if total_dur > 0 else 0
            
            # 按时长加权平均心率
            weighted_hr_sum = sum(lap['avg_hr'] * lap['duration'] for lap in half_laps)
            weighted_hr = weighted_hr_sum / total_dur if total_dur > 0 else 0
            
            return speed, weighted_hr
        
        first_speed, first_hr = calculate_metrics(first_half_laps)
        second_speed, second_hr = calculate_metrics(second_half_laps)
        
        if first_hr <= 0 or second_hr <= 0:
            return None
        
        # 计算效率比
        ratio1 = first_speed / first_hr if first_hr > 0 else 0
        ratio2 = second_speed / second_hr if second_hr > 0 else 0
        
        # 计算 Pa:Hr 百分比
        if ratio1 != 0:
            pa_hr_pct = (ratio2 - ratio1) / ratio1 * 100
        else:
            pa_hr_pct = 0
        
        # 判断解读标准
        pa_hr_abs = abs(pa_hr_pct)
        if pa_hr_abs < 3:
            verdict = '很稳定'
            verdict_class = 'excellent'
            verdict_emoji = '🟢'
        elif 3 <= pa_hr_abs < 5:
            verdict = '正常'
            verdict_class = 'good'
            verdict_emoji = '🟡'
        elif 5 <= pa_hr_abs < 8:
            verdict = '有明显漂移'
            verdict_class = 'warning'
            verdict_emoji = '🟠'
        else:
            verdict = '热疲劳/耐力不足'
            verdict_class = 'poor'
            verdict_emoji = '🔴'
        
        return {
            'pa_hr_pct': pa_hr_pct,
            'pa_hr_abs': pa_hr_abs,
            'verdict': verdict,
            'verdict_class': verdict_class,
            'verdict_emoji': verdict_emoji,
            'first_half_speed': first_speed,
            'first_half_hr': first_hr,
            'second_half_speed': second_speed,
            'second_half_hr': second_hr,
            'first_half_pace': first_speed > 0 and (1000 / first_speed) or 0,  # 秒/km（配速）
            'second_half_pace': second_speed > 0 and (1000 / second_speed) or 0,  # 秒/km（配速）
            'total_distance': total_distance / 1000,  # km
        }


class LLMReportGenerator:
    """LLM 教练点评 Prompt 构建器（KimiWork 迁移版）。

    本类不再调用任何外部模型 API：仅负责构建确定性 Prompt（_build_prompt）、
    解析 <<<BRIEF>>> 简报块（_parse_brief）。实际文字由 KimiWork 会话生成，
    经 main.py 两阶段编排（--prepare-llm → --llm-response）写入缓存并渲染。
    """

    def __init__(self, df_all: pd.DataFrame = None):
        self.df_all = df_all

    @staticmethod
    def _parse_brief(content: str) -> tuple:
        """从 LLM 输出解析 <<<BRIEF>>> 简报分隔块

        Returns:
            (报告正文, 简报)；未按格式输出时降级为 (全文, "")
        """
        import re
        m = re.search(r'<<<BRIEF>>>(.*?)<<<END>>>', content, re.DOTALL)
        if not m:
            return content, ""
        brief = m.group(1).strip()
        report = (content[:m.start()] + content[m.end():]).strip()
        return report, brief
    
    def _build_prompt(self, data: dict, user_note: str = None) -> str:
        """构建 LLM Prompt"""
        raw = data.get('raw_data', {})
        summary = data.get('summary', {})
        intensity = data.get('intensity', {})
        efficiency = data.get('efficiency', {})
        comparison = data.get('comparison', {})
        # C3：原始信号清单（findings，指标/差值/方向），仅作 LLM 参考，禁止照抄
        findings = data.get('findings', [])
        if findings:
            signal_lines = chr(10).join(
                f"- {f['metric']}: {f['diff']:+.1f}{f['unit']}（{f['direction']}）" for f in findings
            )
        else:
            signal_lines = '无'
        laps = data.get('laps', {})
        pa_hr = data.get('pa_hr', {})

        # 构建分圈数据段落
        lap_section = self._format_lap_data(laps)

        # 构建气温影响参考
        temp_impact_section = self._build_temp_impact_reference(raw, pa_hr)

        # Pa:Hr 不适用原因（5.0 第一批 F2）：节奏跑/间歇跑未计算时显式说明，禁止自行估算整场值
        pa_ctx = data.get('pa_hr_context') or {}
        if pa_ctx.get('scope') == 'not_applicable' and pa_ctx.get('reason'):
            _reason_text = {
                'missing_manual_segment': '节奏跑缺少人工指定工作段，本次不计算 Pa:Hr',
                'interval_not_applicable': '间歇跑为工作/恢复交替结构，默认不计算整场 Pa:Hr',
                'insufficient_lap_data': '人工工作段有效数据不足（需 ≥3 km 且有心率），本次不计算 Pa:Hr',
            }.get(pa_ctx['reason'], str(pa_ctx['reason']))
            pa_note_section = f"\n## Pa:Hr 有氧解耦\n【说明】{_reason_text}。不得在点评中自行估算整场 Pa:Hr 数值。\n"
        else:
            pa_note_section = ''

        # 构建跑者自述段落（如有）
        runner_note_section = ''
        if user_note:
            import html as _html
            safe_note = _html.escape(user_note)
            truncated = safe_note if len(safe_note) <= 800 else safe_note[:800] + '\u2026'
            runner_note_section = f"## 🏃 跑者自述（体感反馈）\n> {truncated}\n\n"

        # C1：技术段（5.0.2 F3：比赛异常驱动；5.0.2 验收修正：异常只来自 data['issues'] 的
        # 「技术指标异常」，普通 change 不作异常、不逐项解释；普通课型逻辑不变）
        tech_changes = comparison.get('tech_changes', [])
        is_race_prompt = raw.get('category') in RACE_CATEGORIES
        issues = data.get('issues', [])
        flat_specs = [
            ('步频', f"{raw.get('cadence', 0)} spm"),
            ('步幅', f"{raw.get('stride_length_cm', 0):.1f} cm"),
            ('垂直振幅比', f"{raw.get('vertical_ratio_pct', 0):.1f}%"),
            ('触地时间', f"{raw.get('ground_contact_ms', 0):.1f} ms"),
        ]
        if isinstance(tech_changes, dict) and tech_changes.get('kind') == 'race':
            # 比赛技术参照：同距离全部历史比赛，无功率/配速硬筛选；异常驱动
            tech_lines = [f"【比赛技术参照】同距离历史比赛 {tech_changes['sample_size']} 场"
                          f"（不混其他距离赛事，无功率/配速硬筛选）"]
            if tech_changes.get('status') == 'insufficient_baseline':
                tech_lines.append('本次缺少可比技术基线（同距离历史比赛不足 3 场），不作技术评价。')
                tech_instruction = ('技术效率分析：本段只输出一句「缺少可比技术基线，不作技术评价」，'
                                    '不得写「长期稳定」、不得逐项罗列指标、不得给练习建议')
            else:
                tech_anomalies = [i for i in issues if '技术指标异常' in i['title']]
                if tech_anomalies:
                    tech_lines.append('【技术异常】本场检测到需要修正的技术异常（确定性证据）：')
                    for it in tech_anomalies:
                        tech_lines.append(f"- {it['title']}（{it['evidence']}）")
                    tech_instruction = ('技术效率分析：仅针对上方【技术异常】逐条说明——异常是什么、'
                                        '对本次比赛执行的影响、对应的修正；'
                                        '禁止把普通技术变化当异常，禁止称「改善」，禁止无异常硬凑练习建议')
                else:
                    tech_lines.append('本场未发现需要单独修正的技术问题。')
                    tech_instruction = ('技术效率分析：本段只输出一句「本场未发现需要单独修正的技术问题。」'
                                        '，不得展示或逐项解释 VR、GCT、步幅、步频，不得给练习建议')
        elif tech_changes:
            tech_lines = ['【改善项】（对比 3 个月前同类型相近功率基线）']
            improved = set()
            for c in tech_changes:
                diff_str = f"{c['diff']:+.2f}".rstrip('0').rstrip('.')
                tech_lines.append(
                    f"- {c['metric']}：当前 {c['current']}{c['unit']} vs 基线 {c['baseline']}{c['unit']}（{diff_str}{c['unit']}，改善）"
                )
                improved.add(c['metric'])
            flat_items = [f'{label} {value}' for label, value in flat_specs if label not in improved]
            if flat_items:
                tech_lines.append('【持平项】' + '、'.join(flat_items) + ' —— 与长期基线持平')
            tech_instruction = ('技术效率分析：只对【改善项】逐项点评其训练学意义（每项 1-2 句）；'
                                '【持平项】已在数据段标注持平，一律不得展开、不得评价优劣、'
                                '不得给练习建议、不得引用其他段落的历史中位数；本节总长 ≤150 字')
        else:
            # 5.0.2 F3：无合格基线不得写「长期稳定」
            if comparison.get('tech_status') == 'insufficient_baseline':
                tech_lines = ['缺少可比技术基线（同类型 90 天前样本不足 3 次），不作技术评价']
                tech_instruction = ('技术效率分析：本段只输出一句「缺少可比技术基线，不作技术评价」，'
                                    '不得写「长期稳定」、不得逐项罗列指标、不得给练习建议')
            else:
                tech_lines = ['技术指标与长期基线持平，无显著变化']
                tech_instruction = ('技术效率分析：技术指标长期稳定，本节用一句话确认即可，不要逐项罗列指标数值')
        tech_section = '\n'.join(tech_lines)

        # C2：确定性问题清单（PRD F2）；为空则明确写「问题清单：无」
        if issues:
            issue_lines = ['检测到的问题清单：']
            for it in issues:
                issue_lines.append(f"- {it['title']}（{it['evidence']}）")
            issues_section = '\n'.join(issue_lines)
        else:
            issues_section = '检测到的问题清单：无'

        # 5.0.2 F5：结构化比赛计划与赛段执行证据（无计划则为空串，禁止计划偏离判断）
        race_plan_ev = data.get('race_plan')
        race_plan_section = self._format_race_plan(race_plan_ev) if race_plan_ev else ''

        # 5.0.2 验收修正：动态分圈指令——有结构化计划的比赛按计划赛段逐一分析并覆盖检查点，
        # 普通课型与无计划比赛保持原有前/中/后程指令（指令文本原样保留，不扩大修改）
        plan_segments = (race_plan_ev or {}).get('segments') or []
        if is_race_prompt and plan_segments:
            seg_names = ' / '.join(f"{s['start_km']:g}-{s['end_km']:g} km" for s in plan_segments)
            lap_instruction = (
                f'分圈表现分析：严格按上方「比赛计划与赛段执行」的计划赛段（{seg_names}）'
                '逐一拆解各赛段配速与心率，并结合检查点表现；'
                '不得另建前/中/后程或脱离计划分段；'
                '段内用无序列表，每项 `- **X-Y km**：描述`；'
                '只有证据存在时才可使用"热身不足""后程过猛""心率漂移"等标签，无证据不得硬指')
        else:
            lap_instruction = ('分圈表现分析：按前/中/后程拆解配速与心率变化，还原训练现场；'
                               '如有证据可指出"热身不足""后程过猛""心率漂移"等现象，'
                               '无证据不得硬指这些标签；段内用无序列表，'
                               '每项 `- **前段（X-Y km）**：描述`，中段/后段同格式，不得写成连续长段')

        # 5.0.2 F4：数据/配置提示（非执行问题）
        data_notes = data.get('data_notes') or []
        if data_notes:
            dn_lines = ['## 数据/配置提示（非执行问题，不进入问题清单）']
            for note in data_notes:
                dn_lines.append(f"- {note['title']}：{note['evidence']}")
            data_notes_section = '\n'.join(dn_lines) + '\n'
        else:
            data_notes_section = ''

        # 5.0.2 F4/F6：比赛 Pa:Hr 保留数值但不自动视为问题，禁止与同源分圈互证
        if is_race_prompt and pa_hr:
            pa_race_note = ('\n【比赛 Pa:Hr 说明】本场为比赛，Pa:Hr 数值仅保留参考、不自动视为执行问题；'
                            'Pa:Hr 与同源分圈心率/配速不得称为「相互印证」。\n')
        else:
            pa_race_note = ''

        # 5.0.2 F6：比赛点评专属要求
        if is_race_prompt:
            race_instruction = """
## 比赛点评专属要求（本节要求优先于通用要求）
- 优先回答：目标是否实现、成绩相对同距离历史比赛处于什么位置、执行哪里好/哪里偏离、外部条件（起跑人群、赛道、坡道、气温、湿度）怎样影响、下一步真正需要改什么。
- 有计划时严格按计划赛段与检查点分析执行，不得任意创造与计划无关的前/中/后段，不得只摘取个别公里。
- 只有证据存在时才可使用「热身不足」「后程过猛」「心率漂移」等标签，禁止为凑结构而硬指出这些现象。
- 禁止把比赛末段高心率自动等同「后程失控」；不得写「后程持续提速」这类无证据描述。
- 技术指标无异常时不硬分析、不给练习建议。
- 计划偏离只能依据上方「比赛计划与赛段执行」的确定性偏差判定；无计划配置时禁止判断计划偏离。
- 「问题与修正」清单为空时不凑建议；赛后恢复与下一阶段目标（如自述提到的间歇/节奏安排）可在小结或趋势中回应，但不得伪装成执行问题，禁止机械开课表。
"""
        else:
            race_instruction = ''

        prompt = f"""你是一位专业的跑步教练和运动科学家。请基于跑者自述（如有，见上方「跑者自述」段落），以及以下数据，生成一份专业的跑步分析报告。

{runner_note_section}## 跑步基本信息
- 日期：{raw.get('date', '')}
- 类型：{raw.get('category_name', '')}
- 距离：{int(raw.get('distance_km', 0))} km
- 用时：{raw.get('duration_min', 0):.0f} 分钟
- 平均配速：{raw.get('avg_pace', '')} /km

## 心率分析
- 平均心率：{raw.get('avg_hr', 0)} bpm，最大心率：{raw.get('max_hr', 0)} bpm
- 心率区间分布：
{chr(10).join(f'  {k}: {v:.1f}%' for k, v in summary.get('zone_pct', {}).items())}

## 功率分析
- 平均功率：{raw.get('avg_power', 0)}W，最大功率：{raw.get('max_power', 0)}W，标准化功率：{raw.get('norm_power', 0)}W
- 有氧训练效果：{raw.get('aerobic_te', 0)}，无氧训练效果：{raw.get('anaerobic_te', 0)}

## 技术分析
{tech_section}

## 历史对比
{self._format_comparison(comparison)}
{lap_section}
{race_plan_section}{temp_impact_section}{pa_note_section}{pa_race_note}{data_notes_section}
## 原始信号
{signal_lines}

## 检测到的问题
{issues_section}
{race_instruction}
请生成包含以下 6 个小节的分析文字（小节标题格式 `## emoji 标题`，## 后一个空格、emoji 后一个空格，无其他连接符，标题文本与清单完全一致）：
## 🔥 本次跑步小结 / ## 🏃 强度与负荷分析 / ## ⚙️ 技术效率分析 / ## 📈 能力变化趋势 / ## 🔄 分圈表现分析 / ## 🛠️ 问题与修正

1. 本次跑步小结：2-3 句通俗有温度的小结
2. 强度与负荷分析：心率、功率、训练效果综合评价
3. {tech_instruction}
4. 能力变化趋势：按三个层次组织，每层独立成段——
   ① 短期（近 60 天基线）：本次与近期同类型中位数对比，反映最近状态；
   ② 长期（180 天月度回归）：多月中位数轨迹与斜率，反映训练积累方向；
   ③ 夏季同期对比（仅当数据段提供时）：与去年同期同窗口对比，说明消除了季节温差后的真实变化；若数据段未提供该层数据，则整层直接省略，不得写任何说明或占位文字。
   ①② 某层数据不足时一句话带过即可，不要硬凑；三层顺序固定，不合并。
5. {lap_instruction}
6. 问题与修正：严格依据上方「检测到的问题」清单（每项含数据证据），逐条按「问题 → 对训练效果的影响 → 具体怎么改」输出；建议必须可操作、与问题一一对应，禁止凑数、禁止输出与清单无关的通用建议；连续编号列表，格式 `1. **问题标题**：影响……；改进：……`；若清单为「无」且跑者自述中无明确计划/目标表述，本节只输出固定一句话「本次训练执行无明显问题，无需调整。」，不得输出任何其他内容（禁止通用建议、展望、鼓励）；计划偏离判定：仅当跑者自述包含明确计划/目标（如「原计划马配渐加速」）时，对照执行数据判断是否偏离，偏离则作为一条问题并入本节
7. 报告最后一行输出 `<<<BRIEF>>>100字以内的简要总结（突出训练重点和特点，语言专业简洁，80-120字）<<<END>>>` 包裹的简报
8. 以下为原始信号清单，仅将有训练学意义的信号融入相关小节点评，无意义的直接忽略，禁止照抄清单条目

要求：语言专业严谨务实；Markdown 规整，次级小标题（分圈阶段、建议优先级、技术目标）必须 `**加粗**`；避免堆砌数字，重点解读趋势；建议具体可执行并给量化目标；避免绝对化表述（如"无功率漂移"），改用"未出现明显迹象""暂未观察到"；总字数 ≤1500；不要输出报告标题、类型、日期、配速等 header，直接从正文小结开始写
"""

        return prompt
    def _format_race_plan(self, race_ev: dict) -> str:
        """5.0.2 F5：结构化比赛计划与赛段执行证据的 Prompt 段落

        同时提供原始计划与天气调整后计划；湿度缺失明确未参与判断；
        计划内容只来自确定性内核，模型不得凭记忆补充或修改。
        """
        plan = race_ev.get('plan', {})
        weather = race_ev.get('weather', {})
        lines = ['## 比赛计划与赛段执行（结构化计划，禁止凭记忆补充或修改）']
        lines.append(f"- 比赛：{plan.get('name', '')}，目标 {plan.get('target', '')}")
        lines.append(f"- 策略：{plan.get('strategy', '')}")
        lines.append(f"- 天气规则：{plan.get('weather_rule', '')}")

        temp_mid = weather.get('temp_mid_c')
        temp_txt = f"{temp_mid:.1f}" if temp_mid is not None else '未知'
        thr = plan.get('heat_threshold_c')
        if weather.get('heat_triggered'):
            pen = weather.get('adjusted_pace_penalty_sec') or [None, None]
            lines.append(
                f"- 天气判定：中值气温 {temp_txt}°C > 阈值 {thr:.0f}°C，触发热调整——"
                f"整体配速放宽 +{pen[0]}-{pen[1]} 秒/km，调整后目标 {weather.get('adjusted_target')}")
        else:
            lines.append(f"- 天气判定：中值气温 {temp_txt}°C（阈值 {thr:.0f}°C），未触发热调整")
        if weather.get('humidity_participated'):
            lines.append(f"- 湿度 {weather.get('humidity_pct'):.0f}% 参与天气判断")
        else:
            lines.append('- 湿度数据缺失，未参与天气判断（不得由模型自行估算）')

        lines.append('- 赛段执行（配速=赛段总时长/总距离；心率、功率按分圈时长加权；爬升=分圈求和）：')
        for seg in race_ev.get('segments', []):
            pace = seg.get('actual_pace_sec')
            pace_txt = self._format_pace(pace) if pace is not None else '无数值'
            dev_map = {'in_range': '区间内', 'faster': '快于区间', 'slower': '慢于区间'}
            dev_txt = dev_map.get(seg.get('deviation'), '未知')
            adj_txt = ''
            if seg.get('adjusted_pace_min_sec') is not None:
                adj_txt = (f"；调整后区间 {self._format_pace(seg['adjusted_pace_min_sec'])}-"
                           f"{self._format_pace(seg['adjusted_pace_max_sec'])}"
                           f"（{dev_map.get(seg.get('adjusted_deviation'), '未知')}）")
            note_txt = f"；要点：{seg['note']}" if seg.get('note') else ''
            lines.append(
                f"  - {seg['start_km']:g}-{seg['end_km']:g} km：实际 {pace_txt}"
                f"（计划 {self._format_pace(seg['planned_pace_min_sec'])}-"
                f"{self._format_pace(seg['planned_pace_max_sec'])}，{dev_txt}{adj_txt}），"
                f"加权心率 {seg.get('avg_hr_weighted')} bpm，加权功率 {seg.get('avg_power_weighted')} W，"
                f"爬升 {seg.get('elevation_gain_m')} m{note_txt}")

        lines.append('- 检查点：')
        for cp in race_ev.get('checkpoints', []):
            elapsed = cp.get('actual_elapsed_sec')
            elapsed_txt = self._format_elapsed(elapsed) if elapsed is not None else '无数值'
            cp_dev = cp.get('deviation')
            action = cp.get('action', '')
            # 5.0.2 验收修正：区分预案是否触发，未知状态不得推断已触发
            if cp_dev == 'beyond_upper':
                cp_status = f'超窗口上限；已触发超限预案：{action}'
            elif cp_dev == 'within_window':
                cp_status = f'窗口内；超限预案：{action}（本场未触发）'
            elif cp_dev == 'ahead_of_anchor':
                cp_status = f'快于锚点；超限预案：{action}（本场未触发）'
            else:
                cp_status = '偏差状态未知；不得推断预案已触发'
            lines.append(
                f"  - {cp['distance_km']:g} km：实际 {elapsed_txt}"
                f"（锚点 {self._format_elapsed(cp['anchor_sec'])} / 上限 {self._format_elapsed(cp['upper_sec'])}，"
                f"{cp_status}）")
        lines.append('')
        return '\n'.join(lines)

    @staticmethod
    def _format_elapsed(sec) -> str:
        """秒 → H:MM:SS"""
        sec = int(round(float(sec)))
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}"

    def _format_comparison(self, comp: dict) -> str:
        if not comp:
            return '（无足够历史数据对比）'
        parts = []
        # 5.0.2 F1：同距离历史比赛成绩参照池（成绩/执行比较允许，纯能力结论禁止）
        if comp.get('comparison_kind') == 'same_distance_race_history':
            n = comp.get('sample_size', 0)
            if n < 1:
                parts.append(
                    f"【同距离历史比赛·成绩参照】{comp.get('message') or '无同距离历史比赛记录'}——"
                    f"无法形成成绩参照比较，禁止输出任何同距离成绩/能力方向判断。")
                self._append_status_trends(comp, parts)
                return '\n'.join(parts)
            race_name = '半程马拉松' if (comp.get('pool_category') == 'half_marathon') else '全程马拉松'
            parts.append(
                f"【同距离历史比赛·成绩参照】参照池为全部 {n} 场历史{race_name}"
                f"（跨全年、不限温区/赛道/爬升/比赛目标；条件差异只用于解释差异，不用于排除样本）。"
                f"允许成绩/执行比较（更快/更慢、更稳/波动更大等结果级描述），"
                f"禁止仅凭该池输出「纯能力上升/下降」结论，禁止把成绩差全部归因于体能，"
                f"禁止用本场成绩替代不存在的短期/长期回归证据。")
            for act in (comp.get('pool_activities') or []):
                fields = []
                if act.get('duration_min') is not None:
                    fields.append(f"用时 {act['duration_min']:.0f} 分钟")
                if act.get('avg_pace_sec') is not None:
                    fields.append(f"配速 {self._format_pace(act['avg_pace_sec'])}")
                if act.get('avg_hr') is not None:
                    fields.append(f"心率 {act['avg_hr']:.0f} bpm")
                if act.get('avg_power') is not None:
                    fields.append(f"功率 {act['avg_power']:.0f}W")
                if act.get('efficiency') is not None:
                    fields.append(f"效率 {act['efficiency']:.2f}")
                temp_txt = ''
                if act.get('min_temperature') is not None and act.get('max_temperature') is not None:
                    temp_txt = f"，气温 {act['min_temperature']:.0f}-{act['max_temperature']:.0f}°C"
                elev_txt = f"，爬升 {act['elevation_gain']:.0f} m" if act.get('elevation_gain') is not None else ''
                title_txt = f"《{act['title']}》" if act.get('title') else ''
                parts.append(f"- {act.get('date', '未知日期')} {title_txt}：{'、'.join(fields) if fields else '数据未知'}"
                             f"{temp_txt}{elev_txt}")
            ability = comp.get('ability', {})
            # 5.0.2 验收修正：_format_pace 已含 /KM，配速不再拼接额外 /km 单位
            for key, label, unit, fmt in (
                    ('hr_trend', '心率', 'bpm', lambda v: f"{v:.0f}"),
                    ('pace_trend', '配速', '', self._format_pace),
                    ('power_trend', '功率', 'W', lambda v: f"{v:.0f}")):
                t = ability.get(key)
                if not t:
                    continue
                if n == 1:
                    parts.append(f"{label}：当前 {fmt(t['current'])}{unit} vs 历史同距离比赛（仅 1 场，逐场比较，"
                                 f"不强调统计中位数），差 {t['diff']:+.1f}")
                else:
                    parts.append(f"{label}：当前 {fmt(t['current'])}{unit} vs {n} 场历史中位 {fmt(t['history_median'])}{unit}"
                                 f"（范围 {fmt(t['history_min'])}-{fmt(t['history_max'])}），"
                                 f"差 {t['diff']:+.1f}——{t.get('verdict', '')}（成绩比较，非能力结论）")
            eco = comp.get('economy', {})
            t = eco.get('hr_pace_ratio')
            if t:
                parts.append(f"效率（(m/h)/bpm）：当前 {t['current']:.2f} vs {t.get('sample_size', n)} 场历史中位 "
                             f"{t['history_median']:.2f}（范围 {t['history_min']:.2f}-{t['history_max']:.2f}），"
                             f"差 {t['diff']:+.2f}（成绩比较，非能力结论）")
            parts.append('【注意】状态与趋势以下方短期/长期模块为准；成绩参照池不构成短期或长期能力基线。')
            self._append_status_trends(comp, parts)
            return '\n'.join(parts)

        descriptive_only = comp.get('descriptive_only') is True
        # 5.0.1 F3：整体基线为空——明确空状态并禁止方向判断
        if comp.get('sample_size', 0) < 1:
            parts.append(
                f"【整体对比】{comp.get('message') or '最近无同类型跑步记录，无法对比'}（样本 0）——"
                f"无法形成同类型中位数对比，禁止输出任何同类型方向判断。")
        # 5.0.1 F2：跨全年描述性兜底标注（不误标为近 90/180 天证据）
        if descriptive_only:
            near = comp.get('near_subset_size')
            subset_txt = (f"；心率/配速/功率/效率使用距离相近子集 {near} 次"
                          if near else "")
            parts.append(
                f"【跨全年描述性基线】基线池共 {comp.get('sample_size')} 次同类型活动"
                f"（跨全年、不限温区{subset_txt}）。仅作描述——课程、天气、比赛目标可能不同，"
                f"禁止判断能力进步/退步或更快/更累等方向。")
        # no_temp 同池标注（PRD F2）：LSD 豁免温度过滤时，对比段标注同池口径
        _lt_scope = (comp.get('long_term') or {}).get('baseline_scope')
        _st_scope = (comp.get('short_term') or {}).get('baseline_scope')
        if 'no_temp' in (_lt_scope, _st_scope):
            parts.append('【全部 LSD 同池对比】')
        ability = comp.get('ability', {})
        if 'hr_trend' in ability:
            t = ability['hr_trend']
            if descriptive_only:
                parts.append(f"心率：当前 {t['current']:.0f} vs 历史中位数 {t['history_median']:.0f} bpm（仅作描述）")
            else:
                parts.append(f"心率：当前 {t['current']:.0f} vs 历史中位数 {t['history_median']:.0f} bpm，趋势：{t['verdict']}")
        if 'pace_trend' in ability:
            t = ability['pace_trend']
            # 格式化配速为 X分X秒/KM
            current_pace_str = self._format_pace(t['current'])
            history_pace_str = self._format_pace(t['history_median'])
            if descriptive_only:
                parts.append(f"配速：当前 {current_pace_str} vs 历史中位数 {history_pace_str}（仅作描述）")
            else:
                parts.append(f"配速：当前 {current_pace_str} vs 历史中位数 {history_pace_str}，趋势：{t['verdict']}")
        if 'power_trend' in ability:
            t = ability['power_trend']
            if descriptive_only:
                parts.append(f"功率：当前 {t['current']:.0f}W vs 历史中位数 {t['history_median']:.0f}W（仅作描述）")
            else:
                parts.append(f"功率：当前 {t['current']:.0f}W vs 历史中位数 {t['history_median']:.0f}W，趋势：{t['verdict']}")
        economy = comp.get('economy', {})
        if 'vr_trend' in economy:
            t = economy['vr_trend']
            if descriptive_only:
                parts.append(f"垂直振幅比：当前 {t['current']:.1f}% vs 历史中位数 {t['history_median']:.1f}%（仅作描述）")
            else:
                parts.append(f"垂直振幅比：当前 {t['current']:.1f}% vs 历史中位数 {t['history_median']:.1f}%，趋势：{t['verdict']}")
        if 'hr_pace_ratio' in economy:
            t = economy['hr_pace_ratio']
            if descriptive_only:
                parts.append(f"效率（(m/h)/bpm）：当前 {t['current']:.2f} vs 历史中位数 {t['history_median']:.2f}（仅作描述）")
            else:
                parts.append(f"效率（(m/h)/bpm）：当前 {t['current']:.2f} vs 历史中位数 {t['history_median']:.2f}，趋势：{t['verdict']}")
        
        # 追加短期状态/长期趋势/百分位/预期配速（比赛与普通课型共用）
        self._append_status_trends(comp, parts)

        return '\n'.join(parts) if parts else '（历史数据不足）'

    def _append_status_trends(self, comp: dict, parts: list) -> None:
        """短期状态、长期趋势、同比、百分位与预期配速的 Prompt 段落（5.0.2 F1 比赛路径复用）"""
        # 追加短期状态（第二批 F1：内核已给 evidence_level/verdict_allowed 与每指标有效样本，此处只消费）
        st = comp.get('short_term', {})
        if st and 'message' not in st:
            n = st.get('sample_size')
            if st.get('verdict_allowed'):
                def _st_word(vkey, nkey):
                    v = st.get(vkey)
                    # 单项有效样本不足或当前值缺失：显示样本有限并带有效样本数，禁止输出 None
                    return v if v is not None else f"样本有限（有效 {st.get(nkey)} 次）"
                parts.append(
                    f"短期状态（近{st['window_days']}天 {n} 次同类型）："
                    f"心率{_st_word('verdict_hr', 'hr_valid_samples')}，"
                    f"配速{_st_word('verdict_pace', 'pace_valid_samples')}，"
                    f"效率{_st_word('verdict_efficiency', 'eff_valid_samples')}。"
                    f"{st.get('evidence_reason') or ''}")
            else:
                # 描述级：注入差值与「仅作描述」限制，禁止方向 verdict
                diff_parts = []
                if st.get('hr_current') is not None and st.get('hr_baseline') is not None:
                    diff_parts.append(f"心率当前 {st['hr_current']:.0f} vs 中位 {st['hr_baseline']:.0f} bpm（差 {st.get('hr_diff') if st.get('hr_diff') is not None else 'N/A'}）")
                if st.get('pace_current_sec') is not None and st.get('pace_baseline_sec') is not None:
                    diff_parts.append(f"配速当前 {self._format_pace(st['pace_current_sec'])} vs 中位 {self._format_pace(st['pace_baseline_sec'])}（差 {st.get('pace_diff') if st.get('pace_diff') is not None else 'N/A'} 秒）")
                if st.get('eff_current') is not None and st.get('eff_baseline') is not None:
                    diff_parts.append(f"效率当前 {st['eff_current']:.2f} vs 中位 {st['eff_baseline']:.2f}（差 {st.get('eff_diff') if st.get('eff_diff') is not None else 'N/A'}）")
                diff_txt = ('；'.join(diff_parts)) if diff_parts else '无数值可比较'
                parts.append(
                    f"短期状态（近{st['window_days']}天 {n} 次同类型）：样本有限（n={n}），仅作描述，"
                    f"不得据此输出「更快/更慢/更轻松/更累/更经济/更费力」或近期状态方向。{diff_txt}"
                )
        elif st:
            # 5.0.1 F4：短期样本不足的空状态与禁止方向判断
            parts.append(
                f"短期状态（近{st.get('window_days', 60)}天）：{st.get('message') or '样本不足'}"
                f"（同类型样本 {st.get('sample_size')} 个）——样本不足，禁止判断近期状态方向，"
                f"不得用本次成绩替代不存在的基线。")

        # 追加长期趋势（第二批 F2/F3：verdict_allowed=false 时只给表现描述，不给能力 verdict）
        lt = comp.get('long_term', {})
        if lt:
            trend = lt.get('trend', {})
            if 'hr_slope_per_month' in trend:
                metric_names = {'hr': '心率', 'pace': '配速', 'efficiency': '效率'}
                scope_label = {'same_temp': '同温区', 'all_temp': '跨温区',
                               'no_temp': '全部LSD同池'}.get(lt.get('baseline_scope'), '')
                sens = lt.get('sensitivity') or {}
                sens_txt = '、'.join(
                    f"{metric_names[m]}方向{'稳定' if sens[m].get('direction_stable') else '对单月敏感'}"
                    for m in ('hr', 'pace', 'efficiency') if m in sens)
                base = (f"长期趋势（近{lt['window_days']}天，{scope_label}参照池，"
                        f"{lt.get('months_available')} 个有效月份的月度中位数回归）："
                        f"心率月均变化{trend['hr_slope_per_month']:+.2f}bpm，"
                        f"配速月均变化{trend['pace_slope_per_month']:+.2f}秒")
                if sens_txt:
                    base += f"（逐月剔除敏感性：{sens_txt}）"
                if lt.get('verdict_allowed'):
                    parts.append(f"{base}，判定：{lt['verdict']}。{lt.get('evidence_reason') or ''}")
                else:
                    parts.append(
                        f"{base}。{lt.get('evidence_reason') or '仅作表现描述'}；"
                        f"斜率符号只描述该参照池内的月均数值变化，不得解读为能力进步或退步。")
                    pts = '；'.join(
                        f"{p['month']}:{p['hr_median']:.0f}bpm/{self._format_pace(p['pace_median_sec'])}/{p['efficiency']:.1f}(n={p['count']})"
                        for p in (lt.get('monthly_points') or []))
                    if pts:
                        parts.append(f"长期月度中位点（月:心率/配速/效率）：{pts}")
            elif lt.get('verdict') == '数据不足':
                # 5.0.1 F4：长期无斜率时明确禁止趋势推断
                parts.append(
                    f"长期趋势（近{lt['window_days']}天）：{lt.get('message') or lt['verdict']}"
                    f"——未提供长期月度斜率，禁止写「能力上升/下降/上升通道/近月训练斜率」"
                    f"等趋势结论，不得用本次成绩替代不存在的回归证据。")
        
        # 去年同期对比（无数据时不出现，prompt 里不提示"没数据"）
        yoy = lt.get('yoy', {}) if lt else {}
        if yoy and yoy.get('hr_median') is not None:
            yoy_line = f"去年同期（近{yoy['window_days']}天中位）：心率 {yoy['hr_median']:.0f} bpm"
            if yoy.get('pace_median_sec'):
                yoy_line += f"，配速 {self._format_pace(yoy['pace_median_sec'])}"
            slope_parts = []
            if yoy.get('hr_slope_per_month') is not None:
                slope_parts.append(f"心率月均变化{yoy['hr_slope_per_month']:+.2f}bpm")
            if yoy.get('pace_slope_per_month') is not None:
                slope_parts.append(f"配速月均变化{yoy['pace_slope_per_month']:+.2f}秒")
            if slope_parts:
                yoy_line += (f"（{'，'.join(slope_parts)}，月度中位数回归共 "
                             f"{yoy.get('months_available')} 个有效月份）")
            parts.append(yoy_line)

        # 夏季同比（PRD F3）：有数据才注入，注明「夏季同期对比，消除季节温差影响」
        syoy = lt.get('summer_yoy') if lt else None
        if syoy and syoy.get('prev_hr_median') is not None:
            syoy_line = (f"夏季同期对比，消除季节温差影响：心率 今年 {syoy['curr_hr_median']:.0f} "
                         f"vs 去年同期 {syoy['prev_hr_median']:.0f} bpm")
            if syoy.get('curr_pace_median_sec') and syoy.get('prev_pace_median_sec'):
                syoy_line += (f"，配速 {self._format_pace(syoy['curr_pace_median_sec'])} "
                              f"vs {self._format_pace(syoy['prev_pace_median_sec'])}")
            parts.append(syoy_line)

        # 追加百分位
        pct = comp.get('percentile', {})
        if pct:
            parts.append(f"历史排名：{pct['rank_label']}，超过{pct['value']:.0f}%的相似跑步")
        
        # 追加预期配速
        exp = comp.get('expected_pace', {})
        if exp:
            diff = exp['diff_sec']
            if diff < -10:
                verdict = f'快 {abs(diff):.0f}秒'
            elif diff > 10:
                verdict = f'慢 {diff:.0f}秒'
            else:
                verdict = '基本持平'
            parts.append(f"同类型中位数：{self._format_pace(exp['expected_pace_sec'])}，实际{self._format_pace(exp['actual_pace_sec'])}，{verdict}")
        
        # 明确两个关键指标的统计口径，避免 AI 点评自相矛盾
        parts.append(
            "【指标口径说明】同类型中位数=同类型历史配速中位数；历史排名=按跑步经济性 (m/h)/bpm 的百分位。"
        )

    def _format_pace(self, pace_seconds: float) -> str:
        """将配速秒数转为 X分X秒/KM 格式"""
        return format_pace_chinese(pace_seconds)
    
    def _format_lap_data(self, laps: dict) -> str:
        """格式化分圈数据为 LLM Prompt 文本段落（5.0.1 F4：只消费统一每公里统计）"""
        if not laps or not laps.get('current'):
            return ''

        lines = ['## 分圈数据分析']
        current = laps.get('current', [])
        history_median = laps.get('history_median', [])
        history_p20_pace = laps.get('history_p20_pace', [])
        history_p80_pace = laps.get('history_p80_pace', [])
        sample_size = laps.get('sample_size', 0)

        # 5.0.2 F2：比赛分圈参考中位（n≥3，标签注明实际场次数）
        race_ref = laps.get('race_ref') or {}
        median_min = laps.get('median_min_samples') or 5
        is_race_laps = bool(race_ref)

        if sample_size > 0:
            baseline_note = laps.get('baseline_note')
            note_str = f'（{baseline_note}）' if baseline_note else ''
            lines.append(f'（对比前 {sample_size} 次同类型跑步{note_str}）')
        if is_race_laps and race_ref.get('label'):
            lines.append(f'【比赛参考中位】{race_ref["label"]}——仅作执行参照，'
                         f'禁止据此推断纯能力变化；禁止写成稳定统计真值；'
                         f'无 P20-P80 数据时禁止自行描述历史区间。')

        # 统一证据口径：中位线需每公里 ≥median_min 有效样本，P20-P80 需 ≥10；两指标独立判断
        median_flags = [(h or {}).get('pace_sec') is not None for h in history_median]
        band_flags = [v is not None for v in history_p20_pace]
        median_any = any(median_flags)
        band_any = any(band_flags)

        if sample_size == 0:
            lines.append('【说明】无同类型历史分圈数据，不提供历史中位配速/心率与 P20-P80 区间；'
                         '禁止将各圈与历史中位数比较快慢。')
        elif not median_any:
            samples_txt = '、'.join(
                f"{(s or {}).get('lap', i + 1)}km{(s or {}).get('pace', 0)}个"
                for i, s in enumerate(laps.get('per_km_samples', [])))
            lines.append(
                f'【说明】历史中位线需每公里至少 {median_min} 个有效样本；本次各公里有效样本不足'
                f'（每公里配速样本：{samples_txt}），不提供历史中位配速/心率与 P20-P80 区间，'
                f'仅展示本次曲线。禁止比较各圈与历史中位数的快慢。')
        else:
            if not all(median_flags):
                lines.append(f'【说明】仅部分公里达到每公里 ≥{median_min} 个有效样本，未显示历史中位数的公里'
                             '禁止历史快慢比较。')
            if band_any and not all(band_flags):
                lines.append('【说明】P20-P80 区间需每公里至少 10 个有效样本，仅部分公里显示区间。')

        cols = ['圈次', '配速', '心率', '功率']
        if median_any:
            cols.append('历史中位配速')
        if band_any:
            cols.extend(['历史P20配速', '历史P80配速'])
        lines.append('| ' + ' | '.join(cols) + ' |')
        lines.append('|' + '---|' * len(cols))

        for i, lap in enumerate(current):
            lap_num = lap.get('lap', i + 1)
            pace = self._format_pace(lap.get('pace_sec', 0))
            hr = f"{lap.get('avg_hr', 0):.0f}" if lap.get('avg_hr') else '--'
            power = f"{lap.get('avg_power', 0):.0f}W" if lap.get('avg_power') else '--'
            row = [f'{lap_num}KM', pace, hr, power]
            if median_any:
                hist = history_median[i] if i < len(history_median) else {}
                row.append(self._format_pace(hist['pace_sec'])
                           if hist.get('pace_sec') is not None else '—（该公里样本不足）')
            if band_any:
                p20 = self._format_pace(history_p20_pace[i]) if i < len(history_p20_pace) and history_p20_pace[i] is not None else '—（样本不足）'
                p80 = self._format_pace(history_p80_pace[i]) if i < len(history_p80_pace) and history_p80_pace[i] is not None else '—（样本不足）'
                row.extend([p20, p80])
            lines.append('| ' + ' | '.join(row) + ' |')

        # 提示 LLM 解读分圈表现；无历史中位数时禁止历史快慢比较引导
        lines.append('')
        if median_any:
            if is_race_laps:
                lines.append(f'请按计划赛段（见上方比赛计划段）解读分圈表现：各赛段配速/心率是否落在计划区间？'
                             f'哪几圈快于/慢于{race_ref.get("label", "比赛参考中位")}？'
                             f'将差异与比赛目标、赛道、气温、爬升、人群和配速策略结合解释；'
                             f'禁止把末段高心率自动等同后程失控；禁止用「多数圈快于参考中位」推出能力上升。')
            else:
                lines.append('请解读分圈表现：配速是否均匀？心率是否漂移（后半程明显升高）？'
                             '哪几圈相对历史中位数表现更好/更差？与历史P20-P80区间对比如何？')
        else:
            lines.append('请解读本次分圈表现：配速是否均匀？心率是否漂移（后半程明显升高）？'
                         '前后程表现如何？（本次无历史中位数可比，禁止历史快慢比较）')

        return '\n'.join(lines) + '\n'
    
    def _build_temp_impact_reference(self, raw_data: dict, pa_hr: dict) -> str:
        """构建气温影响参考上下文，供LLM分析时参考"""
        # 如果没有气温数据或Pa:Hr数据，返回空字符串
        min_temp = raw_data.get('min_temperature')
        max_temp = raw_data.get('max_temperature')
        
        if min_temp is None or max_temp is None or pd.isna(min_temp) or pd.isna(max_temp):
            # 如果有Pa:Hr数据但无气温数据，仍提供Pa:Hr信息
            if pa_hr:
                pa_hr_pct = pa_hr.get('pa_hr_pct', 0)
                verdict = pa_hr.get('verdict', '未知')
                return f"\n## 气温与热影响\n【Pa:Hr 有氧解耦分析】\n- 本次 Pa:Hr 有氧解耦值：{pa_hr_pct:+.1f}%（{verdict}）\n\n请在教练点评中适当提及气温对训练的影响（如果相关的话）。"
            return ""
        
        # 计算中值气温
        mid_temp = (min_temp + max_temp) / 2
        
        # 计算基准值（从历史数据中查找）
        ref_power = raw_data.get('avg_power', 0)
        category = raw_data.get('category', '')
        
        # 初始化参考值
        ref_hr = None
        hot_temp_range = "--"
        hot_hr = None
        rise_pct = None
        
        # 从df_all中查询基准数据（基准温度15-20°C，基准功率区间±2.5W）
        if hasattr(self, 'df_all') and self.df_all is not None:
            df = self.df_all.copy()
            # 与 _get_long_term_baseline 保持一致：归一化分类（全马/半马/赛事 → race）
            df['_category_norm'] = df['category'].apply(
                lambda c: 'race' if c in ('full_marathon', 'half_marathon', 'race_event') else c
            )
            category_norm = 'race' if category in ('full_marathon', 'half_marathon', 'race_event') else category
            
            # 计算功率区间边界
            power_lower = ref_power - 2.5
            power_upper = ref_power + 2.5
            
            # 查询基准温度（15-20°C）下相同分类、相似功率的平均心率
            base_df = df[
                (df['_category_norm'] == category_norm) &
                (df['avg_power'] >= power_lower) &
                (df['avg_power'] <= power_upper) &
                ((df['min_temperature'] + df['max_temperature']) / 2 >= 15) &
                ((df['min_temperature'] + df['max_temperature']) / 2 <= 20) &
                (df['avg_hr'].notna())
            ]
            if len(base_df) >= 3:  # 至少3个样本
                ref_hr = base_df['avg_hr'].mean()
            
            # 查询高温区间（25-30°C）下相同分类、相似功率的平均心率
            hot_df = df[
                (df['_category_norm'] == category_norm) &
                (df['avg_power'] >= power_lower) &
                (df['avg_power'] <= power_upper) &
                ((df['min_temperature'] + df['max_temperature']) / 2 >= 25) &
                ((df['min_temperature'] + df['max_temperature']) / 2 <= 30) &
                (df['avg_hr'].notna())
            ]
            if len(hot_df) >= 3:  # 至少3个样本
                hot_hr = hot_df['avg_hr'].mean()
                hot_temp_range = "25-30°C"
            
            # 计算心率上升百分比
            if ref_hr and hot_hr:
                rise_pct = (hot_hr - ref_hr) / ref_hr * 100
        
        # 构建气温影响参考文本
        lines = ["\n## 气温与热影响"]
        lines.append("【热效率数据】")
        lines.append(f"- 本次跑步气温：{min_temp:.1f}-{max_temp:.1f}°C（中值 {mid_temp:.1f}°C）")
        
        if ref_hr:
            lines.append(f"- 基准温度（15-20°C）下，你在 {ref_power:.0f}W 功率输出时平均心率为 {ref_hr:.1f} bpm")
        else:
            lines.append(f"- 基准温度（15-20°C）下，未找到足够样本匹配 {ref_power:.0f}W 功率的数据")
        
        if hot_hr and ref_hr:
            lines.append(f"- 近期高温天（{hot_temp_range}）同功率下心率升至 {hot_hr:.1f} bpm，上升约 {rise_pct:+.1f}%")
        elif hot_hr:
            lines.append(f"- 近期高温天（{hot_temp_range}）同功率下心率约为 {hot_hr:.1f} bpm")
        else:
            lines.append(f"- 高温区间（25-30°C）暂无足够匹配数据")
        
        if pa_hr:
            pa_hr_pct = pa_hr.get('pa_hr_pct', 0)
            verdict = pa_hr.get('verdict', '未知')
            lines.append(f"- 本次 Pa:Hr 有氧解耦值：{pa_hr_pct:+.1f}%（{verdict}）")
        
        lines.append("\n请在教练点评中适当提及气温对训练的影响（如果相关的话）。")
        
        # 添加状态和趋势参考信息
        # 这里我们无法直接访问分析结果，所以只是预留位置
        # 在实际的 LLM 报告生成器中会处理这些信息
        
        return "\n".join(lines)