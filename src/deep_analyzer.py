"""跑步深度分析器"""

import http.client
import json
import logging
import os
from typing import Dict, List

import pandas as pd

from src.config import DEFAULT_CONFIG, HR_ZONE_PERCENTAGES
from src.classifier import HeartRateClassifier

logger = logging.getLogger("PowerFun.deep_analyzer")


class DeepRunAnalyzer:
    """跑步深度分析器"""

    # 心率默认值（从 DEFAULT_CONFIG 统一读取）
    DEFAULT_MAX_HR = DEFAULT_CONFIG.get('max_hr')
    DEFAULT_RESTING_HR = DEFAULT_CONFIG.get('resting_hr')

    def __init__(self, df_all: pd.DataFrame, target_date=None, max_hr=None, resting_hr=None,
                 lap_data: dict = None):
        """
        Args:
            df_all: 完整 DataFrame（包含所有跑步记录，用于对比分析）
            target_date: 对比基准日期，取该日期之前的历史数据
            max_hr: 最大心率（默认从 DEFAULT_CONFIG 读取）
            resting_hr: 静息心率（默认从 DEFAULT_CONFIG 读取）
            lap_data: 分圈数据 dict，格式见需求文档（current/history_avg/history_max_pace/history_min_pace/sample_size）
        """
        self.df_all = df_all
        self.target_date = target_date
        self.max_hr = max_hr if max_hr is not None else self.DEFAULT_MAX_HR
        self.resting_hr = resting_hr if resting_hr is not None else self.DEFAULT_RESTING_HR
        self.lap_data = lap_data or {}
    
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
        result['brief_summary'] = self._generate_brief_summary(row)
        result['hr_zone_ranges'] = self._get_hr_zone_ranges(row)
        # 分圈分析结果
        result['laps'] = self.lap_data
        return result
    
    def _generate_brief_summary(self, row: pd.Series) -> str:
        """生成约100字的简要总结"""
        try:
            # 获取主要数据
            date = str(row.get('date', ''))[:10]
            category_name = row.get('category_name', '跑步')
            distance = row.get('distance', 0)
            duration_min = row.get('duration_min', 0)
            avg_pace_fmt = row.get('avg_pace_fmt', '--')
            avg_hr = row.get('avg_hr', 0)
            
            # 获取心率区间主占比
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
            
            # 构建提示词，明确要求生成100字左右的总结
            prompt = f"""请用100字左右的中文总结这次跑步：{date} {category_name} {distance:.1f}km {duration_min:.0f}分钟，
            配速{avg_pace_fmt}/km，平均心率{avg_hr:.0f}，主训练区间{dominant_zone}。
            请突出训练重点和特点，语言亲切自然，不少于80字。"""
            
            # 调用 LLM 生成简要总结（复用 LLMReportGenerator._call_llm）
            llm_gen = LLMReportGenerator()
            if llm_gen.api_key:
                result = llm_gen._call_llm(prompt, api_key=llm_gen.api_key, max_tokens=2000, temperature=0.8)
                if result:
                    return result.strip()
            return ""
        except Exception as e:
            logger.error(f"Brief summary generation failed: {e}")
            return ""
    
    def _get_hr_zone_ranges(self, row: pd.Series) -> dict:
        """获取心率区间范围（bpm）"""
        max_hr = row.get('max_hr') if pd.notna(row.get('max_hr')) else self.max_hr
        resting_hr = row.get('resting_hr') if pd.notna(row.get('resting_hr')) else self.resting_hr
        
        # 使用 HR_ZONE_PERCENTAGES 定义（Karvonen HRR 法固定百分比）
        HRR = max_hr - resting_hr
        result = {}
        for zone_key, zone_info in HR_ZONE_PERCENTAGES.items():
            min_hr = int(resting_hr + HRR * zone_info['min_pct'])
            max_hr_val = int(resting_hr + HRR * zone_info['max_pct'])
            result[zone_key] = {
                'label': zone_info['name'],
                'min_hr': min_hr,
                'max_hr': max_hr_val
            }
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
        """对比分析：最近5次同类型跑步"""
        df = self.df_all.copy()
        
        # 同类筛选
        category = row.get('category', '')
        if category and 'category' in df.columns:
            df_same = df[df['category'] == category]
        else:
            df_same = df
        
        # 排除本次
        activity_id = row.get('activity_id')
        if activity_id:
            df_same = df_same[df_same['activity_id'] != activity_id]
        elif self.target_date is not None:
            df_same = df_same[df_same['date'] != pd.Timestamp(self.target_date)]
        
        # 按日期排序，取最近5次
        if self.target_date is not None:
            target_ts = pd.Timestamp(self.target_date)
            df_same = df_same[df_same['date'] < target_ts]
        df_same = df_same.sort_values('date', ascending=False).head(5)
        
        if len(df_same) < 1:
            return {
                'sample_size': len(df_same),
                'message': f'最近无同类型跑步记录，无法对比',
            }
        
        # 3.1 能力变化
        dist = row.get('distance', 0)
        dist_tolerance = dist * 0.2  # ±20% 距离容忍
        df_near = df_same[(df_same['distance'] >= dist * 0.8) & (df_same['distance'] <= dist * 1.2)]
        
        result = {
            'sample_size': len(df_same),
            'ability': {},
            'economy': {},
        }
        
        # 心率变化
        if 'avg_hr' in df_same.columns and df_same['avg_hr'].notna().any():
            hist_avg_hr = df_same['avg_hr'].mean()
            curr_hr = row.get('avg_hr', 0)
            hr_diff = curr_hr - hist_avg_hr if hist_avg_hr > 0 else 0
            result['ability']['hr_trend'] = {
                'current': round(curr_hr, 0),  # 取整
                'history_avg': round(hist_avg_hr, 0),  # 取整
                'diff': round(hr_diff, 0),  # 取整
                'verdict': '更轻松' if hr_diff < -3 else ('更累' if hr_diff > 3 else '持平'),
            }
        
        # 配速变化
        if 'avg_pace_sec' in df_same.columns and df_same['avg_pace_sec'].notna().any():
            hist_pace = df_same['avg_pace_sec'].mean()
            curr_pace = row.get('avg_pace_sec', 0)
            pace_diff = curr_pace - hist_pace
            result['ability']['pace_trend'] = {
                'current': round(curr_pace, 0),  # 取整
                'history_avg': round(hist_pace, 0),  # 取整
                'diff': round(pace_diff, 0),  # 取整
                'verdict': '更快' if pace_diff < -5 else ('更慢' if pace_diff > 5 else '持平'),
            }
        
        # 功率变化
        if 'avg_power' in df_same.columns and df_same['avg_power'].notna().any():
            hist_power = df_same['avg_power'].mean()
            curr_power = row.get('avg_power', 0)
            power_diff = curr_power - hist_power
            result['ability']['power_trend'] = {
                'current': round(curr_power, 0),  # 取整
                'history_avg': round(hist_power, 0),  # 取整
                'diff': round(power_diff, 0),  # 取整
                'verdict': '更高' if power_diff > 10 else ('更低' if power_diff < -10 else '持平'),
            }
        
        # 3.2 跑步经济性
        if 'vertical_ratio' in df_same.columns and df_same['vertical_ratio'].notna().any():
            hist_vr = df_same['vertical_ratio'].mean()
            curr_vr = row.get('vertical_ratio', 0)
            vr_diff = curr_vr - hist_vr
            result['economy']['vr_trend'] = {
                'current': round(curr_vr, 1),
                'history_avg': round(hist_vr, 1),
                'diff': round(vr_diff, 1),
                'verdict': '更经济' if vr_diff < -0.5 else ('更费力' if vr_diff > 0.5 else '持平'),
            }
        
        if 'cadence' in df_same.columns and df_same['cadence'].notna().any():
            hist_cad = df_same['cadence'].mean()
            curr_cad = row.get('cadence', 0)
            cad_diff = curr_cad - hist_cad
            result['economy']['cadence_trend'] = {
                'current': round(curr_cad, 0),  # 取整
                'history_avg': round(hist_cad, 0),  # 取整
                'diff': round(cad_diff, 0),  # 取整
                'verdict': '更稳定' if abs(cad_diff) < 3 else ('波动较大' if abs(cad_diff) > 8 else '基本稳定'),
            }
        
        # 心率/配速比值
        if ('avg_hr' in df_same.columns and 'avg_pace_sec' in df_same.columns 
            and df_same['avg_hr'].notna().any() and df_same['avg_pace_sec'].notna().any()):
            df_valid = df_same[(df_same['avg_hr'] > 0) & (df_same['avg_pace_sec'] > 0)].copy()
            if len(df_valid) > 0:
                df_valid['hr_pace_ratio'] = df_valid['avg_hr'] / df_valid['avg_pace_sec']
                hist_ratio = df_valid['hr_pace_ratio'].mean()
                curr_hr = row.get('avg_hr', 0)
                curr_pace = row.get('avg_pace_sec', 0)
                curr_ratio = curr_hr / curr_pace if curr_pace > 0 else 0
                ratio_diff = curr_ratio - hist_ratio
                result['economy']['hr_pace_ratio'] = {
                    'current': round(curr_ratio, 2),
                    'history_avg': round(hist_ratio, 2),
                    'diff': round(ratio_diff, 2),
                    'verdict': '更经济' if ratio_diff < -0.1 else ('更费力' if ratio_diff > 0.1 else '持平'),
                }
        
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
            if t['diff'] < -0.1:
                findings.append(f"心率/配速比值降低，跑步效率提升")
        
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
                'history_avg': [],
                'history_max_pace': [],
                'history_min_pace': [],
                'sample_size': 0,
            }
        
        # 对每个圈序号，计算历史均值/最高/最低配速
        max_laps = len(current)
        history_avg = []
        history_max_pace = []
        history_min_pace = []
        
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
            
            avg_pace = sum(paces) / len(paces) if paces else 0
            avg_hr = sum(hrs) / len(hrs) if hrs else None
            
            history_avg.append({
                'lap': lap_idx,
                'pace_sec': round(avg_pace, 2) if avg_pace else 0,
                'avg_hr': round(avg_hr, 0) if avg_hr else None,
            })
            
            # 最高配速 = 最慢（秒数最大），最低配速 = 最快（秒数最小）
            history_max_pace.append(round(max(paces), 2) if paces else 0)
            history_min_pace.append(round(min(paces), 2) if paces else 0)
        
        return {
            'current': current,
            'history_avg': history_avg,
            'history_max_pace': history_max_pace,
            'history_min_pace': history_min_pace,
            'sample_size': len(recent_laps),
        }


class LLMReportGenerator:
    """LLM 文字报告生成器"""
    
    API_KEY_ENV_VARS = [
        'OPENCLAW_ALIYUN_API_KEY',
        'OPENCLAW_BAILIAN_API_KEY',
    ]
    API_MODEL = 'qwen3.6-plus'
    API_HOST = 'dashscope.aliyuncs.com'
    API_PATH = '/compatible-mode/v1/chat/completions'
    
    def __init__(self):
        self.api_key = self._load_api_key()
    
    def _load_api_key(self) -> str:
        for env_var in self.API_KEY_ENV_VARS:
            key = os.environ.get(env_var, '')
            if key:
                return key
        return ''
    
    def generate(self, analysis_data: dict) -> str:
        """基于结构化分析数据生成 LLM 文字报告
        
        Args:
            analysis_data: DeepRunAnalyzer.analyze() 返回的结果
            
        Returns:
            LLM 生成的文字报告（Markdown 格式）
        """
        if not self.api_key:
            return "（API Key 未配置，跳过 AI 分析）"
        
        prompt = self._build_prompt(analysis_data)
        
        try:
            return self._call_api(prompt)
        except Exception as e:
            logger.error(f"LLM API 调用失败: {e}")
            return f"（AI 分析调用失败: {e}）"
    
    def _build_prompt(self, data: dict) -> str:
        """构建 LLM Prompt"""
        raw = data.get('raw_data', {})
        summary = data.get('summary', {})
        intensity = data.get('intensity', {})
        efficiency = data.get('efficiency', {})
        comparison = data.get('comparison', {})
        findings = data.get('findings', [])
        laps = data.get('laps', {})
        
        # 构建分圈数据段落
        lap_section = self._format_lap_data(laps)
        
        return f"""你是一位专业的跑步教练和运动科学家。请基于以下数据，生成一份通俗易懂的跑步分析报告。

## 跑步基本信息
- 日期：{raw.get('date', '')}
- 类型：{raw.get('category_name', '')}
- 距离：{raw.get('distance_km', 0):.2f} km
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
- 步频：{raw.get('cadence', 0)} spm（{efficiency.get('cadence_eval', '')}）
- 步幅：{raw.get('stride_length_cm', 0):.1f} cm
- 垂直振幅比：{raw.get('vertical_ratio_pct', 0):.1f}%（{efficiency.get('vertical_ratio_eval', '')}）
- 触地时间：{raw.get('ground_contact_ms', 0):.1f} ms（{efficiency.get('ground_contact_eval', '')}）

## 历史对比
{self._format_comparison(comparison)}
{lap_section}
## 关键发现
{chr(10).join(f'- {f}' for f in findings)}

请生成以下内容的分析报告：

1. 用一段话总结本次跑步（2-3 句，通俗易懂，有温度）
2. 强度和负荷解读（心率、功率、训练效果的综合评价）
3. 技术效率解读（步频、步幅、垂直振幅、触地时间的综合分析）
4. 能力变化趋势（基于历史对比的解读）
5. 分圈表现解读（配速是否均匀、有无心率漂移、每圈与历史对比）
6. 具体的改进建议（3-5 条，可操作的训练建议）

要求：
- 语言风格：像一位经验丰富的教练在和你聊天
- 避免堆砌数字，重点解读趋势和意义
- 建议要具体可执行，不要空话
- 总字数控制在 1200 字以内
"""
    
    def _format_comparison(self, comp: dict) -> str:
        if not comp:
            return '（无足够历史数据对比）'
        parts = []
        ability = comp.get('ability', {})
        if 'hr_trend' in ability:
            t = ability['hr_trend']
            parts.append(f"心率对比最近同类型：当前 {t['current']:.0f} vs 历史 {t['history_avg']:.0f} bpm，趋势：{t['verdict']}")
        if 'pace_trend' in ability:
            t = ability['pace_trend']
            # 格式化配速为 X分X秒/KM
            current_pace_str = self._format_pace(t['current'])
            history_pace_str = self._format_pace(t['history_avg'])
            parts.append(f"配速对比：当前 {current_pace_str} vs 历史 {history_pace_str}，趋势：{t['verdict']}")
        if 'power_trend' in ability:
            t = ability['power_trend']
            parts.append(f"功率对比：当前 {t['current']:.0f}W vs 历史 {t['history_avg']:.0f}W，趋势：{t['verdict']}")
        economy = comp.get('economy', {})
        if 'vr_trend' in economy:
            t = economy['vr_trend']
            parts.append(f"垂直振幅比：当前 {t['current']:.1f}% vs 历史 {t['history_avg']:.1f}%，趋势：{t['verdict']}")
        if 'hr_pace_ratio' in economy:
            t = economy['hr_pace_ratio']
            parts.append(f"跑步经济性（心率/配速比）：当前 {t['current']:.2f} vs 历史 {t['history_avg']:.2f}，趋势：{t['verdict']}")
        return '\n'.join(parts) if parts else '（历史数据不足）'
    
    def _format_pace(self, pace_seconds: float) -> str:
        """将配速秒数转为 X分X秒/KM 格式"""
        if pace_seconds <= 0:
            return "--"
        mins = int(pace_seconds // 60)
        secs = int(pace_seconds % 60)
        return f"{mins}分{secs:02d}秒/KM"
    
    def _format_lap_data(self, laps: dict) -> str:
        """格式化分圈数据为 LLM Prompt 文本段落"""
        if not laps or not laps.get('current'):
            return ''
        
        lines = ['## 分圈数据分析']
        current = laps.get('current', [])
        history_avg = laps.get('history_avg', [])
        sample_size = laps.get('sample_size', 0)
        
        if sample_size > 0:
            lines.append(f'（对比前 {sample_size} 次同类型跑步）')
        
        lines.append('| 圈次 | 配速 | 心率 | 功率 | 历史均配速 |')
        lines.append('|------|------|------|------|------------|')
        
        for i, lap in enumerate(current):
            lap_num = lap.get('lap', i + 1)
            pace = self._format_pace(lap.get('pace_sec', 0))
            hr = f"{lap.get('avg_hr', 0):.0f}" if lap.get('avg_hr') else '--'
            power = f"{lap.get('avg_power', 0):.0f}W" if lap.get('avg_power') else '--'
            hist = history_avg[i] if i < len(history_avg) else {}
            hist_pace = self._format_pace(hist.get('pace_sec', 0)) if hist.get('pace_sec', 0) > 0 else '--'
            lines.append(f'| {lap_num}KM | {pace} | {hr} | {power} | {hist_pace} |')
        
        # 提示 LLM 解读分圈表现
        lines.append('')
        lines.append('请解读分圈表现：配速是否均匀？心率是否漂移（后半程明显升高）？哪几圈相对历史表现更好/更差？')
        
        return '\n'.join(lines) + '\n'
    
    def _call_api(self, prompt: str) -> str:
        """调用 Bailian API（默认参数）"""
        return self._call_llm(prompt, api_key=self.api_key, max_tokens=2000, temperature=0.7)
    
    @staticmethod
    def _call_llm(prompt: str, api_key: str = None, max_tokens: int = 2000,
                  temperature: float = 0.7) -> str:
        """通用 LLM 调用方法（供 brief_summary 和 _call_api 复用）"""
        import time
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }
        body = json.dumps({
            'model': 'qwen3.6-plus',
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': max_tokens,
            'temperature': temperature,
        }).encode('utf-8')
        
        for attempt in range(3):
            conn = http.client.HTTPSConnection('dashscope.aliyuncs.com', timeout=120)
            try:
                conn.request('POST', '/compatible-mode/v1/chat/completions', body=body, headers=headers)
                resp = conn.getresponse()
                data = json.loads(resp.read().decode('utf-8'))
                
                if resp.status == 200:
                    return data['choices'][0]['message']['content']
                else:
                    raise Exception(f"API 错误: {data.get('error', data)}")
            except Exception as e:
                if attempt < 2:
                    time.sleep(3)
                else:
                    raise
            finally:
                conn.close()