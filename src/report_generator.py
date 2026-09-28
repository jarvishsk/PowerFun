"""
报告生成器模块
使用Jinja2模板生成自包含HTML报告
"""

import html
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
import logging

from src.config import INSIGHTS_CONFIG, HR_ZONE_PERCENTAGES, USER_CONFIG
from src.utils import load_version

TITLE_MAX_LEN = 25

try:
    from jinja2 import Environment, BaseLoader, select_autoescape
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False

logger = logging.getLogger(__name__)


class NumpyEncoder(json.JSONEncoder):
    """处理numpy和pandas类型的JSON编码器"""
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, pd.Timestamp):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(obj, datetime):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        if pd.isna(obj):
            return None
        return super().default(obj)


class ReportGenerator:
    """HTML报告生成器 - 使用Jinja2模板"""

    def __init__(self, template_dir: Optional[str] = None):
        self.template_dir = template_dir or os.path.join(
            os.path.dirname(__file__), '..', 'templates'
        )

    def generate_insights(self, df: pd.DataFrame, stats: Dict) -> List[Dict]:
        """生成训练结论与下一步（v2：固定 4 张维度卡，8/12 周降级保留）"""
        insights = []
        cfg = INSIGHTS_CONFIG

        if 'date' not in df.columns or df.empty:
            insights.append({
                'type': 'info', 'icon': '📊', 'title': '数据不足',
                'message': '暂无有效跑步记录，无法生成训练建议。',
                'metric': 'total_runs', 'value': 0
            })
            return insights

        df_dates = pd.to_datetime(df['date'])
        now = datetime.now()

        # 窗口选择：优先 4 周；样本不足 3 次时降级到 8 周，仍不足降级到 12 周
        window_days = 28
        recent_cutoff = now - timedelta(days=window_days)
        recent_df = df[df_dates >= recent_cutoff]
        sample_low = False
        if len(recent_df) < 3:
            window_days = 56
            recent_cutoff = now - timedelta(days=window_days)
            recent_df = df[df_dates >= recent_cutoff]
            sample_low = True
            if len(recent_df) < 3:
                window_days = 84
                recent_cutoff = now - timedelta(days=window_days)
                recent_df = df[df_dates >= recent_cutoff]
                sample_low = True

        window_weeks = window_days / 7
        recent_count = len(recent_df)
        prev_start = now - timedelta(days=window_days * 2)
        prev_end = now - timedelta(days=window_days)
        prev_df = df[(df_dates >= prev_start) & (df_dates < prev_end)]

        if sample_low:
            insights.append({
                'type': 'info', 'icon': '📊', 'title': '样本说明',
                'message': f'近 4 周跑步记录不足 3 次，已扩展至近 {window_weeks:.0f} 周，趋势仅供参考。',
                'metric': 'window_weeks', 'value': int(window_weeks),
                'target': '≥3 次/4周', 'action': '保持规律记录后重新评估'
            })

        # 固定 4 张维度卡
        insights.append(self._build_intensity_card(recent_df, df, window_weeks, cfg))
        insights.append(self._build_volume_card(recent_df, prev_df, window_weeks, cfg))
        insights.append(self._build_efficiency_card(recent_df, prev_df, cfg))
        insights.append(self._build_continuity_card(df, recent_df, window_weeks, cfg))

        return insights

    # ---------- v2 固定维度卡辅助方法 ----------

    def _build_intensity_card(self, recent_df: pd.DataFrame, df: pd.DataFrame,
                              window_weeks: float, cfg: Dict) -> Dict:
        """卡 1：🏗️ 强度结构（Z1 占比三档 + Z5 过载，合并为一张卡）"""
        recent_count = len(recent_df)
        if 'hr_zone' not in df.columns or recent_count == 0:
            return {
                'type': 'info', 'icon': '🏗️', 'title': '强度结构',
                'message': '暂无心率区间数据，强度结构待积累后评估。',
                'metric': 'z1_pct', 'value': None,
                'target': '30-50%', 'action': '继续记录并佩戴心率设备'
            }

        z1_count = (recent_df['hr_zone'] == 'Z1-有氧基础').sum()
        z5_count = (recent_df['hr_zone'] == 'Z5-最大强度').sum()
        z1_pct = z1_count / recent_count
        z5_pct = z5_count / recent_count
        ideal_low = cfg['z1_low_pct'] * 100
        ideal_high = cfg['z1_high_pct'] * 100

        # Z1 判定
        z1_card = None
        if z1_pct < cfg['z1_low_pct']:
            z1_upper = (
                USER_CONFIG['resting_hr']
                + HR_ZONE_PERCENTAGES['Z1']['max_pct']
                * (USER_CONFIG['max_hr'] - USER_CONFIG['resting_hr'])
            )
            weekly_runs = recent_count / window_weeks
            target_easy = max(1, int(round(weekly_runs * 0.6))) if weekly_runs > 0 else 2
            easy_range = f"{target_easy}-{target_easy + 1}" if weekly_runs >= 3 else f"{target_easy}"

            # 全期各月 Z1 占比中位数（用于文案）
            overall_z1_median = None
            if 'year_month' in df.columns:
                monthly_total = df.groupby('year_month').size()
                monthly_z1 = df[df['hr_zone'] == 'Z1-有氧基础'].groupby('year_month').size()
                monthly_z1_pct = (monthly_z1 / monthly_total).dropna()
                if not monthly_z1_pct.empty:
                    overall_z1_median = monthly_z1_pct.median() * 100

            msg = (
                f"近 {window_weeks:.0f} 周 Z1 占比 {z1_pct * 100:.1f}%"
                f"（低于 {ideal_low:.0f}% 下限"
            )
            if overall_z1_median is not None:
                msg += f"，全期中位数 {overall_z1_median:.0f}%"
            msg += (
                f"）。建议下周 {easy_range} 次跑步控制心率 <{z1_upper:.0f} bpm，"
                f"每次 45-60 分钟，补有氧基础。"
            )
            z1_card = {
                'type': 'warning', 'icon': '🏗️', 'title': '有氧基础不足',
                'message': msg,
                'metric': 'z1_pct', 'value': round(z1_pct * 100, 1),
                'target': f'{ideal_low:.0f}-{ideal_high:.0f}%',
                'action': f'下周安排 {easy_range} 次轻松跑，心率 <{z1_upper:.0f} bpm'
            }
        elif z1_pct <= cfg['z1_high_pct']:
            z1_card = {
                'type': 'info', 'icon': '🏗️', 'title': '强度结构合理',
                'message': (
                    f"近 {window_weeks:.0f} 周 Z1 占比 {z1_pct * 100:.1f}%，"
                    f"处于 {ideal_low:.0f}-{ideal_high:.0f}% 理想区间，强度结构合理。"
                    f"可维持当前轻松跑比例。"
                ),
                'metric': 'z1_pct', 'value': round(z1_pct * 100, 1),
                'target': f'{ideal_low:.0f}-{ideal_high:.0f}%',
                'action': '保持当前轻松跑比例'
            }
        else:
            # Z1 > 50%，统计 Z2+ 次数（老板实际强度课多落在 Z2，按 Z2+ 口径统计）
            intensity_count = (
                recent_df['hr_zone'].isin([
                    'Z2-有氧耐力', 'Z3-乳酸阈值', 'Z4-无氧耐力', 'Z5-最大强度'
                ]).sum()
            )
            if intensity_count <= 1:
                z1_card = {
                    'type': 'tip', 'icon': '🏗️', 'title': '强度刺激不足',
                    'message': (
                        f"近 {window_weeks:.0f} 周 Z1 占比 {z1_pct * 100:.1f}%，"
                        f"仅 {int(intensity_count)} 次强度刺激。"
                        f"若有比赛目标，建议每周安排 1 次节奏跑或间歇。"
                    ),
                    'metric': 'z1_pct', 'value': round(z1_pct * 100, 1),
                    'target': f'{ideal_low:.0f}-{ideal_high:.0f}%',
                    'action': '每周安排 1 次节奏跑或间歇训练'
                }
            else:
                z1_card = {
                    'type': 'info', 'icon': '🏗️', 'title': '轻松跑为主，强度点缀合理',
                    'message': (
                        f"近 {window_weeks:.0f} 周 Z1 占比 {z1_pct * 100:.1f}%，"
                        f"强度刺激 {int(intensity_count)} 次。"
                        f"轻松跑为主、强度点缀，结构合理。"
                    ),
                    'metric': 'z1_pct', 'value': round(z1_pct * 100, 1),
                    'target': f'{ideal_low:.0f}-{ideal_high:.0f}%',
                    'action': '保持当前强度安排'
                }

        # Z5 过载判定（独立但合并到同一张卡）
        if z5_pct > cfg['z5_overload_pct']:
            z5_card = {
                'type': 'warning', 'icon': '🏗️', 'title': '高强度过多',
                'message': (
                    f"近 {window_weeks:.0f} 周 Z5 占比 {z5_pct * 100:.1f}%"
                    f"（>{cfg['z5_overload_pct'] * 100:.0f}%），高强度过多。"
                    f"建议下周最多 1 次强度课，其余压低心率。"
                ),
                'metric': 'z5_pct', 'value': round(z5_pct * 100, 1),
                'target': f"<{cfg['z5_overload_pct'] * 100:.0f}%",
                'action': '下周最多 1 次强度课，其余压低心率'
            }
            z1_card = self._merge_priority_card(z1_card, z5_card)

        return z1_card

    def _build_volume_card(self, recent_df: pd.DataFrame, prev_df: pd.DataFrame,
                           window_weeks: float, cfg: Dict) -> Dict:
        """卡 2：📦 训练负荷（跑量环比 + 周均）"""
        recent_count = len(recent_df)
        recent_distance = recent_df['distance'].sum() if 'distance' in recent_df.columns else 0
        prev_distance = prev_df['distance'].sum() if 'distance' in prev_df.columns and not prev_df.empty else 0
        weekly_avg = recent_distance / window_weeks

        if recent_count == 0:
            return {
                'type': 'info', 'icon': '📦', 'title': '负荷基线建立中',
                'message': '近窗口无跑步记录，跑量基线待建立。',
                'metric': 'volume_change_pct', 'value': None,
                'target': '稳定负荷', 'action': '恢复规律训练后重新评估'
            }

        if prev_distance == 0:
            return {
                'type': 'info', 'icon': '📦', 'title': '负荷基线建立中',
                'message': (
                    f"近 {window_weeks:.0f} 周跑量 {recent_distance:.1f} km（周均 {weekly_avg:.1f} km），"
                    f"前一窗口无数据，正在建立负荷基线。"
                ),
                'metric': 'recent_distance', 'value': round(recent_distance, 1),
                'target': '稳定负荷', 'action': '继续规律训练以形成对比基线'
            }

        change_pct = (recent_distance - prev_distance) / prev_distance * 100
        threshold = cfg['monthly_volume_change_threshold']

        if change_pct > threshold:
            target_low = prev_distance * 1.1
            target_high = prev_distance * 1.2
            return {
                'type': 'warning', 'icon': '📦', 'title': '跑量增长过快',
                'message': (
                    f"近 {window_weeks:.0f} 周跑量 {recent_distance:.1f} km（周均 {weekly_avg:.1f} km），"
                    f"环比增加 {change_pct:.1f}%（>{threshold:.0f}% 阈值）。"
                    f"下周建议回落到 {target_low:.1f}-{target_high:.1f} km，避免受伤。"
                ),
                'metric': 'volume_change_pct', 'value': round(change_pct, 1),
                'target': f"±{threshold:.0f}%",
                'action': f'下周跑量控制在 {target_low:.1f}-{target_high:.1f} km'
            }
        elif change_pct < -threshold:
            return {
                'type': 'tip', 'icon': '📦', 'title': '跑量下降',
                'message': (
                    f"近 {window_weeks:.0f} 周跑量 {recent_distance:.1f} km（周均 {weekly_avg:.1f} km），"
                    f"环比下降 {abs(change_pct):.1f}%（>{threshold:.0f}% 阈值）。"
                    f"建议逐步恢复到 {prev_distance * 0.9:.1f}-{prev_distance:.1f} km。"
                ),
                'metric': 'volume_change_pct', 'value': round(change_pct, 1),
                'target': f"±{threshold:.0f}%",
                'action': f'下周跑量逐步恢复到 {prev_distance * 0.9:.1f}-{prev_distance:.1f} km'
            }
        else:
            return {
                'type': 'info', 'icon': '📦', 'title': '负荷稳定',
                'message': (
                    f"近 {window_weeks:.0f} 周跑量 {recent_distance:.1f} km（周均 {weekly_avg:.1f} km），"
                    f"环比 {change_pct:+.1f}%，负荷稳定。"
                ),
                'metric': 'volume_change_pct', 'value': round(change_pct, 1),
                'target': f"±{threshold:.0f}%",
                'action': '保持当前跑量节奏'
            }

    def _build_efficiency_card(self, recent_df: pd.DataFrame, prev_df: pd.DataFrame,
                               cfg: Dict) -> Dict:
        """卡 3：💓 有氧效率（beats/km：低 = 进步）"""
        if 'avg_hr' not in recent_df.columns or 'avg_pace_sec' not in recent_df.columns:
            return {
                'type': 'info', 'icon': '💓', 'title': '有氧效率',
                'message': '缺少心率或配速数据，有氧效率暂无法评估。',
                'metric': 'beats_per_km', 'value': None,
                'target': '逐步降低', 'action': '佩戴心率设备并记录配速'
            }

        def _valid_beats(df):
            mask = (df['avg_hr'] > 0) & (df['avg_pace_sec'] > 0) & df['avg_hr'].notna() & df['avg_pace_sec'].notna()
            return df[mask].copy()

        recent_valid = _valid_beats(recent_df)
        prev_valid = _valid_beats(prev_df)

        if len(recent_valid) < 3 or len(prev_valid) < 3:
            return {
                'type': 'info', 'icon': '💓', 'title': '效率基线积累中',
                'message': (
                    f"有效效率样本不足（近窗口 {len(recent_valid)} 次，前窗口 {len(prev_valid)} 次），"
                    f"需前后窗口均 ≥3 次方可判定趋势。"
                ),
                'metric': 'beats_per_km', 'value': None,
                'target': '≥3 次/窗口', 'action': '保持规律记录，待基线稳定后评估'
            }

        recent_valid['beats_per_km'] = recent_valid['avg_hr'] * (recent_valid['avg_pace_sec'] / 60.0)
        prev_valid['beats_per_km'] = prev_valid['avg_hr'] * (prev_valid['avg_pace_sec'] / 60.0)

        recent_beats = recent_valid['beats_per_km'].mean()
        prev_beats = prev_valid['beats_per_km'].mean()
        change_pct = (recent_beats - prev_beats) / prev_beats * 100 if prev_beats else 0

        if change_pct <= -2.0:
            return {
                'type': 'info', 'icon': '💓', 'title': '有氧效率提升',
                'message': (
                    f"心率成本从 {prev_beats:.0f} 降至 {recent_beats:.0f} beats/km"
                    f"（{change_pct:.1f}%），同等配速下心率更低，有氧效率在进步。"
                ),
                'metric': 'beats_per_km', 'value': round(recent_beats, 0),
                'target': '持续降低', 'action': '保持当前有氧训练节奏'
            }
        elif change_pct >= 2.0:
            return {
                'type': 'tip', 'icon': '💓', 'title': '有氧效率回落',
                'message': (
                    f"心率成本从 {prev_beats:.0f} 升至 {recent_beats:.0f} beats/km"
                    f"（+{change_pct:.1f}%），可能与气温、疲劳或状态有关，建议观察。"
                ),
                'metric': 'beats_per_km', 'value': round(recent_beats, 0),
                'target': '观察变化', 'action': '关注睡眠、疲劳和气温变化'
            }
        else:
            return {
                'type': 'info', 'icon': '💓', 'title': '有氧效率平稳',
                'message': (
                    f"心率成本 {prev_beats:.0f} → {recent_beats:.0f} beats/km"
                    f"（{change_pct:+.1f}%），变化在 ±2% 以内，有氧效率平稳。"
                ),
                'metric': 'beats_per_km', 'value': round(recent_beats, 0),
                'target': '保持平稳', 'action': '维持当前训练强度与恢复节奏'
            }

    def _build_continuity_card(self, df: pd.DataFrame, recent_df: pd.DataFrame,
                               window_weeks: float, cfg: Dict) -> Dict:
        """卡 4：🔄 训练连续性（周均次数 + 空窗期）"""
        df_dates = pd.to_datetime(df['date'])
        now = datetime.now()
        last_run = df_dates.max()
        gap = (now - last_run).days
        recent_count = len(recent_df)
        weekly_avg = recent_count / window_weeks if window_weeks > 0 else 0

        if gap > cfg['rest_gap_days']:
            return {
                'type': 'warning', 'icon': '🔄', 'title': '训练空窗期',
                'message': (
                    f"最近 {gap} 天无跑步记录，训练连续性受影响。"
                    f"建议 48 小时内安排一次 30 分钟轻松跑恢复节奏。"
                ),
                'metric': 'rest_gap_days', 'value': int(gap),
                'target': f"≤{cfg['rest_gap_days']} 天",
                'action': '48 小时内安排一次 30 分钟轻松跑'
            }

        if weekly_avg >= 3:
            title = '训练规律'
            msg = (
                f"近 {window_weeks:.0f} 周 {recent_count} 次（周均 {weekly_avg:.1f} 次），训练规律。"
            )
            action = '保持当前训练频率'
        elif weekly_avg >= 2:
            title = '训练基本规律'
            msg = (
                f"近 {window_weeks:.0f} 周 {recent_count} 次（周均 {weekly_avg:.1f} 次），训练基本规律。"
            )
            action = '保持当前训练频率'
        else:
            title = '频率偏低'
            msg = (
                f"近 {window_weeks:.0f} 周 {recent_count} 次（周均 {weekly_avg:.1f} 次），"
                f"频率偏低。建议提升到每周 3 次。"
            )
            action = '逐步提升到每周 3 次训练'

        return {
            'type': 'info' if weekly_avg >= 2 else 'tip',
            'icon': '🔄', 'title': title,
            'message': msg,
            'metric': 'weekly_runs', 'value': round(weekly_avg, 1),
            'target': '≥3 次/周', 'action': action
        }

    def _merge_priority_card(self, base: Dict, override: Dict) -> Dict:
        """合并同维度提示：优先级 warning > tip > info，同优先级合并文案"""
        priority = {'info': 0, 'tip': 1, 'warning': 2}
        base_p = priority.get(base.get('type'), 0)
        override_p = priority.get(override.get('type'), 0)

        if override_p > base_p:
            return override
        if override_p < base_p:
            return base

        # 同优先级：保留 base 标题，合并 message 与 action
        merged = dict(base)
        merged['message'] = f"{base.get('message', '')} {override.get('message', '')}".strip()
        actions = [base.get('action', ''), override.get('action', '')]
        merged['action'] = '；'.join([a for a in actions if a])
        return merged

    def _prepare_table_data(self, df: pd.DataFrame, analysis_dir: str = None) -> List[Dict]:
        """准备表格数据"""
        # 扫描深析报告文件
        available_links = set()
        if analysis_dir and os.path.isdir(analysis_dir):
            for fname in os.listdir(analysis_dir):
                if (fname.startswith('run_analysis_') or fname.startswith('深度分析报告_')) and fname.endswith('.html'):
                    available_links.add(fname)

        records = []
        for idx, row in df.iterrows():
            record = {
                'date': row['date'].strftime('%Y-%m-%d') if pd.notna(row.get('date')) else '--',
                'title': (row.get('title') or '--')[:TITLE_MAX_LEN],  # 截断为最多25个字符
                'category': row.get('category_name') or '--',
                'category_color': row.get('category_color', '#999'),
                'distance': f"{row['distance']:.2f}" if pd.notna(row.get('distance')) else '--',
                'pace': row.get('avg_pace_fmt') or '--',
                'hr': f"{int(row['avg_hr'])}" if pd.notna(row.get('avg_hr')) else '--',
                'power': f"{int(row['avg_power'])}" if pd.notna(row.get('avg_power')) else '--',
                'cadence': f"{int(row['cadence'])}" if pd.notna(row.get('cadence')) else '--',
                'vo2_max': f"{int(row['vO2_max'])}" if pd.notna(row.get('vO2_max')) else '--',
                'activity_id': row.get('activity_id', 'unknown'),
            }
            # 检查是否有对应的深析报告（新格式带 activity_id 优先，旧格式日期兜底）
            if analysis_dir:
                date_str = record['date'].replace('-', '')  # YYYYMMDD
                activity_id = record.get('activity_id')
                candidates = []
                if activity_id and str(activity_id) not in ('', 'unknown', 'None'):
                    candidates.append(f"run_analysis_{date_str}_{activity_id}.html")
                candidates.append(f"run_analysis_{date_str}.html")
                for expected_file in candidates:
                    if expected_file in available_links:
                        record['deep_analysis_link'] = expected_file
                        break

            records.append(record)

        records.sort(key=lambda x: x['date'], reverse=True)
        return records

    def _serialize_charts(self, charts: Dict) -> Dict[str, str]:
        """将图表字典序列化为JSON字符串"""
        charts_json = {}
        for key, chart in charts.items():
            if chart:
                charts_json[key] = json.dumps(chart, cls=NumpyEncoder, ensure_ascii=False)
            else:
                charts_json[key] = 'null'
        return charts_json

    def generate_html(self, df: pd.DataFrame, charts: Dict, stats: Dict, output_path: str, analysis_dir: str = None, model_name: str = 'AI模型'):
        """生成HTML报告"""
        insights = self.generate_insights(df, stats)
        table_data = self._prepare_table_data(df, analysis_dir=analysis_dir)
        charts_json = self._serialize_charts(charts)

        # 预计算模板变量
        current_month = datetime.now().strftime('%Y-%m')
        monthly_data = df[df['year_month'] == current_month] if 'year_month' in df.columns else pd.DataFrame()
        current_month_distance = monthly_data['distance'].sum() if len(monthly_data) > 0 else 0

        total_duration_hours = stats.get('total_duration', 0) / 60
        total_dur_h = int(total_duration_hours)
        total_dur_m = int((total_duration_hours % 1) * 60)

        avg_pace_sec = stats.get('avg_pace', 0)
        pace_m = int(avg_pace_sec // 60) if avg_pace_sec else 0
        pace_s = int(avg_pace_sec % 60) if avg_pace_sec else 0

        # 检查是否有训练效果数据
        has_training_effect = bool(charts.get('training_effect'))
        has_power = bool(charts.get('power_distribution'))

        # jinja2 是事实依赖，缺失时给出明确错误
        if not HAS_JINJA2:
            raise RuntimeError(
                "PowerFun 报告生成依赖 jinja2 模板引擎。"
                "请运行：pip install jinja2，然后重试。"
            )

        html_content = self._render_jinja2(
            df, charts_json, stats, insights, table_data, charts,
            current_month_distance, total_dur_h, total_dur_m, pace_m, pace_s,
            has_training_effect, has_power
        )

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"HTML报告已生成: {output_path}")

    def _render_jinja2(self, df, charts_json, stats, insights, table_data, charts,
                       current_month_distance, total_dur_h, total_dur_m, pace_m, pace_s,
                       has_training_effect, has_power) -> str:
        """使用Jinja2模板渲染"""
        template_str = self._get_html_template()
        env = Environment(
            loader=BaseLoader(),
            autoescape=select_autoescape(['html']),
        )
        template = env.from_string(template_str)
        return template.render(
            df=df, charts_json=charts_json, stats=stats,
            insights=insights, table_data=table_data, charts=charts,
            datetime=datetime, json=json, NumpyEncoder=NumpyEncoder,
            pd=pd,
            current_month_distance=current_month_distance,
            total_dur_h=total_dur_h, total_dur_m=total_dur_m,
            pace_m=pace_m, pace_s=pace_s,
            has_training_effect=has_training_effect,
            has_power=has_power,
            version=load_version(),
        )

    def _get_html_template(self) -> str:
        """返回HTML模板字符串（Jinja2语法）"""
        return r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>跑步数据分析报告 - {{ stats.get('date_range', {}).get('start', '') }} 至 {{ stats.get('date_range', {}).get('end', '') }}</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <link rel="stylesheet" href="https://cdn.bootcdn.net/ajax/libs/datatables/1.10.21/css/jquery.dataTables.min.css">
    <script src="https://cdn.bootcdn.net/ajax/libs/jquery/3.7.1/jquery.min.js"></script>
    <script src="https://cdn.bootcdn.net/ajax/libs/datatables/1.10.21/js/jquery.dataTables.min.js"></script>
    <style>
        :root {
            --z1-color: #808080; --z2-color: #87CEEB; --z3-color: #32CD32;
            --z4-color: #FFA500; --z5-color: #FF0000;
            --primary-color: #4169E1; --secondary-color: #FF6B6B;
            --bg-color: #f8f9fa; --card-bg: #ffffff;
            --text-color: #333333; --text-muted: #6c757d;
            --border-color: #dee2e6;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg-color); color: var(--text-color); line-height: 1.6;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .header {
            background: linear-gradient(135deg, var(--primary-color) 0%, #667eea 100%);
            color: white; padding: 40px; border-radius: 16px; margin-bottom: 30px;
            box-shadow: 0 4px 20px rgba(65, 105, 225, 0.3);
        }
        .header h1 { font-size: 2.5rem; margin-bottom: 10px; font-weight: 700; }
        .header .subtitle { font-size: 1.1rem; opacity: 0.9; margin-bottom: 20px; }
        .header .meta { font-size: 0.9rem; opacity: 0.8; }
        .metrics-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px; margin-bottom: 30px;
        }
        .metric-card {
            background: var(--card-bg); padding: 24px; border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .metric-card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,0.12); }
        .metric-card .label { font-size: 0.9rem; color: var(--text-muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
        .metric-card .value { font-size: 2rem; font-weight: 700; color: var(--primary-color); }
        .metric-card .unit { font-size: 0.9rem; color: var(--text-muted); margin-left: 4px; }
        .section {
            background: var(--card-bg); padding: 30px; border-radius: 12px;
            margin-bottom: 30px; box-shadow: 0 2px 12px rgba(0,0,0,0.08);
        }
        .section-title {
            font-size: 1.5rem; font-weight: 600; margin-bottom: 24px; padding-bottom: 12px;
            border-bottom: 2px solid var(--border-color);
            display: flex; align-items: center; gap: 10px;
        }
        .section-title .icon { font-size: 1.3rem; }
        .chart-container { width: 100%; min-height: 400px; }
        .charts-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 30px; }
        .insights-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .insight-card { padding: 20px; border-radius: 10px; border-left: 4px solid; }
        .insight-card.warning { background: #fff3cd; border-color: #ffc107; }
        .insight-card.info { background: #d1ecf1; border-color: #17a2b8; }
        .insight-card.tip { background: #d4edda; border-color: #28a745; }
        .insight-card .icon { font-size: 1.5rem; margin-bottom: 10px; }
        .insight-card .title { font-weight: 600; margin-bottom: 8px; font-size: 1.1rem; }
        .insight-card .message { color: var(--text-muted); font-size: 0.95rem; line-height: 1.5; }
        .table-container { max-height: 600px; overflow-y: auto; position: relative; }
        .data-table { width: 100%; border-collapse: separate; border-spacing: 0; }
        .data-table thead { position: sticky; top: 0; z-index: 10; }
        .data-table th {
            background: var(--primary-color); color: white; padding: 14px 12px;
            text-align: left; font-weight: 600; border-bottom: 2px solid var(--border-color);
            position: sticky; top: 0;
        }
        .data-table td { padding: 12px; border-bottom: 1px solid var(--border-color); }
        .data-table tr:hover { background: var(--bg-color); }
        .category-badge {
            display: inline-block; padding: 4px 10px; border-radius: 20px;
            font-size: 0.85rem; font-weight: 500; color: white;
        }
        .footer { text-align: center; padding: 30px; color: var(--text-muted); font-size: 0.9rem; }
        @media (max-width: 768px) {
            .header h1 { font-size: 1.8rem; }
            .metrics-grid { grid-template-columns: repeat(2, 1fr); }
            .charts-row { grid-template-columns: 1fr; }
            .section { padding: 20px; }
        }
        .dataTables_wrapper .dataTables_length,
        .dataTables_wrapper .dataTables_filter { margin-bottom: 15px; }
        .dataTables_wrapper .dataTables_info,
        .dataTables_wrapper .dataTables_paginate { margin-top: 15px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏃 PowerFun 综合分析报告</h1>
            <div class="subtitle">Running Power Analysis Report</div>
            <div class="meta">
                <div>📅 数据时间范围: {{ stats.get('date_range', {}).get('start', '--') }} 至 {{ stats.get('date_range', {}).get('end', '--') }}</div>
                <div>📊 报告生成时间: {{ datetime.now().strftime('%Y-%m-%d %H:%M:%S') }}</div>
            </div>
        </div>

        <div class="metrics-grid">
            <div class="metric-card">
                <div class="label">总次数</div>
                <div class="value">{{ stats.get('total_runs', 0) }}<span class="unit">次</span></div>
            </div>
            <div class="metric-card">
                <div class="label">总距离</div>
                <div class="value">{{ "%.1f"|format(stats.get('total_distance', 0)) }}<span class="unit">km</span></div>
            </div>
            <div class="metric-card">
                <div class="label">总时长</div>
                <div class="value">{{ total_dur_h }}:{{ '%02d'|format(total_dur_m) }}<span class="unit">小时</span></div>
            </div>
            <div class="metric-card">
                <div class="label">本月跑量</div>
                <div class="value">{{ "%.1f"|format(current_month_distance) }}<span class="unit">km</span></div>
            </div>
            <div class="metric-card">
                <div class="label">平均配速</div>
                <div class="value">{{ pace_m }}:{{ '%02d'|format(pace_s) }}<span class="unit">/km</span></div>
            </div>
            <div class="metric-card">
                <div class="label">平均心率</div>
                <div class="value">{{ "%.0f"|format(stats.get('avg_hr', 0)) }}<span class="unit">bpm</span></div>
            </div>
        </div>

        <div class="section">
            <h2 class="section-title"><span class="icon">📈</span>配速-心率趋势分析</h2>
            <div id="chart-pace-hr" class="chart-container"></div>
        </div>

        <div class="charts-row">
            <div class="section">
                <h2 class="section-title"><span class="icon">📊</span>月跑量趋势</h2>
                <div id="chart-monthly" class="chart-container"></div>
            </div>
            <div class="section">
                <h2 class="section-title"><span class="icon">💓</span>心率区间分布</h2>
                <div id="chart-hr-pie" class="chart-container"></div>
            </div>
        </div>

        <div class="charts-row">
            <div class="section">
                <h2 class="section-title"><span class="icon">🏃</span>训练类型分布</h2>
                <div id="chart-category" class="chart-container"></div>
            </div>
            <div class="section">
                <h2 class="section-title"><span class="icon">📅</span>月度心率区间时长</h2>
                <div id="chart-hr-stacked" class="chart-container"></div>
            </div>
        </div>

        <div class="charts-row">
            {% if has_power %}
            <div class="section">
                <h2 class="section-title"><span class="icon">⚡</span>功率分布</h2>
                <div id="chart-power" class="chart-container"></div>
            </div>
            {% endif %}
            <div class="section">
                <h2 class="section-title"><span class="icon">💪</span>心率分布直方图</h2>
                <div id="chart-hr-dist" class="chart-container"></div>
            </div>
        </div>

        {% set vr_gct_trend_json = charts_json.get('vr_gct_trend', 'null') %}
        {% if vr_gct_trend_json and vr_gct_trend_json != 'null' %}
        <div class="section">
            <h2 class="section-title"><span class="icon">📈</span>垂直振幅比 & 触地时间趋势</h2>
            <div id="chart-vr-gct" class="chart-container"></div>
        </div>
        {% endif %}

        {% if has_training_effect %}
        <div class="section">
            <h2 class="section-title"><span class="icon">🎯</span>训练效果趋势</h2>
            <div id="chart-training-effect" class="chart-container"></div>
        </div>
        {% endif %}

        {% set temp_hr_scatter_json = charts_json.get('temp_hr_scatter', 'null') %}
        {% if temp_hr_scatter_json and temp_hr_scatter_json != 'null' %}
        <div class="section">
            <h2 class="section-title"><span class="icon">🌡️</span>气温-心率效率趋势</h2>
            <div id="chart-temp-hr-scatter" class="chart-container"></div>
        </div>
        {% endif %}

        {% set beats_per_km_json = charts_json.get('beats_per_km', 'null') %}
        {% if beats_per_km_json and beats_per_km_json != 'null' %}
        <div class="section">
            <h2 class="section-title"><span class="icon">💓</span>心率成本趋势（beats/km）</h2>
            <div id="chart-beats-per-km" class="chart-container"></div>
        </div>
        {% endif %}

        <div class="charts-row">
            {% set speed_hr_scatter_json = charts_json.get('speed_hr_scatter', 'null') %}
            {% if speed_hr_scatter_json and speed_hr_scatter_json != 'null' %}
            <div class="section">
                <h2 class="section-title"><span class="icon">🏃</span>速度-心率散点（颜色=气温）</h2>
                <div id="chart-speed-hr-scatter" class="chart-container"></div>
            </div>
            {% endif %}

            {% set speed_hr_temp_curves_json = charts_json.get('speed_hr_temp_curves', 'null') %}
            {% if speed_hr_temp_curves_json and speed_hr_temp_curves_json != 'null' %}
            <div class="section">
                <h2 class="section-title"><span class="icon">🌡️</span>速度-心率温度分层曲线</h2>
                <div id="chart-speed-hr-temp-curves" class="chart-container"></div>
            </div>
            {% endif %}
        </div>

        <div class="section">
            <h2 class="section-title"><span class="icon">🎯</span>训练结论与下一步</h2>
            <div class="insights-grid">
                {% for insight in insights %}
                <div class="insight-card {{ insight['type'] }}">
                    <div class="icon">{{ insight['icon'] }}</div>
                    <div class="title">{{ insight['title'] }}</div>
                    <div class="message">{{ insight['message'] }}</div>
                </div>
                {% endfor %}
            </div>
        </div>

        <div class="section">
            <h2 class="section-title"><span class="icon">📋</span>详细数据记录</h2>
            <div class="table-container">
                <table id="data-table" class="data-table">
                    <thead>
                        <tr>
                            <th>日期</th><th>标题</th><th>分类</th>
                            <th>距离 (km)</th><th>配速</th><th>心率 (bpm)</th>
                            <th>功率 (w)</th><th>步频 (spm)</th><th>VO2max</th>
                            <th>深度分析</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for record in table_data %}
                        <tr>
                            <td>{{ record['date'] }}</td>
                            <td>{{ record['title'] }}</td>
                            <td><span class="category-badge" style="background-color: {{ record['category_color'] }}">{{ record['category'] }}</span></td>
                            <td>{{ record['distance'] }}</td>
                            <td>{{ record['pace'] }}</td>
                            <td>{{ record['hr'] }}</td>
                            <td>{{ record['power'] }}</td>
                            <td>{{ record['cadence'] }}</td>
                            <td>{{ record['vo2_max'] }}</td>
                            <td>
                                {% if record.get('deep_analysis_link') %}
                                <a href="PowerFun_Reports/{{ record['deep_analysis_link'] }}" 
                                   target="_blank" 
                                   style="color:#667eea;text-decoration:none;">📊 查看</a>
                                {% else %}
                                -
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="footer">
            <p>🏃 综合分析报告 v{{ version }} | 数据来自 Garmin Connect</p>
            <p>支持 Garmin / Coros / 高驰 / Keep 等主流运动平台导出格式</p>
        </div>
    </div>

    <script>
        const pace_hr_trend = {{ charts_json['pace_hr_trend'] | safe }};
        const monthly_volume = {{ charts_json['monthly_volume'] | safe }};
        const hr_zone_pie = {{ charts_json['hr_zone_pie'] | safe }};
        const category_pie = {{ charts_json['category_pie'] | safe }};
        const hr_zone_stacked = {{ charts_json['hr_zone_stacked'] | safe }};
        const vr_gct_trend = {{ charts_json.get('vr_gct_trend', 'null') | safe }};
        const hr_distribution = {{ charts_json.get('hr_distribution', 'null') | safe }};
        const training_effect = {{ charts_json.get('training_effect', 'null') | safe }};
        const power_distribution = {{ charts_json.get('power_distribution', 'null') | safe }};
        const temp_hr_scatter = {{ charts_json.get('temp_hr_scatter', 'null') | safe }};
        const beats_per_km = {{ charts_json.get('beats_per_km', 'null') | safe }};
        const speed_hr_scatter = {{ charts_json.get('speed_hr_scatter', 'null') | safe }};
        const speed_hr_temp_curves = {{ charts_json.get('speed_hr_temp_curves', 'null') | safe }};

        if (pace_hr_trend && pace_hr_trend.data) {
            Plotly.newPlot('chart-pace-hr', pace_hr_trend.data, pace_hr_trend.layout, {responsive: true});
            
            // 自定义筛选按钮 + JS联动（替代Plotly updatemenus）
            var phFilter = pace_hr_trend._pace_hr_filter;
            if (phFilter) {
                var phState = { catIdx: 0, dateIdx: 0 };
                var el = document.getElementById('chart-pace-hr');
                
                // 类型按钮容器（图表上方）
                var catDiv = document.createElement('div');
                catDiv.style.cssText = 'text-align:center;margin-bottom:10px;';
                phFilter.cat_labels.forEach(function(label, i) {
                    var btn = document.createElement('button');
                    btn.textContent = label;
                    btn.dataset.idx = i;
                    btn.style.cssText = 'padding:6px 14px;margin:0 4px;border:1px solid #ccc;background:' + (i===0?'#4169E1':'#fff') + ';color:' + (i===0?'#fff':'#333') + ';border-radius:4px;cursor:pointer;font-size:13px;';
                    btn.onclick = function() {
                        phState.catIdx = i;
                        var vis = phFilter.visibility_matrix[i + '_' + phState.dateIdx];
                        Plotly.restyle('chart-pace-hr', { visible: vis });
                        updateCatButtons(i);
                    };
                    catDiv.appendChild(btn);
                });
                el.parentElement.insertBefore(catDiv, el);
                
                // 时间按钮容器（图表下方）
                var dateDiv = document.createElement('div');
                dateDiv.style.cssText = 'text-align:center;margin-top:10px;';
                phFilter.date_labels.forEach(function(label, i) {
                    var btn = document.createElement('button');
                    btn.textContent = label;
                    btn.dataset.idx = i;
                    btn.style.cssText = 'padding:6px 14px;margin:0 4px;border:1px solid #ccc;background:' + (i===0?'#4169E1':'#fff') + ';color:' + (i===0?'#fff':'#333') + ';border-radius:4px;cursor:pointer;font-size:13px;';
                    btn.onclick = function() {
                        phState.dateIdx = i;
                        var vis = phFilter.visibility_matrix[phState.catIdx + '_' + i];
                        Plotly.restyle('chart-pace-hr', { visible: vis });
                        updateDateButtons(i);
                    };
                    dateDiv.appendChild(btn);
                });
                el.parentElement.appendChild(dateDiv);
                
                function updateCatButtons(activeIdx) {
                    catDiv.querySelectorAll('button').forEach(function(b, i) {
                        b.style.background = i===activeIdx ? '#4169E1' : '#fff';
                        b.style.color = i===activeIdx ? '#fff' : '#333';
                    });
                }
                function updateDateButtons(activeIdx) {
                    dateDiv.querySelectorAll('button').forEach(function(b, i) {
                        b.style.background = i===activeIdx ? '#4169E1' : '#fff';
                        b.style.color = i===activeIdx ? '#fff' : '#333';
                    });
                }
            }
        }
        if (monthly_volume && monthly_volume.data) {
            Plotly.newPlot('chart-monthly', monthly_volume.data, monthly_volume.layout, {responsive: true});
        }
        if (hr_zone_pie && hr_zone_pie.data) {
            Plotly.newPlot('chart-hr-pie', hr_zone_pie.data, hr_zone_pie.layout, {responsive: true});
        }
        if (category_pie && category_pie.data) {
            Plotly.newPlot('chart-category', category_pie.data, category_pie.layout, {responsive: true});
        }
        if (hr_zone_stacked && hr_zone_stacked.data) {
            Plotly.newPlot('chart-hr-stacked', hr_zone_stacked.data, hr_zone_stacked.layout, {responsive: true});
        }
        if (vr_gct_trend && vr_gct_trend.data) {
            Plotly.newPlot('chart-vr-gct', vr_gct_trend.data, vr_gct_trend.layout, {responsive: true});
        }
        if (hr_distribution && hr_distribution.data) {
            Plotly.newPlot('chart-hr-dist', hr_distribution.data, hr_distribution.layout, {responsive: true});
        }
        {% if has_training_effect %}
        if (training_effect && training_effect.data) {
            Plotly.newPlot('chart-training-effect', training_effect.data, training_effect.layout, {responsive: true});
        }
        {% endif %}
        {% if has_power %}
        if (power_distribution && power_distribution.data) {
            Plotly.newPlot('chart-power', power_distribution.data, power_distribution.layout, {responsive: true});
        }
        {% endif %}

        if (temp_hr_scatter && temp_hr_scatter.data) {
            Plotly.newPlot('chart-temp-hr-scatter', temp_hr_scatter.data, temp_hr_scatter.layout, {responsive: true});
        }
        if (beats_per_km && beats_per_km.data) {
            Plotly.newPlot('chart-beats-per-km', beats_per_km.data, beats_per_km.layout, {responsive: true});
        }
        if (speed_hr_scatter && speed_hr_scatter.data) {
            Plotly.newPlot('chart-speed-hr-scatter', speed_hr_scatter.data, speed_hr_scatter.layout, {responsive: true});
        }
        if (speed_hr_temp_curves && speed_hr_temp_curves.data) {
            Plotly.newPlot('chart-speed-hr-temp-curves', speed_hr_temp_curves.data, speed_hr_temp_curves.layout, {responsive: true});
        }

        $(document).ready(function() {
            $('#data-table').DataTable({
                pageLength: 50,
                language: { url: 'https://cdn.bootcdn.net/ajax/libs/datatables/1.10.21/i18n/zh.json' },
                order: [[0, 'desc']]
            });
        });
    </script>
</body>
</html>'''
