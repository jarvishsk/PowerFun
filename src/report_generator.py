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


def _load_version() -> str:
    """从 VERSION 文件读取版本号"""
    try:
        version_path = Path(__file__).resolve().parent.parent / 'VERSION'
        return version_path.read_text().strip()
    except Exception:
        return '3.0'


def _safe_color(color) -> str:
    """颜色值 XSS 白名单校验：只允许 #RRGGBB 格式"""
    if re.match(r'^#[0-9a-fA-F]{6}$', str(color)):
        return str(color)
    return '#999999'

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
        """生成智能训练建议"""
        insights = []

        if 'hr_zone' in df.columns:
            z1_count = len(df[df['hr_zone'] == 'Z1-有氧基础'])
            total_count = len(df)
            z1_pct = z1_count / total_count if total_count > 0 else 0
            if z1_pct < 0.3:
                insights.append({'type': 'warning', 'icon': '⚠️', 'title': '有氧基础训练不足',
                    'message': f'Z1有氧基础训练占比仅 {z1_pct*100:.1f}%，建议增加轻松跑比例，夯实有氧基础。理想比例为30-40%。'})
            elif z1_pct > 0.5:
                insights.append({'type': 'info', 'icon': '✅', 'title': '有氧基础扎实',
                    'message': f'Z1有氧基础训练占比 {z1_pct*100:.1f}%，有氧基础训练充足。'})

        if 'date' in df.columns:
            df_sorted = df.sort_values('date')
            last_run = df_sorted['date'].max()
            gap = (datetime.now() - last_run).days
            if gap > 7:
                insights.append({'type': 'warning', 'icon': '⏰', 'title': '训练空窗期',
                    'message': f'最近 {gap} 天无跑步记录，注意保持训练连续性。'})

        if 'cadence' in df.columns and df['cadence'].notna().any():
            avg_cad = df['cadence'].mean()
            if avg_cad < 170:
                insights.append({'type': 'tip', 'icon': '👟', 'title': '步频偏低',
                    'message': f'平均步频 {avg_cad:.0f} spm，建议通过节拍器训练提升至180spm。'})
            elif avg_cad >= 180:
                insights.append({'type': 'info', 'icon': '✅', 'title': '步频优秀',
                    'message': f'平均步频 {avg_cad:.0f} spm，步频控制良好。'})

        if 'category' in df.columns:
            race_count = len(df[df['category'].isin(['full_marathon', 'half_marathon', 'race_event'])])
            if race_count > 0:
                insights.append({'type': 'info', 'icon': '🏆', 'title': '比赛完成',
                    'message': f'本周期内完成 {race_count} 场比赛，注意赛后恢复。'})

        if 'hr_zone' in df.columns:
            z5_count = len(df[df['hr_zone'] == 'Z5-最大强度'])
            if z5_count > len(df) * 0.2:
                insights.append({'type': 'warning', 'icon': '🔥', 'title': '高强度训练过多',
                    'message': f'Z5最大强度训练占比过高（{z5_count/len(df)*100:.1f}%），注意控制强度。'})

        if 'year_month' in df.columns:
            monthly = df.groupby('year_month')['distance'].sum()
            if len(monthly) >= 2:
                latest = monthly.iloc[-1]
                prev = monthly.iloc[-2]
                change = (latest - prev) / prev * 100 if prev > 0 else 0
                if change > 20:
                    insights.append({'type': 'warning', 'icon': '📈', 'title': '跑量增长过快',
                        'message': f'本月跑量较上月增长 {change:.1f}%，注意循序渐进。'})
                elif change < -20:
                    insights.append({'type': 'tip', 'icon': '📉', 'title': '跑量下降',
                        'message': f'本月跑量较上月下降 {abs(change):.1f}%，注意保持训练量。'})

        if not insights:
            insights.append({'type': 'info', 'icon': '✨', 'title': '训练状态良好',
                'message': '训练数据看起来不错，继续保持！建议每周安排1-2次力量训练。'})

        return insights

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
                'title': (row.get('title') or '--')[:25],  # 截断为最多25个字符
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
            # 检查是否有对应的深析报告
            if analysis_dir:
                date_str = record['date'].replace('-', '')  # YYYYMMDD
                expected_file = f"run_analysis_{date_str}.html"
                if expected_file in available_links:
                    record['deep_analysis_link'] = expected_file

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

    def generate_html(self, df: pd.DataFrame, charts: Dict, stats: Dict, output_path: str, analysis_dir: str = None):
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

        # 使用Jinja2渲染
        if HAS_JINJA2:
            html_content = self._render_jinja2(
                df, charts_json, stats, insights, table_data, charts,
                current_month_distance, total_dur_h, total_dur_m, pace_m, pace_s,
                has_training_effect, has_power
            )
        else:
            html_content = self._render_fallback(
                df, charts_json, stats, insights, table_data, charts,
                current_month_distance, total_dur_h, total_dur_m, pace_m, pace_s,
                has_training_effect, has_power, _load_version()
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
            version=_load_version(),
        )

    def _render_fallback(self, df, charts_json, stats, insights, table_data, charts,
                         current_month_distance, total_dur_h, total_dur_m, pace_m, pace_s,
                         has_training_effect, has_power, version='3.0') -> str:
        """不使用Jinja2的渲染（直接字符串替换）"""
        # 构建HTML各部分（对所有用户数据进行html.escape防XSS）
        insights_html = '\n'.join([
            f'<div class="insight-card {html.escape(i["type"])}">'
            f'<div class="icon">{html.escape(i["icon"])}</div>'
            f'<div class="title">{html.escape(i["title"])}</div>'
            f'<div class="message">{html.escape(i["message"])}</div></div>'
            for i in insights
        ])

        table_html = '\n'.join([
            f'<tr><td>{html.escape(r["date"])}</td><td>{html.escape(r["title"])}</td>'
            f'<td><span class="category-badge" style="background-color:{_safe_color(r.get("category_color", "#999"))}">{html.escape(r["category"])}</span></td>'
            f'<td>{html.escape(r["distance"])}</td><td>{html.escape(r["pace"])}</td><td>{html.escape(r["hr"])}</td>'
            f'<td>{html.escape(r["power"])}</td><td>{html.escape(r["cadence"])}</td></tr>'
            for r in table_data
        ])

        training_effect_section = ''
        if has_training_effect:
            training_effect_section = '''
        <div class="section">
            <h2 class="section-title"><span class="icon">🎯</span>训练效果趋势</h2>
            <div id="chart-training-effect" class="chart-container"></div>
        </div>'''

        power_section = ''
        if has_power:
            power_section = '''
        <div class="section">
            <h2 class="section-title"><span class="icon">⚡</span>功率分布</h2>
            <div id="chart-power" class="chart-container"></div>
        </div>'''

        training_effect_script = ''
        if has_training_effect:
            training_effect_script = "if (training_effect && training_effect.data) { Plotly.newPlot('chart-training-effect', training_effect.data, training_effect.layout, {responsive: true}); }"

        power_script = ''
        if has_power:
            power_script = "if (power_distribution && power_distribution.data) { Plotly.newPlot('chart-power', power_distribution.data, power_distribution.layout, {responsive: true}); }"

        html = self._get_html_template().replace('{{ insights_html }}', insights_html)
        html = html.replace('{{ table_html }}', table_html)
        html = html.replace('{{ training_effect_section }}', training_effect_section)
        html = html.replace('{{ power_section }}', power_section)
        html = html.replace('{{ training_effect_script }}', training_effect_script)
        html = html.replace('{{ power_script }}', power_script)

        return html

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

        <div class="section">
            <h2 class="section-title"><span class="icon">📏</span>距离趋势</h2>
            <div id="chart-distance" class="chart-container"></div>
        </div>

        {% if has_training_effect %}
        <div class="section">
            <h2 class="section-title"><span class="icon">🎯</span>训练效果趋势</h2>
            <div id="chart-training-effect" class="chart-container"></div>
        </div>
        {% endif %}

        <div class="section">
            <h2 class="section-title"><span class="icon">💡</span>智能训练建议</h2>
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
        const distance_trend = {{ charts_json.get('distance_trend', 'null') | safe }};
        const hr_distribution = {{ charts_json.get('hr_distribution', 'null') | safe }};
        const training_effect = {{ charts_json.get('training_effect', 'null') | safe }};
        const power_distribution = {{ charts_json.get('power_distribution', 'null') | safe }};

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
        if (distance_trend && distance_trend.data) {
            Plotly.newPlot('chart-distance', distance_trend.data, distance_trend.layout, {responsive: true});
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
