"""跑步深度分析报告生成器"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Template, Environment, BaseLoader

from src.config import ZONE_COLORS as _ZONE_COLORS

logger = logging.getLogger("PowerFun.analysis_report")


def _load_version() -> str:
    """从 VERSION 文件读取版本号"""
    try:
        version_path = Path(__file__).resolve().parent.parent / 'VERSION'
        return version_path.read_text().strip()
    except Exception:
        return '3.0'

# 创建共享 Environment
_env = Environment(loader=BaseLoader())

# ============================================================
# 自定义过滤器和全局函数
# ============================================================

def trend_class(diff: float) -> str:
    if diff < 0: return 'down'
    elif diff > 0: return 'up'
    return 'flat'

def signed(val: float) -> str:
    return f"+{val:.0f}" if val > 0 else f"{val:.0f}"

def markdown_to_html(md_text: str) -> str:
    """将 LLM 输出的 Markdown 转为 HTML，支持标题、加粗、列表、分割线"""
    import re
    if not md_text:
        return ""
    # XSS 过滤
    md_text = re.sub(r'<script[^>]*>.*?</script>', '', md_text, flags=re.DOTALL | re.IGNORECASE)
    md_text = re.sub(r'<iframe[^>]*>', '', md_text, flags=re.IGNORECASE)
    md_text = re.sub(r'\bon\w+\s*=', '', md_text, flags=re.IGNORECASE)

    # 先处理标题和加粗
    md_text = re.sub(r'^#{2,3}\s+(.+)$', r'<h3>\1</h3>', md_text, flags=re.MULTILINE)
    md_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', md_text)
    # 处理分割线
    md_text = re.sub(r'^---\s*$', '<hr>', md_text, flags=re.MULTILINE)

    lines = md_text.split('\n')
    result = []
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            result.append('</ul>')
            in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == '<hr>':
            close_list()
            if stripped == '<hr>':
                result.append('<hr>')
            continue

        # 列表项: * xxx 或 - xxx
        list_match = re.match(r'^[\*\-]\s+(.+)$', stripped)
        if list_match:
            if not in_list:
                result.append('<ul>')
                in_list = True
            content = list_match.group(1)
            # 处理列表项中的 **加粗**
            content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
            result.append(f'<li>{content}</li>')
        else:
            close_list()
            # 非列表行：跳过 h3 后的空行，其他按段落处理
            if stripped.startswith('<h3>'):
                result.append(stripped)
            else:
                result.append(f'<p>{stripped}</p>')

    close_list()
    return '\n'.join(result)

def truncate_text(text, max_len):
    return text[:max_len] if text else ''

def format_pace(secs):
    return f"{int(secs//60)}分{int(secs%60):02d}秒/KM" if secs else "--"

def fmt2(val):
    """格式化数字为保留两位小数，0 也显示（如 0.40）"""
    try:
        return f"{float(val):.2f}"
    except (ValueError, TypeError):
        return str(val)

def bracket_color(diff, good_is_low):
    return '#dc3545' if (diff < 0) == good_is_low else '#28a745'

def bracket_text_color(diff, good_is_low, verdict=''):
    return '#17a2b8' if verdict == '持平' else ('#dc3545' if (diff < 0) == good_is_low else '#28a745')

# 注册所有过滤器和全局函数
_env.filters['trend_class'] = trend_class
_env.filters['signed'] = signed
_env.filters['markdown_to_html'] = markdown_to_html
_env.filters['truncate_text'] = truncate_text
_env.filters['format_pace'] = format_pace
_env.filters['fmt2'] = fmt2
_env.filters['bracket_color'] = bracket_color
_env.globals['bracket_color'] = bracket_color
_env.globals['bracket_text_color'] = bracket_text_color
_env.globals['trend_class'] = trend_class

# HTML 模板
ANALYSIS_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>跑步深度分析 - {{ date }} {{ category_name }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #f5f5f5; color: #333; line-height: 1.6; }
        .container { max-width: 800px; margin: 0 auto; padding: 24px 16px; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 32px 24px; border-radius: 16px; margin-bottom: 24px; text-align: center; }
        .header h1 { font-size: 24px; margin-bottom: 8px; }
        .header .meta { font-size: 14px; opacity: 0.9; }
        .section { background: white; border-radius: 12px; padding: 24px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
        .section h2 { font-size: 18px; color: #667eea; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid #f0f0f0; }
        .section h3 { font-size: 15px; color: #555; margin: 12px 0 8px; }
        .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; margin-bottom: 16px; }
        .stat-card { background: #f8f9fa; border-radius: 8px; padding: 12px; text-align: center; }
        .stat-card .value { font-size: 24px; font-weight: 600; color: #667eea; }
        .stat-card .label { font-size: 12px; color: #888; margin-top: 4px; }
        .zone-bar { display: flex; height: 24px; border-radius: 12px; overflow: hidden; margin: 8px 0; }
        .zone-bar div { display: flex; align-items: center; justify-content: center; font-size: 11px; color: white; font-weight: 500; }
        .eval-badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 500; }
        .eval-excellent { background: #d4edda; color: #155724; }
        .eval-good { background: #cce5ff; color: #004085; }
        .eval-normal { background: #fff3cd; color: #856404; }
        .eval-poor { background: #f8d7da; color: #721c24; }
        .trend-up { color: #28a745; }
        .trend-down { color: #dc3545; }
        .trend-flat { color: #6c757d; }
        .finding { padding: 8px 12px; background: #f0f4ff; border-left: 3px solid #667eea; border-radius: 4px; margin: 8px 0; }
        .llm-report { background: #fafafa; border-radius: 8px; padding: 20px; line-height: 1.8; }
        .llm-report h3 { color: #667eea; margin: 16px 0 8px; font-size: 16px; }
        .llm-report h3:first-child { margin-top: 0; }
        .llm-report ul { margin: 8px 0 8px 20px; padding: 0; list-style: disc; }
        .llm-report li { margin: 4px 0; }
        .llm-report hr { border: none; border-top: 1px solid #e0e0e0; margin: 16px 0; }
        .llm-report p { margin: 8px 0; }
        .footer { text-align: center; padding: 16px; font-size: 12px; color: #999; }
        @media print { body { background: white; } .section { box-shadow: none; border: 1px solid #eee; } }
    </style>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🏃 深度分析报告</h1>
        <div class="meta">{{ date }} | {{ category_name }} | {{ distance_km }}km | {{ duration_min }}分钟</div>
    </div>

    <div class="section">
        <h2>📊 本次跑步总结</h2>
        <p>主训练区间：<strong>{{ dominant_zone }}</strong>（占比 {{ zone_pct.get(dominant_zone, 0)|int }}%）</p>
        {% if brief_summary %}
        <p style="margin-top:12px;color:#555;font-size:14px;line-height:1.8;">{{ brief_summary|truncate_text(500) }}</p>
        {% endif %}
        <div class="zone-bar">
            {% for zone in ['Z1-有氧基础', 'Z2-有氧耐力', 'Z3-乳酸阈值', 'Z4-无氧耐力', 'Z5-最大强度'] %}
            {% if zone_pct.get(zone, 0) > 0 %}
            <div style="width: {{ zone_pct.get(zone, 0)|int }}%; background: {{ zone_colors.get(zone, '#999') }};">{{ zone_pct.get(zone, 0)|int }}%</div>
            {% endif %}
            {% endfor %}
        </div>
        <div class="stat-grid">
            <div class="stat-card"><div class="value">{{ avg_hr }}</div><div class="label">平均心率</div></div>
            <div class="stat-card"><div class="value">{{ max_hr }}</div><div class="label">最大心率</div></div>
            <div class="stat-card"><div class="value">{{ avg_power }}</div><div class="label">平均功率</div></div>
            <div class="stat-card"><div class="value">{{ cadence }}</div><div class="label">步频</div></div>
        </div>
    </div>

    <div class="section">
        <h2>💪 强度与负荷</h2>
        <h3>心率分布</h3>
        {% for zone_key, zone_info in hr_zone_ranges.items() %}
        {% if hr_zone_pct.get(zone_key, 0) > 0 %}
        <div style="display:flex;justify-content:space-between;padding:4px 8px;border-radius:4px;
            background:{{ zone_colors.get(zone_key + '-' + zone_info.label, '#999') }};color:white;margin:2px 0;">
            <span>{{ zone_key }}-{{ zone_info.label }}（{{ zone_info.min_hr }}-{{ zone_info.max_hr }} bpm）</span>
            <span>{{ hr_zone_pct.get(zone_key, 0)|int }}%</span>
        </div>
        {% endif %}
        {% endfor %}
        <h3>功率与训练效果</h3>
        <div class="stat-grid">
            <div class="stat-card"><div class="value">{{ avg_power }}</div><div class="label">平均功率 (W)</div></div>
            <div class="stat-card"><div class="value">{{ max_power }}</div><div class="label">最大功率 (W)</div></div>
            <div class="stat-card"><div class="value">{{ aerobic_te }}</div><div class="label">有氧 TE</div></div>
            <div class="stat-card"><div class="value">{{ anaerobic_te }}</div><div class="label">无氧 TE</div></div>
        </div>
        <p>本次卡路里总消耗：{{ total_calories }}kcal = {{ calories }} kcal（运动）+ {{ bmr_calories }} kcal（基础代谢）</p>
    </div>

    <div class="section">
        <h2>👟 效率与技术</h2>
        <div class="stat-grid">
            <div class="stat-card"><div class="value">{{ cadence }}</div><div class="label">步频 (spm)</div></div>
            <div class="stat-card"><div class="value">{{ stride_length }}<span style="font-size:14px">cm</span></div><div class="label">步幅</div></div>
            <div class="stat-card"><div class="value">{{ vertical_ratio }}%</div><div class="label">垂直振幅比</div></div>
            <div class="stat-card"><div class="value">{{ ground_contact }}</div><div class="label">触地时间 (ms)</div></div>
        </div>
        <!-- 横排评价（居中） -->
        <div style="display:flex;gap:16px;margin:12px 0;flex-wrap:wrap;justify-content:center;">
            <span>步频：<span class="eval-badge eval-{{ cadence_eval_class }}">{{ cadence_eval }}</span></span>
            <span>垂直振幅比：<span class="eval-badge eval-{{ vr_eval_class }}">{{ vr_eval }}</span></span>
            <span>触地时间：<span class="eval-badge eval-{{ gct_eval_class }}">{{ gct_eval }}</span></span>
        </div>
        <!-- 参考标准（断行） -->
        <p style="color:#999;font-size:12px;margin-top:8px;">
        <strong>参考标准</strong><br>
        <strong>步频</strong>：优秀≥180 良好170-179 一般160-169 偏低<160（spm）<br>
        <strong>垂直振幅比</strong>：优秀≤6.3% 良好6.4-8.0% 一般8.1-10.0% 偏高>10.0%<br>
        <strong>触地时间</strong>：优秀≤210 良好211-240 一般241-270 偏长>270（ms）
        </p>
    </div>

    {% if lap_pace_chart_html or lap_hr_chart_html %}
    <div class="section">
        <h2>📊 每公里配速</h2>
        <div id="lap-pace-chart" style="border-radius:8px;overflow:hidden;"></div>

    </div>
    {% if lap_pace_chart_html %}
    <script>
    (function(){
        try {
            var data = {{ lap_pace_chart_html | safe }};
            if (data && data.data && data.data.length > 0) {
                Plotly.newPlot('lap-pace-chart', data.data, data.layout, {responsive: true});
            }
        } catch(e) { console.error('lap pace chart render error:', e); }
    })();
    </script>
    {% endif %}

    {% if lap_hr_chart_html %}
    <div class="section">
        <h2>📊 每公里心率</h2>
        <div id="lap-hr-chart" style="border-radius:8px;overflow:hidden;"></div>
    </div>
    <script>
    (function(){
        try {
            var data = {{ lap_hr_chart_html | safe }};
            if (data && data.data && data.data.length > 0) {
                Plotly.newPlot('lap-hr-chart', data.data, data.layout, {responsive: true});
            }
        } catch(e) { console.error('lap hr chart render error:', e); }
    })();
    </script>
    {% endif %}
    {% endif %}

    {% if comparison and comparison.get('sample_size', 0) >= 1 %}
    <div class="section">
        <h2>📈 对比分析（近5次同类型均值）</h2>
        
        {% if comparison.get('ability') %}
        <h3>能力变化</h3>
        <style>
        .comparison-row {
            display: flex;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid #f0f0f0;
        }
        .comparison-row:last-child { border-bottom: none; }
        .metric-label { flex: 0 0 100px; font-size: 14px; color: #555; }
        .metric-values { flex: 1; text-align: center; font-size: 14px; }
        .metric-trend { flex: 0 0 120px; text-align: right; }
        .vs-badge { 
            display: inline-block;
            background: #dc3545;
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 12px;
            margin: 0 6px;
        }
        .trend-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
        }
        </style>
        
        {% if comparison.ability.get('hr_trend') %}
        <div class="comparison-row">
            <div class="metric-label">💓 心率</div>
            <div class="metric-values">{{ comparison.ability.hr_trend.current|int }}bpm <span class="vs-badge">VS</span> {{ comparison.ability.hr_trend.history_avg|int }}bpm</div>
            <div class="metric-trend"><span class="trend-badge" style="background:{{ '#e3f2fd' if comparison.ability.hr_trend.verdict == '持平' else ('#d4edda' if (comparison.ability.hr_trend.diff < 0) == True else '#f8d7da') }};color:{{ '#17a2b8' if comparison.ability.hr_trend.verdict == '持平' else ('#155724' if (comparison.ability.hr_trend.diff < 0) == True else '#721c24') }};">{{ comparison.ability.hr_trend.verdict }}</span></div>
        </div>
        {% endif %}
        
        {% if comparison.ability.get('pace_trend') %}
        <div class="comparison-row">
            <div class="metric-label">🏃 配速</div>
            <div class="metric-values">{{ comparison.ability.pace_trend.current|format_pace }} <span class="vs-badge">VS</span> {{ comparison.ability.pace_trend.history_avg|format_pace }}</div>
            <div class="metric-trend"><span class="trend-badge" style="background:{{ '#e3f2fd' if comparison.ability.pace_trend.verdict == '持平' else ('#d4edda' if (comparison.ability.pace_trend.diff < 0) == True else '#f8d7da') }};color:{{ '#17a2b8' if comparison.ability.pace_trend.verdict == '持平' else ('#155724' if (comparison.ability.pace_trend.diff < 0) == True else '#721c24') }};">{{ comparison.ability.pace_trend.verdict }}</span></div>
        </div>
        {% endif %}
        
        {% if comparison.ability.get('power_trend') %}
        <div class="comparison-row">
            <div class="metric-label">⚡ 功率</div>
            <div class="metric-values">{{ comparison.ability.power_trend.current|int }}W <span class="vs-badge">VS</span> {{ comparison.ability.power_trend.history_avg|int }}W</div>
            <div class="metric-trend"><span class="trend-badge" style="background:{{ '#e3f2fd' if comparison.ability.power_trend.verdict == '持平' else ('#d4edda' if (comparison.ability.power_trend.diff < 0) == False else '#f8d7da') }};color:{{ '#17a2b8' if comparison.ability.power_trend.verdict == '持平' else ('#155724' if (comparison.ability.power_trend.diff < 0) == False else '#721c24') }};">{{ comparison.ability.power_trend.verdict }}</span></div>
        </div>
        {% endif %}
        {% endif %}
        
        {% if comparison.get('economy') %}
        <h3>跑步经济性</h3>
        {% if comparison.economy.get('vr_trend') %}
        <div class="comparison-row">
            <div class="metric-label">📐 垂直振幅比</div>
            <div class="metric-values">{{ comparison.economy.vr_trend.current|round(1) }}% <span class="vs-badge">VS</span> {{ comparison.economy.vr_trend.history_avg|round(1) }}%</div>
            <div class="metric-trend"><span class="trend-badge" style="background:{{ '#e3f2fd' if comparison.economy.vr_trend.verdict == '持平' else ('#d4edda' if (comparison.economy.vr_trend.diff < 0) == True else '#f8d7da') }};color:{{ '#17a2b8' if comparison.economy.vr_trend.verdict == '持平' else ('#155724' if (comparison.economy.vr_trend.diff < 0) == True else '#721c24') }};">{{ comparison.economy.vr_trend.verdict }}</span></div>
        </div>
        {% endif %}
        {% if comparison.economy.get('hr_pace_ratio') %}
        <div class="comparison-row">
            <div class="metric-label">📊 心率/配速比</div>
            <div class="metric-values">{{ comparison.economy.hr_pace_ratio.current|fmt2 }} <span class="vs-badge">VS</span> {{ comparison.economy.hr_pace_ratio.history_avg|fmt2 }}</div>
            <div class="metric-trend"><span class="trend-badge" style="background:{{ '#e3f2fd' if comparison.economy.hr_pace_ratio.verdict == '持平' else ('#d4edda' if (comparison.economy.hr_pace_ratio.diff < 0) == True else '#f8d7da') }};color:{{ '#17a2b8' if comparison.economy.hr_pace_ratio.verdict == '持平' else ('#155724' if (comparison.economy.hr_pace_ratio.diff < 0) == True else '#721c24') }};">{{ comparison.economy.hr_pace_ratio.verdict }}</span></div>
        </div>
        {% endif %}
        {% endif %}
        
        <p style="text-align:right;color:#999;font-size:12px;margin-top:16px;">有效样本{{ comparison.sample_size }}个</p>
    </div>
    {% endif %}

    {% if findings %}
    <div class="section">
        <h2>🔍 关键发现</h2>
        {% for f in findings %}
        <div class="finding">{{ f }}</div>
        {% endfor %}
    </div>
    {% endif %}

    {% if llm_report %}
    <div class="section">
        <h2>🤖 AI 教练点评</h2>
        <div class="llm-report">{{ llm_report | markdown_to_html | safe }}</div>
    </div>
    {% endif %}

    <div class="footer">
        PowerFun v{{ version }} | 数据来自 Garmin Connect | 生成时间：{{ generated_at }}
    </div>
</div>
</body>
</html>
"""

class AnalysisReportGenerator:
    """深度分析报告生成器"""
    
    ZONE_COLORS = {
        'Z1-有氧基础': _ZONE_COLORS['Z1'],
        'Z2-有氧耐力': _ZONE_COLORS['Z2'],
        'Z3-乳酸阈值': _ZONE_COLORS['Z3'],
        'Z4-无氧耐力': _ZONE_COLORS['Z4'],
        'Z5-最大强度': _ZONE_COLORS['Z5'],
    }
    
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate(self, analysis_data: dict, llm_report: str,
                 lap_pace_chart_html: str = '', lap_hr_chart_html: str = '',
                 lap_count: int = 0) -> str:
        """生成 HTML 报告
        
        Args:
            analysis_data: DeepRunAnalyzer.analyze() 返回的结果
            llm_report: LLM 生成的文字报告
            lap_pace_chart_html: 分圈配速图表 HTML（可选）
            lap_hr_chart_html: 分圈心率图表 HTML（可选）
            lap_count: 分圈数量（可选）
            
        Returns:
            HTML 文件路径
        """
        summary = analysis_data.get('summary', {})
        intensity = analysis_data.get('intensity', {})
        efficiency = analysis_data.get('efficiency', {})
        comparison = analysis_data.get('comparison', {})
        findings = analysis_data.get('findings', [])
        raw = analysis_data.get('raw_data', {})
        
        context = {
            'date': raw.get('date', ''),
            'category_name': raw.get('category_name', '跑步'),
            'distance_km': f"{raw.get('distance_km', 0):.1f}",
            'duration_min': f"{raw.get('duration_min', 0):.0f}",
            'dominant_zone': summary.get('dominant_zone', '未知'),
            'zone_pct': summary.get('zone_pct', {}),
            'zone_colors': self.ZONE_COLORS,
            'avg_hr': f"{raw.get('avg_hr', 0):.0f}",
            'max_hr': f"{raw.get('max_hr', 0):.0f}",
            'avg_power': f"{raw.get('avg_power', 0):.0f}",
            'max_power': f"{raw.get('max_power', 0):.0f}",
            'cadence': f"{raw.get('cadence', 0):.0f}",
            'stride_length': f"{raw.get('stride_length_cm', 0):.0f}",
            'vertical_ratio': f"{raw.get('vertical_ratio_pct', 0):.1f}",
            'ground_contact': f"{raw.get('ground_contact_ms', 0):.0f}",
            'aerobic_te': f"{raw.get('aerobic_te', 0):.1f}",
            'anaerobic_te': f"{raw.get('anaerobic_te', 0):.1f}",
            'calories': f"{raw.get('calories', 0):.0f}",
            'bmr_calories': f"{raw.get('bmr_calories', 0):.0f}",
            'total_calories': f"{raw.get('calories', 0) + raw.get('bmr_calories', 0):.0f}",
            'hr_zone_pct': intensity.get('hr_zone_pct', {}),
            'hr_zone_ranges': analysis_data.get('hr_zone_ranges', {}),
            'cadence_eval': efficiency.get('cadence_eval', ''),
            'cadence_eval_class': self._eval_class(efficiency.get('cadence_eval', '')),
            'vr_eval': efficiency.get('vertical_ratio_eval', ''),
            'vr_eval_class': self._eval_class(efficiency.get('vertical_ratio_eval', '')),
            'gct_eval': efficiency.get('ground_contact_eval', ''),
            'gct_eval_class': self._eval_class(efficiency.get('ground_contact_eval', '')),
            'comparison': comparison,
            'findings': findings,
            'brief_summary': analysis_data.get('brief_summary', ''),
            'llm_report': llm_report if llm_report and '未配置' not in llm_report and '失败' not in llm_report else '',
            'lap_pace_chart_html': lap_pace_chart_html,
            'lap_hr_chart_html': lap_hr_chart_html,
            'lap_count': lap_count,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'version': _load_version(),
        }
        
        # 使用共享 Environment 编译模板
        template = _env.from_string(ANALYSIS_HTML_TEMPLATE)
        html = template.render(**context)
        
        # 文件名：run_analysis_{YYYYMMDD}.html
        date_str = raw.get('date', '').replace('-', '')  # Convert YYYY-MM-DD to YYYYMMDD
        if not date_str:
            # 如果无法获取日期，则使用activity_id或当前时间
            activity_id = raw.get('activity_id', datetime.now().strftime('%Y%m%d%H%M'))
            date_str = activity_id
        html_path = self.output_dir / f"run_analysis_{date_str}.html"
        html_path.write_text(html, encoding='utf-8')
        
        logger.info(f"深度分析报告已生成: {html_path}")
        return str(html_path)
    
    def _eval_class(self, eval_text: str) -> str:
        mapping = {'优秀': 'excellent', '良好': 'good', '一般': 'normal'}
        return mapping.get(eval_text, 'poor')


