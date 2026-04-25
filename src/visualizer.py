"""PowerFun 可视化模块

基于 Plotly 生成交互式图表。
"""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)


class RunningVisualizer:
    """跑步数据可视化器"""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir or '.')
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def create_dashboard(self, df: pd.DataFrame, analysis: dict) -> go.Figure:
        """创建综合仪表盘

        Args:
            df: 标准化数据
            analysis: 分析结果

        Returns:
            Plotly Figure 对象
        """
        # 4 行 2 列子图布局
        fig = make_subplots(
            rows=4, cols=2,
            subplot_titles=(
                '📈 距离趋势', '⏱️ 配速趋势',
                '📊 月度跑量', '❤️ 心率分布',
                '🏃 配速分布', '📉 心率区间',
            ),
            specs=[
                [{'secondary_y': True}, {'secondary_y': True}],
                [{'type': 'bar'}, {'type': 'bar'}],
                [{'type': 'histogram'}, {'type': 'pie'}],
                [None, None],  # 预留
            ],
            vertical_spacing=0.08,
            horizontal_spacing=0.1,
        )

        # Row 1: 距离 & 配速趋势
        self._add_distance_trend(fig, df, row=1, col=1)
        self._add_pace_trend(fig, df, row=1, col=2)

        # Row 2: 月度跑量 & 心率分布
        if 'monthly' in analysis:
            self._add_monthly_bar(fig, analysis['monthly'], row=2, col=1)
        self._add_hr_scatter(fig, df, row=2, col=2)

        # Row 3: 配速分布 & 心率区间
        self._add_pace_histogram(fig, df, row=3, col=1)
        if 'hr_zones' in analysis and 'error' not in analysis['hr_zones']:
            self._add_hr_zone_pie(fig, analysis['hr_zones'], row=3, col=2)

        fig.update_layout(
            height=1200,
            title_text="🏃 PowerFun 跑步数据分析报告",
            title_x=0.5,
            template='plotly_white',
            font=dict(family='PingFang SC, Microsoft YaHei, sans-serif'),
            showlegend=False,
        )

        return fig

    def _add_distance_trend(self, fig, df: pd.DataFrame, row, col):
        """距离趋势图"""
        if df.empty:
            return

        fig.add_trace(
            go.Scatter(
                x=df['date'],
                y=df['distance'],
                mode='lines+markers',
                name='距离',
                line=dict(color='#3498db', width=2),
                marker=dict(size=5),
                hovertemplate='日期: %{x|%Y-%m-%d}<br>距离: %{y:.2f} km<br><extra></extra>',
            ),
            row=row, col=col,
        )

        # 累计距离
        if 'distance' in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df['date'],
                    y=df['distance'].cumsum(),
                    mode='lines',
                    name='累计',
                    line=dict(color='#e74c3c', width=1.5, dash='dash'),
                    yaxis='y2',
                    hovertemplate='日期: %{x|%Y-%m-%d}<br>累计: %{y:.1f} km<br><extra></extra>',
                ),
                row=row, col=col,
                secondary_y=True,
            )

    def _add_pace_trend(self, fig, df: pd.DataFrame, row, col):
        """配速趋势图"""
        if 'pace_min_per_km' not in df.columns or df.empty:
            return

        df_valid = df.dropna(subset=['pace_min_per_km'])
        if df_valid.empty:
            return

        fig.add_trace(
            go.Scatter(
                x=df_valid['date'],
                y=df_valid['pace_min_per_km'],
                mode='lines+markers',
                name='配速',
                line=dict(color='#2ecc71', width=2),
                marker=dict(size=5),
                hovertemplate='日期: %{x|%Y-%m-%d}<br>配速: %{y:.2f} min/km<br><extra></extra>',
            ),
            row=row, col=col,
        )

        # 移动平均
        if len(df_valid) >= 5:
            ma = df_valid['pace_min_per_km'].rolling(window=5, min_periods=3).mean()
            fig.add_trace(
                go.Scatter(
                    x=df_valid['date'],
                    y=ma,
                    mode='lines',
                    name='MA5',
                    line=dict(color='#e67e22', width=2),
                    hovertemplate='日期: %{x|%Y-%m-%d}<br>MA5: %{y:.2f} min/km<br><extra></extra>',
                ),
                row=row, col=col,
            )

    def _add_monthly_bar(self, fig, monthly: pd.DataFrame, row, col):
        """月度跑量柱状图"""
        if monthly.empty:
            return

        fig.add_trace(
            go.Bar(
                x=monthly['year_month'],
                y=monthly['distance_km'],
                name='月跑量',
                marker_color='#3498db',
                hovertemplate='月份: %{x}<br>跑量: %{y:.1f} km<br><extra></extra>',
            ),
            row=row, col=col,
        )

    def _add_hr_scatter(self, fig, df: pd.DataFrame, row, col):
        """心率散点图"""
        if 'avg_hr' not in df.columns or df.empty:
            return

        fig.add_trace(
            go.Scatter(
                x=df['date'],
                y=df['avg_hr'],
                mode='markers',
                name='平均心率',
                marker=dict(
                    size=8,
                    color=df['avg_hr'],
                    colorscale='RdYlGn_r',
                    showscale=True,
                ),
                hovertemplate='日期: %{x|%Y-%m-%d}<br>心率: %{y} bpm<br><extra></extra>',
            ),
            row=row, col=col,
        )

    def _add_pace_histogram(self, fig, df: pd.DataFrame, row, col):
        """配速分布直方图"""
        if 'pace_min_per_km' not in df.columns:
            return

        df_valid = df.dropna(subset=['pace_min_per_km'])
        if df_valid.empty:
            return

        fig.add_trace(
            go.Histogram(
                x=df_valid['pace_min_per_km'],
                nbinsx=20,
                marker_color='#9b59b6',
                hovertemplate='配速区间: %{x:.1f} min/km<br>次数: %{y}<br><extra></extra>',
            ),
            row=row, col=col,
        )

    def _add_hr_zone_pie(self, fig, hr_zones: dict, row, col):
        """心率区间饼图"""
        labels = []
        values = []
        colors = []

        for zone_name, zone_data in hr_zones.items():
            if zone_data['count'] > 0:
                labels.append(zone_name)
                values.append(zone_data['count'])
                colors.append(zone_data['color'])

        if not values:
            return

        fig.add_trace(
            go.Pie(
                labels=labels,
                values=values,
                marker_colors=colors,
                hole=0.4,
                hovertemplate='%{label}: %{value} 次 (%{percent})<extra></extra>',
            ),
            row=row, col=col,
        )

    def save(self, fig: go.Figure, filename: str = 'dashboard.html') -> str:
        """保存图表为 HTML"""
        filepath = self.output_dir / filename
        fig.write_html(
            str(filepath),
            full_html=True,
            include_plotlyjs='cdn',
            config={'displayModeBar': True, 'responsive': True},
        )
        logger.info(f"图表已保存: {filepath}")
        return str(filepath)

    def save_static(self, fig: go.Figure, filename: str = 'dashboard.png',
                    width: int = 1200, height: int = 1200) -> str:
        """保存静态图片 (需要 kaleido)"""
        try:
            filepath = self.output_dir / filename
            fig.write_image(str(filepath), width=width, height=height, scale=2)
            logger.info(f"静态图片已保存: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.warning(f"保存静态图片失败 (安装 kaleido 可启用): {e}")
            return ''
