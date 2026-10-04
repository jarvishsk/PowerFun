"""跑步深度分析器"""

import http.client
import json
import logging
import math
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.config import DEFAULT_CONFIG, HR_ZONE_PERCENTAGES
from src.classifier import HeartRateClassifier
from src.utils import format_pace_chinese

logger = logging.getLogger("PowerFun.deep_analyzer")


class DeepRunAnalyzer:
    """跑步深度分析器"""

    # 心率默认值（从 DEFAULT_CONFIG 统一读取）
    DEFAULT_MAX_HR = DEFAULT_CONFIG.get('max_hr')
    DEFAULT_RESTING_HR = DEFAULT_CONFIG.get('resting_hr')

    def __init__(self, df_all: pd.DataFrame, target_date=None, max_hr: int = None, resting_hr: int = None,
                 lap_data: dict = None, raw_laps: list = None):
        """
        Args:
            df_all: 完整 DataFrame（包含所有跑步记录，用于对比分析）
            target_date: 对比基准日期，取该日期之前的历史数据
            max_hr: 最大心率（默认从 DEFAULT_CONFIG 读取）
            resting_hr: 静息心率（默认从 DEFAULT_CONFIG 读取）
            lap_data: 分圈数据 dict，格式见需求文档（current/history_median/history_p20_pace/history_p80_pace/sample_size）
            raw_laps: 原始分圈数据列表（含 distance_m/duration_sec/avg_hr），用于 Pa:Hr 计算
        """
        self.df_all = df_all
        self.target_date = target_date
        # 使用传入值，未传入时从 DEFAULT_CONFIG 读取
        self.max_hr = max_hr or self.DEFAULT_MAX_HR
        self.resting_hr = resting_hr or self.DEFAULT_RESTING_HR
        self.lap_data = lap_data or {}
        self.raw_laps = raw_laps or []
    
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
        
        # Pa:Hr 有氧解耦分析（使用原始 lap 数据，不是转换后的）
        result['pa_hr'] = self._calc_pa_hr(self.raw_laps) if self.raw_laps else None
        
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

        # 中位数基线放宽链（PRD F2：保时效优先）：90天同温区 → 90天不限温区 → 180天不限温区
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
        if target_ts is not None:
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
                if len(d) >= 3:
                    df_same = d.sort_values('date', ascending=False)
                    baseline_scope = scope
                    break
            else:
                df_same = pd.DataFrame(columns=df.columns)
        else:
            # 无目标日期：不限制窗口与温区（保持原行为）
            df_same = _base_candidates()
            baseline_scope = 'all_temp'
        
        # 上限15次，避免样本过多时过度平均
        if len(df_same) > 15:
            df_same = df_same.head(15)
        
        if len(df_same) < 1:
            return {
                'sample_size': len(df_same),
                'message': f'最近无同类型跑步记录，无法对比',
            }
        
        # 3.1 能力变化
        dist = row.get('distance', 0)
        dist_tolerance = dist * 0.2  # ±20% 距离容忍
        df_near = df_same[(df_same['distance'] >= dist * 0.8) & (df_same['distance'] <= dist * 1.2)]
        # 距离相近样本不足时降级为同温区样本
        df_compare = df_near if len(df_near) >= 3 else df_same
        
        # 统计工具函数
        def stats(series):
            """返回中位数、P20、P80"""
            return {
                'median': round(series.median(), 2),
                'p20': round(series.quantile(0.20), 2),
                'p80': round(series.quantile(0.80), 2),
            }
        
        result = {
            'sample_size': len(df_same),
            'ability': {},
            'economy': {},
            'temp_bucket': target_bucket,
            'baseline_scope': baseline_scope,
        }
        
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
        
        # 新增：状态评估与趋势分析
        result['short_term'] = self._calc_short_term(row, category_norm, target_bucket, df)
        result['long_term'] = self._calc_long_term(row, category_norm, target_bucket, df)
        result['tech_changes'] = self._calc_tech_changes(row, df_same)
        
        # 获取长期基线数据用于百分位和预期配速计算（PRD F5：同口径三级选择）
        df_long_term, _lt_scope = self._get_long_term_baseline(row, category_norm, target_bucket, df)
        result['percentile'] = self._calc_percentile(row, df_long_term)
        result['expected_pace'] = self._calc_expected_pace(row, df_long_term)
        
        return result
    
    def _extract_findings(self, result: dict) -> list:
        """从分析结果中提取关键发现"""
        findings = []
        comparison = result.get('comparison', {})
        ability = comparison.get('ability', {})
        economy = comparison.get('economy', {})
        
        if 'hr_trend' in ability:
            t = ability['hr_trend']
            if t['diff'] < -3:
                findings.append(f"心率下降 {abs(t['diff']):.0f}bpm，心肺能力提升明显")
            elif t['diff'] > 3:
                findings.append(f"心率上升 {t['diff']:.0f}bpm，可能疲劳积累或恢复不足")
        
        if 'pace_trend' in ability:
            t = ability['pace_trend']
            if t['diff'] < -5:
                findings.append(f"配速提升 {abs(t['diff']):.0f}秒/公里，速度能力增强")
            elif t['diff'] > 5:
                findings.append(f"配速下降 {t['diff']:.0f}秒/公里，可能状态不佳")
        
        if 'power_trend' in ability:
            t = ability['power_trend']
            if abs(t['diff']) > 10:
                findings.append(f"功率变化 {t['diff']:+.0f}W，输出能力{'增强' if t['diff'] > 0 else '下降'}")
        
        if 'vr_trend' in economy:
            t = economy['vr_trend']
            if t['diff'] < -0.5:
                findings.append(f"垂直振幅比下降 {abs(t['diff']):.1f}%，跑步经济性改善")
            elif t['diff'] > 0.5:
                findings.append(f"垂直振幅比上升 {t['diff']:.1f}%，跑步经济性下降")
        
        if 'hr_pace_ratio' in economy:
            t = economy['hr_pace_ratio']
            if t['diff'] > 1:
                findings.append(f"效率（(m/h)/bpm）提升，跑步经济性改善")
            elif t['diff'] < -1:
                findings.append(f"效率（(m/h)/bpm）下降，跑步经济性变差")
        
        if not findings:
            findings.append("各项指标稳定，保持当前训练节奏")
        
        return findings
    
    def _analyze_laps(self, lap_data: list[dict], recent_laps: list[list[dict]]) -> dict:
        """分析分圈数据，对比历史同类型
        
        Args:
            lap_data: 本次分圈数据列表
            recent_laps: 前 N 次同类型分圈数据列表，每个元素是一次跑步的分圈列表
        
        Returns:
            分圈分析结果 dict
        """
        # 过滤残圈：距离 < 1KM 的圈舍弃
        if lap_data:
            lap_data = [lap for lap in lap_data if lap.get('distance_m', 0) >= 1000]
        if recent_laps:
            recent_laps = [
                [lap for lap in run_laps if lap.get('distance_m', 0) >= 1000]
                for run_laps in recent_laps
            ]
        
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
        
        if not recent_laps:
            return {
                'current': current,
                'history_median': [],
                'history_p20_pace': [],
                'history_p80_pace': [],
                'sample_size': 0,
            }
        
        # 对每个圈序号，计算历史中位数 + P20/P80 区间
        max_laps = len(current)
        history_median = []
        history_p20_pace = []
        history_p80_pace = []
        
        for lap_idx in range(1, max_laps + 1):
            paces = []
            hrs = []
            for run_laps in recent_laps:
                for rl in run_laps:
                    if rl.get('lap_index') == lap_idx:
                        p = rl.get('pace_sec_per_km', 0)
                        if p > 0:
                            paces.append(p)
                        h = rl.get('avg_hr')
                        if h is not None and not pd.isna(h) and h > 0:
                            hrs.append(h)
            
            median_pace = float(np.percentile(paces, 50)) if paces else 0
            if paces:
                p20 = float(np.percentile(paces, 20))
                p80 = float(np.percentile(paces, 80))
            else:
                p20 = 0
                p80 = 0
            
            avg_hr = sum(hrs) / len(hrs) if hrs else None
            
            history_median.append({
                'lap': lap_idx,
                'pace_sec': round(median_pace, 2) if median_pace else 0,
                'avg_hr': round(avg_hr, 0) if avg_hr else None,
            })
            
            history_p20_pace.append(round(p20, 2) if p20 else 0)
            history_p80_pace.append(round(p80, 2) if p80 else 0)
        
        return {
            'current': current,
            'history_median': history_median,
            'history_p20_pace': history_p20_pace,
            'history_p80_pace': history_p80_pace,
            'sample_size': len(recent_laps),
        }

    def _calc_tech_changes(self, row: pd.Series, df_same: pd.DataFrame) -> list:
        """对比本次 vs 历史中位数，仅列出超阈值变化的技术指标

        阈值：vertical_ratio ±0.2、ground_contact_time ±5ms、cadence ±2spm、stride_length ±1cm
        方向：VR/GCT 越低越好；cadence/stride 只做变化量不做方向判定

        Returns:
            变化项列表，每项含 metric/current/baseline/diff/unit/direction
        """
        def hist_median(col: str):
            if col in df_same.columns and df_same[col].notna().any():
                return df_same[col].dropna().median()
            return None

        specs = [
            ('vertical_ratio', '垂直振幅比', 0.2, 'lower', '%'),
            ('ground_contact_time', '触地时间', 5, 'lower', 'ms'),
            ('cadence', '步频', 2, 'neutral', 'spm'),
            ('stride_length', '步幅', 1, 'neutral', 'cm'),
        ]

        changes = []
        for col, label, threshold, direction, unit in specs:
            baseline = hist_median(col)
            curr = row.get(col)
            if baseline is None or curr is None or pd.isna(curr):
                continue
            diff = curr - baseline
            if abs(diff) < threshold:
                continue
            if direction == 'lower':
                verdict = 'improved' if diff < 0 else 'regressed'
            else:
                verdict = 'changed'
            changes.append({
                'metric': label,
                'field': col,
                'current': round(curr, 2),
                'baseline': round(baseline, 2),
                'diff': round(diff, 2),
                'unit': unit,
                'direction': verdict,
            })
        return changes

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

    # 基线新鲜度门槛：最新样本距目标日超过该天数视为过期（PRD F1）
    BASELINE_FRESHNESS_DAYS = 45

    def _select_baseline(self, df_window: pd.DataFrame, temp_bucket: Optional[str]) -> tuple:
        """三级基线选择（PRD F1）：同温区(新鲜) → 不限温区(新鲜) → 数据不足

        Args:
            df_window: 已按时间窗口/类型筛选的候选样本（未做温区筛选）
            temp_bucket: 目标温区（None 表示目标无温区数据，跳过第一级）

        Returns:
            (df_baseline, baseline_scope, insufficient_reason)
            采用时 scope 为 'same_temp'/'all_temp'，reason 为 None；
            数据不足时返回 (空 DataFrame, None, '样本不足'/'基线过旧')
        """
        target_ts = pd.Timestamp(self.target_date)
        df_temp = df_window.copy()
        if 'min_temperature' in df_temp.columns and 'max_temperature' in df_temp.columns:
            df_temp['_temp_bucket'] = df_temp.apply(lambda r: self._get_temp_bucket(r), axis=1)
            # 无温区记录不进入基线，避免把缺失温度误判为冷天
            df_temp = df_temp[df_temp['_temp_bucket'].notna()]

        def _fresh(d: pd.DataFrame) -> bool:
            """最新样本距目标日 ≤45 天（PRD F1 新鲜度门槛）"""
            return (target_ts - d['date'].max()).days <= self.BASELINE_FRESHNESS_DAYS

        # 1. 窗口内同温区：≥3 次且新鲜
        if temp_bucket is not None and '_temp_bucket' in df_temp.columns:
            d_same = df_temp[df_temp['_temp_bucket'] == temp_bucket]
            if len(d_same) >= 3 and _fresh(d_same):
                return d_same, 'same_temp', None

        # 2. 窗口内不限温区：≥3 次且新鲜（跨温区基线）
        if len(df_temp) >= 3 and _fresh(df_temp):
            return df_temp, 'all_temp', None

        # 3. 数据不足：区分样本不足(n<3) / 基线过旧(最新样本>45天)
        if len(df_temp) >= 3:
            return pd.DataFrame(), None, '基线过旧'
        return pd.DataFrame(), None, '样本不足'
    
    def _get_long_term_baseline(self, row: pd.Series, category: str, temp_bucket: str, df_all: pd.DataFrame) -> tuple:
        """获取长期基线数据（PRD F5：三级基线选择 + 新鲜度门槛，口径与 _calc_long_term 一致）

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
        
        # 时间窗口：前180天
        cutoff_ts = target_ts - pd.Timedelta(days=180)
        df_filtered = df_filtered[df_filtered['date'] >= cutoff_ts]
        df_filtered = df_filtered[df_filtered['date'] <= target_ts]
        
        # 三级基线选择（PRD F5 同步 F1）：同温区(新鲜) → 不限温区(新鲜) → 数据不足
        df_baseline, baseline_scope, _reason = self._select_baseline(df_filtered, temp_bucket)
        if df_baseline.empty:
            return pd.DataFrame(), None
        
        # 限制样本上限为30次
        if len(df_baseline) > 30:
            df_baseline = df_baseline.sort_values('date', ascending=False).head(30)
        
        return df_baseline, baseline_scope
    
    def _calc_short_term(self, row: pd.Series, category: str, temp_bucket: str, df_all: pd.DataFrame) -> dict:
        """计算短期状态（近30天同类型同温区）"""
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
        
        # 时间窗口：前30天
        cutoff_ts = target_ts - pd.Timedelta(days=30)
        df_filtered = df_filtered[df_filtered['date'] >= cutoff_ts]
        df_filtered = df_filtered[df_filtered['date'] <= target_ts]
        
        # 三级基线选择（PRD F1）：同温区(≥3次且新鲜) → 不限温区(≥3次且新鲜) → 数据不足
        # 近30天窗口天然满足 45 天新鲜度门槛
        df_same_temp, baseline_scope, insufficient_reason = self._select_baseline(df_filtered, temp_bucket)
        
        # 1次也能比，不返回"数据不足"
        if len(df_same_temp) < 1:
            return {
                'window_days': 30,
                'sample_size': len(df_same_temp),
                'temp_bucket': temp_bucket,
                'baseline_scope': baseline_scope,
                'message': insufficient_reason or '样本不足',
            }
        
        # 计算中位数
        hr_median = df_same_temp['avg_hr'].dropna().median() if 'avg_hr' in df_same_temp.columns else None
        pace_median = df_same_temp['avg_pace_sec'].dropna().median() if 'avg_pace_sec' in df_same_temp.columns else None
        
        # 计算效率中位数 (m/h)/bpm
        df_eff_valid = df_same_temp[(df_same_temp['avg_pace_sec'] > 0) & (df_same_temp['avg_hr'] > 0)].copy() if 'avg_pace_sec' in df_same_temp.columns and 'avg_hr' in df_same_temp.columns else pd.DataFrame()
        efficiency_median = None
        if not df_eff_valid.empty:
            df_eff_valid['efficiency'] = 3600000.0 / (df_eff_valid['avg_pace_sec'] * df_eff_valid['avg_hr'])
            efficiency_median = df_eff_valid['efficiency'].dropna().median()
        
        # 当前值
        curr_hr = row.get('avg_hr', 0)
        curr_pace = row.get('avg_pace_sec', 0)
        curr_eff = 0
        if curr_pace > 0 and curr_hr > 0:
            curr_eff = 3600000.0 / (curr_pace * curr_hr)
        
        # 计算差值
        hr_diff = (curr_hr - hr_median) if hr_median is not None else 0
        pace_diff = (curr_pace - pace_median) if pace_median is not None else 0
        eff_diff = (curr_eff - efficiency_median) if efficiency_median is not None else 0
        
        # 判读逻辑
        hr_verdict = '更轻松' if hr_diff < -3 else ('更累' if hr_diff > 3 else '持平')
        pace_verdict = '更快' if pace_diff < -5 else ('更慢' if pace_diff > 5 else '持平')
        eff_verdict = '更经济' if eff_diff > 3 else ('更费力' if eff_diff < -3 else '持平')
        
        temp_bucket_label = 'all' if baseline_scope == 'all_temp' else temp_bucket

        # 当前值与基线值（供模板渲染数据解释；0/NaN 视为数据不足）
        def _clean_num(val):
            if val is None or pd.isna(val) or val == 0:
                return None
            return val

        return {
            'window_days': 30,
            'sample_size': len(df_same_temp),
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
        }
    
    def _calc_long_term(self, row: pd.Series, category: str, temp_bucket: str, df_all: pd.DataFrame) -> dict:
        """计算长期趋势（近180天同类型同温区线性回归），含去年同期对比"""
        # 获取目标日期
        if self.target_date is None:
            return None
        target_ts = pd.Timestamp(self.target_date)

        # 去年同期等价窗口（对齐月日，向前相同天数），无数据时为 {'message': '数据不足'}
        yoy = self._calc_yoy(row, category, df_all)
        
        # 筛选同类型数据
        df_filtered = df_all[df_all['_category_norm'] == category].copy()
        
        # 排除本次
        activity_id = row.get('activity_id')
        if activity_id:
            df_filtered = df_filtered[df_filtered['activity_id'] != activity_id]
        else:
            df_filtered = df_filtered[df_filtered['date'] != target_ts]
        
        # 时间窗口：前180天
        cutoff_ts = target_ts - pd.Timedelta(days=180)
        df_filtered = df_filtered[df_filtered['date'] >= cutoff_ts]
        df_filtered = df_filtered[df_filtered['date'] <= target_ts]
        
        # 三级基线选择（PRD F1）：同温区(≥3次且新鲜) → 不限温区(≥3次且新鲜) → 数据不足
        df_same_temp, baseline_scope, insufficient_reason = self._select_baseline(df_filtered, temp_bucket)
        
        # 限制样本上限为30次
        if len(df_same_temp) > 30:
            df_same_temp = df_same_temp.sort_values('date', ascending=False).head(30)
        
        if len(df_same_temp) < 3:
            return {
                'window_days': 180,
                'sample_size': len(df_same_temp),
                'months_available': 0,
                'verdict': '数据不足',
                'message': insufficient_reason,
                'yoy': yoy,
            }
        
        # 按月分组，计算每月中位数与月样本数（使用 .copy() 避免 SettingWithCopyWarning）
        df_same_temp = df_same_temp.copy()
        df_same_temp['year_month'] = df_same_temp['date'].dt.to_period('M')
        monthly_stats = df_same_temp.groupby('year_month').agg(
            avg_hr=('avg_hr', 'median'),
            avg_pace_sec=('avg_pace_sec', 'median'),
            count=('avg_pace_sec', 'size'),
        ).reset_index()
        
        # 过滤掉无效值
        monthly_stats = monthly_stats.dropna(subset=['avg_hr', 'avg_pace_sec'])
        
        # 回归只纳入每月≥2样本的月份（PRD F1：单月单样本不进回归，样本总数报告不变）
        regress_stats = monthly_stats[monthly_stats['count'] >= 2]
        
        # 剔除后至少需要3个有效月份
        if len(regress_stats) < 3:
            return {
                'window_days': 180,
                'sample_size': len(df_same_temp),
                'months_available': len(monthly_stats),
                'baseline_scope': baseline_scope,
                'verdict': '数据不足',
                'message': '样本不足',
                'yoy': yoy,
            }
        
        # 准备线性回归数据：x 轴用真实月份间隔（PRD F1，修正原月份序号当 x 轴导致的荒谬斜率）
        months_numeric = np.array(
            [(p - regress_stats['year_month'].iloc[0]).n for p in regress_stats['year_month']],
            dtype=float,
        )
        hr_values = regress_stats['avg_hr'].values
        pace_values = regress_stats['avg_pace_sec'].values
        
        # 计算线性回归斜率（单位：每月变化）
        hr_slope = np.polyfit(months_numeric, hr_values, 1)[0] if len(hr_values) > 1 else 0
        pace_slope = np.polyfit(months_numeric, pace_values, 1)[0] if len(pace_values) > 1 else 0
        
        # 计算效率斜率（与心率/配速共用同一 x 轴）
        efficiency_values = []
        for _, r in regress_stats.iterrows():
            if r['avg_pace_sec'] > 0 and r['avg_hr'] > 0:
                efficiency_values.append(3600000.0 / (r['avg_pace_sec'] * r['avg_hr']))
            else:
                efficiency_values.append(np.nan)
        efficiency_values = np.array(efficiency_values)
        eff_mask = ~np.isnan(efficiency_values)
        
        if eff_mask.sum() > 1:
            efficiency_slope = np.polyfit(months_numeric[eff_mask], efficiency_values[eff_mask], 1)[0]
        else:
            efficiency_slope = 0
        
        # 计算斜率后的判定
        hr_slope = float(hr_slope)  # bpm/月
        pace_slope = float(pace_slope)  # 秒/月
        efficiency_slope = float(efficiency_slope)  # 效率单位/月
        
        # 综合判定 + 理由
        neg_signals = []
        pos_signals = []
        if hr_slope < -1:
            pos_signals.append(f'心率月降{abs(hr_slope):.1f}bpm')
        elif hr_slope > 1:
            neg_signals.append(f'心率月升{hr_slope:.1f}bpm')
        
        if pace_slope < -2:
            pos_signals.append(f'配速月升{abs(pace_slope):.1f}秒')
        elif pace_slope > 2:
            neg_signals.append(f'配速月降{pace_slope:.1f}秒')
        
        if efficiency_slope > 1:
            pos_signals.append(f'效率月升{efficiency_slope:.1f}')
        elif efficiency_slope < -1:
            neg_signals.append(f'效率月降{abs(efficiency_slope):.1f}')
        
        reasons = neg_signals + pos_signals
        
        # verdict：正负信号兼有 → 分化；仅负向 → 退步；仅正向 → 进步；无信号 → 稳定
        if not reasons:
            verdict = '稳定'
            reason = '各项指标变化在正常范围内'
        elif neg_signals and pos_signals:
            verdict = '分化'
            reason = '，'.join(reasons)
        elif neg_signals:
            verdict = '退步'
            reason = '，'.join(reasons)
        elif pos_signals:
            verdict = '进步'
            reason = '，'.join(reasons)
        else:
            verdict = '稳定'
            reason = '各项指标变化在正常范围内'
        
        # 跨温区基线标注（PRD F1）
        if baseline_scope == 'all_temp':
            reason = f'{reason}（跨温区基线）'
        
        return {
            'window_days': 180,
            'sample_size': len(df_same_temp),
            'months_available': len(monthly_stats),
            'baseline_scope': baseline_scope,
            'trend': {
                'hr_slope_per_month': round(float(hr_slope), 2),
                'pace_slope_per_month': round(float(pace_slope), 2),
                'efficiency_slope_per_month': round(float(efficiency_slope), 2),
            },
            'verdict': verdict,
            'reason': reason,
            'yoy': yoy,
        }
    
    def _calc_yoy(self, row: pd.Series, category: str, df_all: pd.DataFrame) -> Optional[dict]:
        """去年同期等价窗口对比：本次日期 -1 年，向前取与长期窗口一致的天数（180 天）

        对比维度：心率中位、配速中位（样本≥3 时附月趋势斜率）
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

        hr_median = _clean(df_win['avg_hr'].dropna().median()) if 'avg_hr' in df_win.columns else None
        pace_median = _clean(df_win['avg_pace_sec'].dropna().median()) if 'avg_pace_sec' in df_win.columns else None

        if hr_median is None and pace_median is None:
            return {'message': '数据不足'}

        result = {
            'window_days': window_days,
            'sample_size': len(df_win),
            'hr_median': round(hr_median, 0) if hr_median is not None else None,
            'pace_median_sec': round(pace_median, 0) if pace_median is not None else None,
            'current_hr': round(row.get('avg_hr', 0), 0),
            'current_pace_sec': row.get('avg_pace_sec', 0),
        }

        # 样本≥3 时计算月趋势斜率（实现从简：按日期线性回归）
        if len(df_win) >= 3:
            df_fit = df_win.sort_values('date')
            x = (df_fit['date'] - yoy_start).dt.days.astype(float).values
            if hr_median is not None and df_fit['avg_hr'].notna().sum() >= 3:
                mask = df_fit['avg_hr'].notna().values
                slope = np.polyfit(x[mask], df_fit.loc[mask, 'avg_hr'].values, 1)[0]
                result['hr_slope_per_month'] = round(float(slope) * 30, 2)
            if pace_median is not None and df_fit['avg_pace_sec'].notna().sum() >= 3:
                mask = df_fit['avg_pace_sec'].notna().values
                slope = np.polyfit(x[mask], df_fit.loc[mask, 'avg_pace_sec'].values, 1)[0]
                result['pace_slope_per_month'] = round(float(slope) * 30, 2)

        return result

    def _calc_percentile(self, row: pd.Series, df_baseline: pd.DataFrame) -> dict:
        """计算百分位排名"""
        if len(df_baseline) < 5:
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
        
        if len(history_effs) < 5:
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
    """LLM 文字报告生成器（配置从 config.py 读取）"""
    
    def __init__(self, df_all: pd.DataFrame = None):
        from src.config import LLM_CONFIG
        self.config = LLM_CONFIG
        self.api_key = self.config.get('api_key', '')
        self.df_all = df_all
    
    def generate(self, analysis_data: dict, user_note: str = None) -> tuple:
        """基于结构化分析数据生成 LLM 文字报告

        Args:
            analysis_data: DeepRunAnalyzer.analyze() 返回的结果
            user_note: 跑者体感备注（可选），将与客观数据一起提交给 AI 综合分析

        Returns:
            (report_text, actual_model, brief_summary) 元组，actual_model 为 LLM 实际返回的模型名，
            brief_summary 为解析出的 100 字简报（解析失败时为空字符串）
        """
        display_name = self.config.get('display_name', 'AI模型')
        if not self.api_key:
            return "（API Key 未配置，跳过 AI 分析）", display_name, ""

        prompt = self._build_prompt(analysis_data, user_note=user_note)
        logger.info(f"prompt 字符数: {len(prompt)}")

        try:
            content, actual_model = self._call_api(prompt)
            # 解析 <<<BRIEF>>> 分隔块：正文去掉该块，简报单独返回
            content, brief = self._parse_brief(content)
            return content, actual_model, brief
        except Exception as e:
            logger.error(f"LLM API 调用失败: {e}")
            return f"（AI 分析调用失败: {e}）", display_name, ""

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
        findings = data.get('findings', [])
        laps = data.get('laps', {})
        pa_hr = data.get('pa_hr', {})

        # 构建分圈数据段落
        lap_section = self._format_lap_data(laps)

        # 构建气温影响参考
        temp_impact_section = self._build_temp_impact_reference(raw, pa_hr)

        # 构建跑者自述段落（如有）
        runner_note_section = ''
        if user_note:
            import html as _html
            safe_note = _html.escape(user_note)
            truncated = safe_note if len(safe_note) <= 800 else safe_note[:800] + '\u2026'
            runner_note_section = f"## 🏃 跑者自述（体感反馈）\n> {truncated}\n\n"

        # C1：技术段只在有变化时展开（tech_changes 来自 _compare_with_history）
        tech_changes = comparison.get('tech_changes', [])
        tech_lines = [
            f"- 步频：{raw.get('cadence', 0)} spm（{efficiency.get('cadence_eval', '')}）",
            f"- 步幅：{raw.get('stride_length_cm', 0):.1f} cm",
            f"- 垂直振幅比：{raw.get('vertical_ratio_pct', 0):.1f}%（{efficiency.get('vertical_ratio_eval', '')}）",
            f"- 触地时间：{raw.get('ground_contact_ms', 0):.1f} ms（{efficiency.get('ground_contact_eval', '')}）",
        ]
        if tech_changes:
            tech_lines.append('与历史中位数相比的变化（仅列出超阈值项，方向：VR/触地时间越低越好）：')
            for c in tech_changes:
                if c['direction'] == 'improved':
                    word = '改善'
                elif c['direction'] == 'regressed':
                    word = '退步'
                else:
                    word = '升高' if c['diff'] > 0 else '降低'
                diff_str = f"{c['diff']:+.2f}".rstrip('0').rstrip('.')
                tech_lines.append(
                    f"- {c['metric']}：当前 {c['current']}{c['unit']} vs 历史中位 {c['baseline']}{c['unit']}（{diff_str}{c['unit']}，{word}）"
                )
            tech_instruction = ('技术效率分析：只对上述有变化的指标展开点评（未变化指标不必罗列），'
                                '评价较差的指标须给改进目标值（如"触地时间压至 220-230ms"）和对应练习方法')
        else:
            tech_instruction = ('技术效率分析：本次各项技术指标与历史水平相比均无超阈值变化，'
                                '本节用一句话确认稳定即可，不要逐项罗列指标数值')
        tech_section = '\n'.join(tech_lines)

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
{temp_impact_section}
## 关键发现
{chr(10).join(f'- {f}' for f in findings)}

请生成包含以下 6 个小节的分析文字（小节标题格式 `## emoji 标题`，## 后一个空格、emoji 后一个空格，无其他连接符，标题文本与清单完全一致）：
## 🔥 本次跑步小结 / ## 🏃 强度与负荷分析 / ## ⚙️ 技术效率分析 / ## 📈 能力变化趋势 / ## 🔄 分圈表现分析 / ## 🎯 改进建议

1. 本次跑步小结：2-3 句通俗有温度，末尾一句话提炼核心价值（易记锚点，如"用 Z1/Z2 的心率代价跑出接近 Z3 的配速输出"）
2. 强度与负荷分析：心率、功率、训练效果综合评价
3. {tech_instruction}
4. 能力变化趋势：基于历史对比解读
5. 分圈表现分析：按前/中/后程拆解配速与心率变化，指出"热身不足""后程过猛""心率漂移"等现象，还原训练现场；段内用无序列表，每项 `- **前段（X-Y km）**：描述`，中段/后段同格式，不得写成连续长段
6. 改进建议：只针对本次跑步暴露的问题（如分圈漂移、心率失控、配速执行偏差、天气应对失误等）提 2-5 条建议；长期固化存在的技术短板除非本次明显恶化，否则不提；按【最高优先】→【次优先】→【中长期】分层并说明紧迫性；若本次执行无大问题，允许只给 2-3 条，不强行凑数；连续编号列表，格式 `1. **【最高优先】标题**：内容`
7. 报告最后一行输出 `<<<BRIEF>>>100字以内的简要总结（突出训练重点和特点，语言专业简洁，80-120字）<<<END>>>` 包裹的简报

要求：语言专业严谨务实；Markdown 规整，次级小标题（分圈阶段、建议优先级、技术目标）必须 `**加粗**`；避免堆砌数字，重点解读趋势；建议具体可执行并给量化目标；避免绝对化表述（如"无功率漂移"），改用"未出现明显迹象""暂未观察到"；总字数 ≤1500；不要输出报告标题、类型、日期、配速等 header，直接从正文小结开始写
"""

        return prompt
    def _format_comparison(self, comp: dict) -> str:
        if not comp:
            return '（无足够历史数据对比）'
        parts = []
        ability = comp.get('ability', {})
        if 'hr_trend' in ability:
            t = ability['hr_trend']
            parts.append(f"心率：当前 {t['current']:.0f} vs 历史中位数 {t['history_median']:.0f} bpm，趋势：{t['verdict']}")
        if 'pace_trend' in ability:
            t = ability['pace_trend']
            # 格式化配速为 X分X秒/KM
            current_pace_str = self._format_pace(t['current'])
            history_pace_str = self._format_pace(t['history_median'])
            parts.append(f"配速：当前 {current_pace_str} vs 历史中位数 {history_pace_str}，趋势：{t['verdict']}")
        if 'power_trend' in ability:
            t = ability['power_trend']
            parts.append(f"功率：当前 {t['current']:.0f}W vs 历史中位数 {t['history_median']:.0f}W，趋势：{t['verdict']}")
        economy = comp.get('economy', {})
        if 'vr_trend' in economy:
            t = economy['vr_trend']
            parts.append(f"垂直振幅比：当前 {t['current']:.1f}% vs 历史中位数 {t['history_median']:.1f}%，趋势：{t['verdict']}")
        if 'hr_pace_ratio' in economy:
            t = economy['hr_pace_ratio']
            parts.append(f"效率（(m/h)/bpm）：当前 {t['current']:.2f} vs 历史中位数 {t['history_median']:.2f}，趋势：{t['verdict']}")
        
        # 追加短期状态
        st = comp.get('short_term', {})
        if st and 'message' not in st:
            parts.append(f"短期状态（近{st['window_days']}天 {st['sample_size']} 次同类型）：心率{st['verdict_hr']}，配速{st['verdict_pace']}，效率{st['verdict_efficiency']}")
        
        # 追加长期趋势
        lt = comp.get('long_term', {})
        if lt:
            trend = lt.get('trend', {})
            if 'hr_slope_per_month' in trend:
                parts.append(f"长期趋势（近{lt['window_days']}天）：心率月变化{trend['hr_slope_per_month']:+.1f}bpm，配速月变化{trend['pace_slope_per_month']:+.1f}秒，判定{lt['verdict']}")
            elif lt.get('verdict') == '数据不足':
                parts.append(f"长期趋势（近{lt['window_days']}天）：{lt.get('message') or lt['verdict']}")
        
        # 去年同期对比（无数据时不出现，prompt 里不提示"没数据"）
        yoy = lt.get('yoy', {}) if lt else {}
        if yoy and yoy.get('hr_median') is not None:
            yoy_line = f"去年同期（近{yoy['window_days']}天中位）：心率 {yoy['hr_median']:.0f} bpm"
            if yoy.get('pace_median_sec'):
                yoy_line += f"，配速 {self._format_pace(yoy['pace_median_sec'])}"
            slope_parts = []
            if yoy.get('hr_slope_per_month') is not None:
                slope_parts.append(f"心率月变化{yoy['hr_slope_per_month']:+.1f}bpm")
            if yoy.get('pace_slope_per_month') is not None:
                slope_parts.append(f"配速月变化{yoy['pace_slope_per_month']:+.1f}秒")
            if slope_parts:
                yoy_line += f"（{'，'.join(slope_parts)}）"
            parts.append(yoy_line)
        
        # 追加百分位
        pct = comp.get('percentile', {})
        if pct:
            parts.append(f"历史排名：{pct['rank_label']}，超过{pct['value']:.0f}%的相似跑步")
        
        # 追加预期配速
        exp = comp.get('expected_pace', {})
        if exp:
            diff = exp['diff_sec']
            if diff < -10:
                verdict = f'比预期快 {abs(diff):.0f}秒'
            elif diff > 10:
                verdict = f'比预期慢 {diff:.0f}秒'
            else:
                verdict = '符合预期'
            parts.append(f"预期配速：{self._format_pace(exp['expected_pace_sec'])}，实际{self._format_pace(exp['actual_pace_sec'])}，{verdict}")
        
        # 明确两个关键指标的统计口径，避免 AI 点评自相矛盾
        parts.append(
            "【指标口径说明】预期配速=同类型历史配速中位数；历史排名=按跑步经济性 (m/h)/bpm 的百分位。"
        )
        
        return '\n'.join(parts) if parts else '（历史数据不足）'
    
    def _format_pace(self, pace_seconds: float) -> str:
        """将配速秒数转为 X分X秒/KM 格式"""
        return format_pace_chinese(pace_seconds)
    
    def _format_lap_data(self, laps: dict) -> str:
        """格式化分圈数据为 LLM Prompt 文本段落"""
        if not laps or not laps.get('current'):
            return ''
        
        lines = ['## 分圈数据分析']
        current = laps.get('current', [])
        history_median = laps.get('history_median', [])
        history_p20_pace = laps.get('history_p20_pace', [])
        history_p80_pace = laps.get('history_p80_pace', [])
        sample_size = laps.get('sample_size', 0)
        
        if sample_size > 0:
            baseline_note = laps.get('baseline_note')
            note_str = f'（{baseline_note}）' if baseline_note else ''
            lines.append(f'（对比前 {sample_size} 次同类型跑步{note_str}）')
        
        lines.append('| 圈次 | 配速 | 心率 | 功率 | 历史中位配速 | 历史P20配速 | 历史P80配速 |')
        lines.append('|------|------|------|------|------------|------------|------------|')
        
        for i, lap in enumerate(current):
            lap_num = lap.get('lap', i + 1)
            pace = self._format_pace(lap.get('pace_sec', 0))
            hr = f"{lap.get('avg_hr', 0):.0f}" if lap.get('avg_hr') else '--'
            power = f"{lap.get('avg_power', 0):.0f}W" if lap.get('avg_power') else '--'
            hist = history_median[i] if i < len(history_median) else {}
            hist_pace = self._format_pace(hist.get('pace_sec', 0)) if hist.get('pace_sec', 0) > 0 else '--'
            hist_p20_pace_str = self._format_pace(history_p20_pace[i]) if i < len(history_p20_pace) else '--'
            hist_p80_pace_str = self._format_pace(history_p80_pace[i]) if i < len(history_p80_pace) else '--'
            lines.append(f'| {lap_num}KM | {pace} | {hr} | {power} | {hist_pace} | {hist_p20_pace_str} | {hist_p80_pace_str} |')
        
        # 提示 LLM 解读分圈表现
        lines.append('')
        lines.append('请解读分圈表现：配速是否均匀？心率是否漂移（后半程明显升高）？哪几圈相对历史中位数表现更好/更差？与历史P20-P80区间对比如何？')
        
        return '\n'.join(lines) + '\n'
    
    def _call_api(self, prompt: str) -> tuple:
        """调用 LLM API（使用 config.py 中的配置）
        
        Returns:
            (content, actual_model) 元组
        """
        return self._call_llm(
            prompt,
            api_key=self.api_key,
            model=self.config.get('model'),
            host=self.config.get('host'),
            port=self.config.get('port'),
            use_http=self.config.get('use_http', False),
            path=self.config.get('path'),
            max_tokens=self.config.get('max_tokens', 2000),
            temperature=self.config.get('temperature', 0.7)
        )
    
    @staticmethod
    def _call_llm(prompt: str, api_key: str = None, model: str = '',
                  host: str = '', port: int = None,
                  use_http: bool = False, path: str = '',
                  max_tokens: int = 2000, temperature: float = 0.7) -> str:
        """通用 LLM 调用方法（供 brief_summary 和 _call_api 复用）"""
        import time
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }
        body_dict = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': max_tokens,
            'temperature': temperature,
        }
        # GLM 系列模型默认启用推理（reasoning），会吃掉大量 token
        # 需要显式关闭，否则 content 可能为空
        if 'glm' in model.lower():
            body_dict['thinking'] = {'type': 'disabled'}
        body = json.dumps(body_dict).encode('utf-8')
        
        # 根据 use_http 参数选择 HTTP/HTTPS
        conn_factory = http.client.HTTPConnection if use_http else http.client.HTTPSConnection
        
        max_retries = 6
        for attempt in range(max_retries):
            if port:
                conn = conn_factory(f'{host}:{port}', timeout=240)
            else:
                conn = conn_factory(host, timeout=240)
            try:
                conn.request('POST', path, body=body, headers=headers)
                resp = conn.getresponse()
                data = json.loads(resp.read().decode('utf-8'))
                
                if resp.status == 200:
                    actual_model = data.get('model', model)
                    return data['choices'][0]['message']['content'], actual_model
                else:
                    raise Exception(f"API 错误: {data.get('error', data)}")
            except Exception as e:
                if attempt < max_retries - 1:
                    sleep_time = min(5 * (2 ** attempt), 60)  # 递增退避: 5,10,20,40,60
                    logger.warning(f"LLM 调用失败，第 {attempt+1}/{max_retries} 次重试 ({sleep_time}s 后): {e}")
                    time.sleep(sleep_time)
                else:
                    raise
            finally:
                conn.close()
    
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