"""
可视化模块
使用Plotly生成交互式图表
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from typing import Dict, List
from datetime import datetime, timedelta
import logging
import json

from src.config import ZONE_COLORS as _ZONE_COLORS

logger = logging.getLogger(__name__)


class ChartGenerator:
    """图表生成器"""

    HR_ZONE_COLORS = {
        'Z1-有氧基础': _ZONE_COLORS['Z1'],
        'Z2-有氧耐力': _ZONE_COLORS['Z2'],
        'Z3-乳酸阈值': _ZONE_COLORS['Z3'],
        'Z4-无氧耐力': _ZONE_COLORS['Z4'],
        'Z5-最大强度': _ZONE_COLORS['Z5'],
    }

    CATEGORY_COLORS = {
        'easy_run': '#808080',
        'aerobic_run': '#87CEEB',
        'lsd': '#4169E1',
        'full_marathon': '#FFD700',
        'half_marathon': '#FFD700',
        'race_event': '#FFD700'
    }

    CAT_NAME_MAP = {
        'easy_run': '轻松跑',
        'aerobic_run': '有氧耐力',
        'lsd': 'LSD',
        'full_marathon': '比赛',
        'half_marathon': '比赛',
        'race_event': '比赛'
    }

    def __init__(self, max_points: int = 50):
        self.max_points = max_points
        # 公共布局样式
        self._common_layout_style = {
            'template': 'plotly_white',
            'legend': dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5)
        }

    def _to_js_dict(self, fig_dict: Dict) -> Dict:
        """将Plotly字典转换为可JSON序列化的字典"""
        return json.loads(json.dumps(fig_dict, default=lambda x: x.tolist() if hasattr(x, 'tolist') else str(x) if isinstance(x, pd.Timestamp) else x))

    def _format_pace(self, seconds) -> str:
        """将秒数转换为分:秒格式"""
        if seconds is None:
            return "--:--"
        minutes = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{minutes}:{secs:02d}"

    def _get_recent_months(self, df: pd.DataFrame, months: int = 12) -> pd.DataFrame:
        """获取最近N个月的数据"""
        if df.empty or 'year_month' not in df.columns:
            return df

        unique_months = sorted(df['year_month'].unique())
        if len(unique_months) > months:
            recent_months = unique_months[-months:]
            return df[df['year_month'].isin(recent_months)]
        return df

    def create_pace_hr_trend_chart(self, df: pd.DataFrame) -> Dict:
        """
        创建配速-心率趋势图
        - 横轴刻度竖排显示
        - 鼠标悬停配速显示为分:秒格式
        - 按钮放到图表外面
        """
        if df.empty:
            return {}

        df = df.copy().sort_values('date')
        df['date_str'] = df['date'].dt.strftime('%m-%d')

        # 计算各时间范围
        now = datetime.now()
        ts_3m = now - timedelta(days=90)
        ts_6m = now - timedelta(days=180)
        ts_1y = now - timedelta(days=365)
        ts_ytd = datetime(now.year, 1, 1)

        # 筛选各时间范围的数据
        df_all = df
        df_1y = df[df['date'] >= ts_1y]
        df_ytd = df[df['date'] >= ts_ytd]
        df_6m = df[df['date'] >= ts_6m]
        df_3m = df[df['date'] >= ts_3m]

        time_ranges = {
            'all': df_all,
            '1y': df_1y,
            'ytd': df_ytd,
            '6m': df_6m,
            '3m': df_3m
        }

        # 4种类型:轻松跑、有氧耐力、LSD、比赛(合并全马半马赛事)
        cat_list = ['easy_run', 'aerobic_run', 'lsd', 'race']
        date_range_list = ['all', '1y', 'ytd', '6m', '3m']

        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # 为每个(类型,日期范围)组合创建2个trace(配速+心率)
        for cat in cat_list:
            if cat == 'race':
                color = '#FFD700'
                cat_name = '比赛'
            else:
                color = self.CATEGORY_COLORS.get(cat, '#4169E1')
                cat_name = self.CAT_NAME_MAP.get(cat, cat)

            for date_range in date_range_list:
                range_df = time_ranges[date_range]

                if cat == 'race':
                    cat_df = range_df[range_df['category'].isin(['full_marathon', 'half_marathon', 'race_event'])]
                else:
                    cat_df = range_df[range_df['category'] == cat]

                # 默认显示:轻松跑 + 全部
                is_visible = (cat == 'easy_run' and date_range == 'all')

                if len(cat_df) > 0:
                    # 添加配速格式化列
                    cat_df = cat_df.copy()
                    cat_df['pace_fmt'] = cat_df['avg_pace_sec'].apply(self._format_pace)

                    # 配速曲线 - hover显示分:秒格式
                    fig.add_trace(go.Scatter(
                        x=cat_df['date'].tolist(),
                        y=cat_df['avg_pace_sec'].tolist(),
                        mode='lines+markers',
                        name=f"{cat_name}",
                        line=dict(color=color, width=2),
                        line_shape='spline',
                        marker=dict(size=8, color=color),
                        visible=is_visible,
                        hovertemplate="<b>%{customdata[0]}</b><br>日期: %{customdata[1]}<br>配速: %{customdata[2]}<extra></extra>",
                        customdata=np.stack([cat_df['title'].values, cat_df['date_str'].values, cat_df['pace_fmt'].values], axis=-1)
                    ), secondary_y=False)

                    # 心率曲线
                    fig.add_trace(go.Scatter(
                        x=cat_df['date'].tolist(),
                        y=cat_df['avg_hr'].tolist(),
                        mode='lines+markers',
                        name=f"{cat_name} - 心率",
                        line=dict(color=color, width=2, dash='dash'),
                        line_shape='spline',
                        marker=dict(size=6, color=color, symbol='diamond'),
                        visible=is_visible,
                        hovertemplate="<b>%{customdata}</b><br>日期: %{x}<br>心率: %{y} bpm<extra></extra>",
                        customdata=cat_df['title'].values,
                        showlegend=False
                    ), secondary_y=True)
                else:
                    # 添加空trace保持索引一致
                    fig.add_trace(go.Scatter(x=[], y=[], visible=False), secondary_y=False)
                    fig.add_trace(go.Scatter(x=[], y=[], visible=False, showlegend=False), secondary_y=True)

        total_traces = len(fig.data)
        traces_per_combo = 2

        # 生成指定(类型,日期范围)的visible列表
        def make_visible(cat_idx: int, date_idx: int) -> List[bool]:
            visible = [False] * total_traces
            start_idx = (cat_idx * 5 + date_idx) * traces_per_combo
            visible[start_idx] = True
            visible[start_idx + 1] = True
            return visible

        # 把可见性矩阵作为图表数据的一部分返回
        cat_labels = ['轻松跑', '有氧耐力', 'LSD', '比赛']
        date_labels = ['全部', '近一年', '今年以来', '近半年', '近三个月']

        visibility_matrix = {}
        for cat_idx in range(len(cat_labels)):
            for date_idx in range(len(date_labels)):
                key = f"{cat_idx}_{date_idx}"
                visibility_matrix[key] = make_visible(cat_idx, date_idx)

        fig.update_layout(
            title=None,
            xaxis=dict(
                tickangle=-90,
                type='date',
                tickformat='%m-%d'
            ),
            yaxis=dict(
                title='配速',
                autorange='reversed',
                tickformat='%M:%S',
                tickmode='array',
                tickvals=[315, 330, 345, 360, 375, 390, 405, 420, 435, 450, 465, 480],
                ticktext=['5:15', '5:30', '5:45', '6:00', '6:15', '6:30', '6:45', '7:00', '7:15', '7:30', '7:45', '8:00']
            ),
            **self._common_layout_style,
            yaxis2=dict(title='心率 (bpm)', range=[120, 180]),
            hovermode='x unified',
            height=500,
            margin=dict(l=80, r=60, t=120, b=80),
        )

        fig_dict = fig.to_dict()
        # 把筛选数据放在顶层,不放在 layout 中
        fig_dict['_pace_hr_filter'] = {
            'cat_labels': cat_labels,
            'date_labels': date_labels,
            'visibility_matrix': visibility_matrix
        }

        return self._to_js_dict(fig_dict)

    def create_monthly_volume_chart(self, df: pd.DataFrame) -> Dict:
        """创建月跑量柱状图 - yy-mm格式"""
        if df.empty or 'year_month' not in df.columns:
            return {}

        df_recent = self._get_recent_months(df, 12)
        monthly = df_recent.groupby('year_month')['distance'].sum().reset_index()
        monthly = monthly.sort_values('year_month')

        # 转换为yy-mm格式字符串
        monthly['year_month_str'] = monthly['year_month'].astype(str).apply(
            lambda x: f"{x[2:4]}-{x[5:7]}"
        )

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=monthly['year_month_str'].tolist(),
            y=monthly['distance'].tolist(),
            marker_color='#4169E1',
            opacity=0.8,
            hovertemplate="%{x}: %{y:.1f} km<extra></extra>"
        ))

        fig.update_layout(
            title=None,
            xaxis=dict(tickangle=0, title=None, type='category'),
            yaxis=dict(title='跑量 (km)'),
            height=400,
            **self._common_layout_style
        )

        return self._to_js_dict(fig.to_dict())

    def _prepare_time_ranges(self, df):
        """计算各时间范围数据"""
        now = datetime.now()
        return {
            'all': df,
            '3m': df[df['date'] >= now - timedelta(days=90)],
            '6m': df[df['date'] >= now - timedelta(days=180)],
            'ytd': df[df['date'] >= datetime(now.year, 1, 1)],
            '1y': df[df['date'] >= now - timedelta(days=365)]
        }

    def _create_pie_fig(self, range_data_dict):
        """根据 range_data 创建饼图"""
        fig = go.Figure()

        for range_key in ['all', '3m', '6m', 'ytd', '1y']:
            fig.add_trace(go.Pie(
                labels=range_data_dict[range_key]['labels'],
                values=range_data_dict[range_key]['values'],
                marker_colors=range_data_dict[range_key]['colors'],
                hole=0.4,
                textinfo='label+percent',
                textposition='outside',
                hovertemplate="%{label}<br>%{value:.1f} 分钟<br>%{percent}<extra></extra>",
                visible=(range_key == 'all')
            ))

        fig.update_layout(
            title=None,
            height=400,
            showlegend=False,
            # 增加顶部margin,给按钮留出空间
            margin=dict(l=40, r=40, t=100, b=40),
            template='plotly_white',
            updatemenus=[
                dict(
                    type='buttons',
                    direction='right',
                    x=0.5,
                    y=1.12,  # 放到图表外面
                    xanchor='center',
                    yanchor='bottom',
                    showactive=True,
                    buttons=list([
                        dict(label='全部', method='update', args=[{'visible': [True, False, False, False, False]}]),
                        dict(label='近三个月', method='update', args=[{'visible': [False, True, False, False, False]}]),
                        dict(label='近半年', method='update', args=[{'visible': [False, False, True, False, False]}]),
                        dict(label='今年以来', method='update', args=[{'visible': [False, False, False, True, False]}]),
                        dict(label='近一年', method='update', args=[{'visible': [False, False, False, False, True]}])
                    ])
                )
            ]
        )

        return fig

    def create_hr_zone_pie_chart(self, df: pd.DataFrame) -> Dict:
        """创建心率分布饼图(带时间筛选)- 按钮放到图表外面"""
        if df.empty:
            return {}

        # 检查是否有所需的心率区间时长字段
        hr_zone_cols = ['hr_zone_1_sec', 'hr_zone_2_sec', 'hr_zone_3_sec', 'hr_zone_4_sec', 'hr_zone_5_sec']
        if not all(col in df.columns for col in hr_zone_cols):
            # 如果没有API提供的字段,直接返回空字典,不再回退到旧逻辑
            return {}

        # 使用新的API字段
        zone_order = ['Z1-有氧基础', 'Z2-有氧耐力', 'Z3-乳酸阈值', 'Z4-无氧耐力', 'Z5-最大强度']
        zone_names = ['Z1', 'Z2', 'Z3', 'Z4', 'Z5']

        # 准备各时间范围的数据
        date_ranges = self._prepare_time_ranges(df)

        range_data = {}
        for range_key, range_df in date_ranges.items():
            if range_df.empty:
                range_data[range_key] = {'labels': [], 'values': [], 'colors': []}
                continue

            # 对每个时间范围,汇总各区间秒数
            zone_seconds = {
                'Z1': range_df['hr_zone_1_sec'].sum() if 'hr_zone_1_sec' in range_df.columns else 0,
                'Z2': range_df['hr_zone_2_sec'].sum() if 'hr_zone_2_sec' in range_df.columns else 0,
                'Z3': range_df['hr_zone_3_sec'].sum() if 'hr_zone_3_sec' in range_df.columns else 0,
                'Z4': range_df['hr_zone_4_sec'].sum() if 'hr_zone_4_sec' in range_df.columns else 0,
                'Z5': range_df['hr_zone_5_sec'].sum() if 'hr_zone_5_sec' in range_df.columns else 0,
            }

            # 过滤值为 0 的区间
            filtered_zones = {k: v for k, v in zone_seconds.items() if v > 0}

            # 秒转分钟
            zone_minutes = {k: v / 60.0 for k, v in filtered_zones.items()}

            # 构建标签、值和颜色列表
            labels = []
            values = []
            colors = []

            for i, zone_name in enumerate(zone_names):
                if zone_name in zone_minutes:
                    labels.append(zone_order[i])  # Z1-有氧基础, Z2-有氧耐力, ...
                    values.append(zone_minutes[zone_name])
                    colors.append(self.HR_ZONE_COLORS[zone_order[i]])

            range_data[range_key] = {
                'labels': labels,
                'values': values,
                'colors': colors
            }

        fig = self._create_pie_fig(range_data)

        return self._to_js_dict(fig.to_dict())

    def create_category_pie_chart(self, df: pd.DataFrame) -> Dict:
        """创建跑分类别分布饼图(带时间筛选)- 按钮放到图表外面"""
        if df.empty or 'category' not in df.columns:
            return {}

        now = datetime.now()
        date_ranges = {
            'all': df,
            '3m': df[df['date'] >= now - timedelta(days=90)],
            '6m': df[df['date'] >= now - timedelta(days=180)],
            'ytd': df[df['date'] >= datetime(now.year, 1, 1)],
            '1y': df[df['date'] >= now - timedelta(days=365)]
        }

        range_data = {}
        for range_key, range_df in date_ranges.items():
            if range_df.empty:
                range_data[range_key] = {'labels': [], 'values': [], 'colors': []}
                continue

            cat_data = range_df.groupby(['category', 'category_name', 'category_color']).size().reset_index(name='count')

            range_data[range_key] = {
                'labels': cat_data['category_name'].tolist(),
                'values': cat_data['count'].tolist(),
                'colors': cat_data['category_color'].tolist()
            }

        fig = go.Figure()

        for range_key in ['all', '3m', '6m', 'ytd', '1y']:
            fig.add_trace(go.Pie(
                labels=range_data[range_key]['labels'],
                values=range_data[range_key]['values'],
                marker_colors=range_data[range_key]['colors'],
                hole=0.3,
                textinfo='label+percent',
                textposition='outside',
                hovertemplate="%{label}<br>%{value} 次<br>%{percent}<extra></extra>",
                visible=(range_key == 'all')
            ))

        fig.update_layout(
            title=None,
            height=400,
            showlegend=False,
            # 增加顶部margin,给按钮留出空间
            margin=dict(l=40, r=40, t=100, b=40),
            template='plotly_white',
            updatemenus=[
                dict(
                    type='buttons',
                    direction='right',
                    x=0.5,
                    y=1.12,  # 放到图表外面
                    xanchor='center',
                    yanchor='bottom',
                    showactive=True,
                    buttons=list([
                        dict(label='全部', method='update', args=[{'visible': [True, False, False, False, False]}]),
                        dict(label='近三个月', method='update', args=[{'visible': [False, True, False, False, False]}]),
                        dict(label='近半年', method='update', args=[{'visible': [False, False, True, False, False]}]),
                        dict(label='今年以来', method='update', args=[{'visible': [False, False, False, True, False]}]),
                        dict(label='近一年', method='update', args=[{'visible': [False, False, False, False, True]}])
                    ])
                )
            ]
        )

        return self._to_js_dict(fig.to_dict())

    def create_hr_zone_stacked_bar(self, df: pd.DataFrame) -> Dict:
        """创建心率区间堆叠柱状图 - yy-mm格式"""
        if df.empty or 'year_month' not in df.columns:
            return {}
        
        # 检查是否有所需的心率区间时长字段
        hr_zone_cols = ['hr_zone_1_sec', 'hr_zone_2_sec', 'hr_zone_3_sec', 'hr_zone_4_sec', 'hr_zone_5_sec']
        if not all(col in df.columns for col in hr_zone_cols):
            # 如果没有API提供的字段，直接返回空字典，不再回退到旧逻辑
            return {}
        
        # 使用新的API字段
        df_recent = self._get_recent_months(df, 12)
        
        # 按 year_month 分组，对 hr_zone_1~5_sec 分别求和
        monthly_hr = df_recent.groupby('year_month').agg({
            'hr_zone_1_sec': 'sum',
            'hr_zone_2_sec': 'sum',
            'hr_zone_3_sec': 'sum',
            'hr_zone_4_sec': 'sum',
            'hr_zone_5_sec': 'sum',
        })
        
        # 秒转分钟：monthly_hr = monthly_hr / 60
        monthly_hr = monthly_hr / 60
        
        # 使用安全映射重命名
        rename_map = {
            'hr_zone_1_sec': 'Z1-有氧基础',
            'hr_zone_2_sec': 'Z2-有氧耐力',
            'hr_zone_3_sec': 'Z3-乳酸阈值',
            'hr_zone_4_sec': 'Z4-无氧耐力',
            'hr_zone_5_sec': 'Z5-最大强度',
        }
        monthly_hr = monthly_hr.rename(columns=rename_map)
        
        pivot_df = monthly_hr
        
        # 转换为yy-mm格式字符串
        x_labels = [f"{str(idx)[2:4]}-{str(idx)[5:7]}" for idx in pivot_df.index]
        
        fig = go.Figure()
        
        for zone in pivot_df.columns:
            color = self.HR_ZONE_COLORS.get(zone, '#999999')
            fig.add_trace(go.Bar(
                name=zone,
                x=x_labels,
                y=pivot_df[zone].tolist(),
                marker_color=color,
                hovertemplate=f"{zone}<br>%{{x}}: %{{y:.1f}} 分钟<extra></extra>"
            ))
        
        fig.update_layout(
            title=None,
            xaxis=dict(tickangle=0, title=None, type='category'),
            yaxis=dict(title='时长 (分钟)'),
            barmode='stack',
            legend_traceorder='reversed',
            height=450,
            **self._common_layout_style
        )
        
        return self._to_js_dict(fig.to_dict())

    def create_distance_trend_chart(self, df: pd.DataFrame) -> Dict:
        """
        创建距离趋势图
        - 散点图 + 移动平均线(x轴使用实际日期,自动按时间排序)
        - 按分类着色
        """
        if df.empty:
            return {}

        df = df.copy().sort_values('date')
        df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')

        fig = go.Figure()

        # 按分类绘制散点
        categories = df['category'].unique() if 'category' in df.columns else ['other']
        cat_color_map = {
            'full_marathon': '#FFD700', 'half_marathon': '#C0C0C0', 'race_event': '#CD7F32',
            'lsd': '#4169E1', 'easy_run': '#808080', 'aerobic_run': '#87CEEB',
            'tempo_run': '#32CD32', 'intensity_run': '#FFA500', 'short_run': '#9370DB',
            'other': '#999999'
        }
        cat_name_map = {
            'full_marathon': '全马', 'half_marathon': '半马', 'race_event': '赛事',
            'lsd': 'LSD', 'easy_run': '轻松跑', 'aerobic_run': '有氧耐力',
            'tempo_run': '马拉松配速', 'intensity_run': '强度训练', 'short_run': '短距离',
            'other': '其他'
        }

        for cat in categories:
            cat_df = df[df['category'] == cat]
            if cat_df.empty:
                continue
            color = cat_color_map.get(cat, '#999999')
            name = cat_name_map.get(cat, cat)

            fig.add_trace(go.Scatter(
                x=cat_df['date'].tolist(),
                y=cat_df['distance'].tolist(),
                mode='markers',
                name=name,
                marker=dict(color=color, size=6, symbol='circle'),
                hovertemplate="<b>%{customdata[0]}</b><br>日期: %{customdata[1]}<br>距离: %{y:.1f} km<extra></extra>",
                customdata=np.stack([cat_df['title'].values, cat_df['date_str'].values], axis=-1)
            ))

        # 移动平均线(窗口=5)
        if len(df) >= 5:
            rolling_avg = df['distance'].rolling(window=5, center=True).mean()
            fig.add_trace(go.Scatter(
                x=df['date'].tolist(),
                y=rolling_avg.tolist(),
                mode='lines',
                name='5次移动平均',
                line=dict(color='#FF6B6B', width=2, dash='dash'),
                hovertemplate="日期: %{x|%Y-%m-%d}<br>移动平均: %{y:.1f} km<extra></extra>"
            ))

        fig.update_layout(
            title=None,
            xaxis=dict(tickangle=-45, title=None, type='date', tickformat='%m-%d'),
            yaxis=dict(title='距离 (km)'),
            height=400,
            hovermode='x unified',
            **self._common_layout_style
        )

        return self._to_js_dict(fig.to_dict())

    def create_training_effect_chart(self, df: pd.DataFrame) -> Dict:
        """
        创建训练效果面积趋势图 + vO2max 趋势线
        - 上线：有氧 + 无氧 总和（平滑折线）
        - 下线：仅有氧效果（平滑折线）
        - 两线之间红色填充（宽度 = 无氧训练占比）
        - 左轴：训练效果评分 3-6，保留三条参考线
        - 右轴：vO2max 趋势线（橙色虚线）
        """
        if df.empty:
            return {}

        # 检查是否有训练效果数据
        has_aerobic = 'aerobic_training_effect' in df.columns and df['aerobic_training_effect'].notna().any()
        has_anaerobic = 'anaerobic_training_effect' in df.columns and df['anaerobic_training_effect'].notna().any()

        if not has_aerobic and not has_anaerobic:
            return {}

        df = df.copy().sort_values('date')

        # 计算有氧 + 无氧总和
        if has_aerobic and has_anaerobic:
            df['total_te'] = df['aerobic_training_effect'] + df['anaerobic_training_effect']
        elif has_aerobic:
            df['total_te'] = df['aerobic_training_effect']
        else:
            df['total_te'] = df['anaerobic_training_effect']

        fig = go.Figure()

        # 计算有氧 + 无氧总和
        # 使用原始数据（不 smoothing）
        total_values = df['total_te'].tolist()
        aerobic_values = df['aerobic_training_effect'].tolist()

        # 上线：有氧 + 无氧（填充到下线）
        fig.add_trace(go.Scatter(
            x=df['date'].tolist(),
            y=total_values,
            mode='lines',
            name='有氧+无氧',
            fill=None,
            line=dict(color='#FF6B6B', width=2, shape='spline'),
            hovertemplate="<b>%{customdata}</b><br>日期: %{x|%Y-%m-%d}<br>有氧+无氧: %{y:.1f}<extra></extra>",
            customdata=df['title'].values
        ))

        # 下线：有氧效果（填充到上线，形成区域）
        fig.add_trace(go.Scatter(
            x=df['date'].tolist(),
            y=aerobic_values,
            mode='lines',
            name='有氧效果',
            fill='tonexty',
            fillcolor='rgba(255, 107, 107, 0.25)',
            line=dict(color='#4169E1', width=2, shape='spline'),
            hovertemplate="<b>%{customdata}</b><br>日期: %{x|%Y-%m-%d}<br>有氧效果: %{y:.1f}<extra></extra>",
            customdata=df['title'].values
        ))

        # vO2max 趋势线（右轴）
        has_vo2 = 'vO2_max' in df.columns and df['vO2_max'].notna().any()
        if has_vo2:
            vo2_values = df['vO2_max'].fillna(0).tolist()
            if len(df) >= 3:
                vo2_smooth = df['vO2_max'].rolling(window=5, center=True, min_periods=1).mean().tolist()
            else:
                vo2_smooth = vo2_values
            fig.add_trace(go.Scatter(
                x=df['date'].tolist(),
                y=vo2_smooth,
                mode='lines',
                name='VO2max',
                yaxis='y2',
                line=dict(color='#2ECC71', width=2, dash='dash', shape='spline'),
                hovertemplate="<b>%{customdata}</b><br>日期: %{x|%Y-%m-%d}<br>VO2max: %{y:.0f}<extra></extra>",
                customdata=df['title'].values
            ))

        # 添加参考线（Garmin 官方 TE 标准）
        fig.add_hline(y=3.0, line_dash="dot", line_color="#cccccc",
                      annotation_text="提升体能")
        fig.add_hline(y=4.0, line_dash="dot", line_color="#999999",
                      annotation_text="高度提升")
        fig.add_hline(y=5.0, line_dash="dot", line_color="#FF6B6B",
                      annotation_text="过度训练")

        # 配置双 Y 轴
        if has_vo2:
            vo2_min = float(df['vO2_max'].min())
            vo2_max = float(df['vO2_max'].max())
            y2_range = [int(vo2_min - 1), int(vo2_max + 1)]
            fig.update_layout(
                yaxis2=dict(
                    title=dict(text='VO2max', font=dict(color='#2ECC71')),
                    side='right',
                    overlaying='y',
                    range=y2_range,
                    showgrid=False,
                    tickfont=dict(color='#2ECC71'),
                )
            )

        fig.update_layout(
            title=None,
            xaxis=dict(tickangle=-45, title=None, type='date', tickformat='%Y-%m'),
            yaxis=dict(title='训练效果评分', range=[3, 8.5]),
            height=400,
            hovermode='x unified',
            **self._common_layout_style
        )

        return self._to_js_dict(fig.to_dict())

    def create_power_distribution_chart(self, df: pd.DataFrame) -> Dict:
        """
        创建功率分布图
        - 直方图 + 核密度估计
        - 仅在有功率数据时显示
        """
        if df.empty or 'avg_power' not in df.columns or df['avg_power'].notna().sum() < 2:
            return {}

        power_data = df['avg_power'].dropna()

        fig = go.Figure()

        # 直方图
        fig.add_trace(go.Histogram(
            x=power_data.tolist(),
            nbinsx=30,
            name='功率分布',
            marker_color='#4169E1',
            opacity=0.7,
            hovertemplate="功率: %{x:.0f} W<br>次数: %{y}<extra></extra>"
        ))

        # 添加统计线
        mean_power = power_data.mean()
        median_power = power_data.median()

        # 平均线（红色虚线）- 靠左
        fig.add_vline(x=mean_power, line_dash="dash", line_color="#FF6B6B")
        fig.add_annotation(
            x=mean_power - 5,   # 向左偏移 5W
            y=0.95,
            yref="paper",
            text=f"平均: {mean_power:.0f}W",
            showarrow=False,
            font=dict(color="#FF6B6B", size=11),
            xanchor="right"
        )

        # 中位数线（绿色点线）- 靠右
        fig.add_vline(x=median_power, line_dash="dot", line_color="#32CD32")
        fig.add_annotation(
            x=median_power + 5,  # 向右偏移 5W
            y=0.95,
            yref="paper",
            text=f"中位数: {median_power:.0f}W",
            showarrow=False,
            font=dict(color="#32CD32", size=11),
            xanchor="left"
        )

        fig.update_layout(
            **self._common_layout_style,
            title=None,
            xaxis=dict(title='平均功率 (W)'),
            yaxis=dict(title='次数'),
            height=400,
            margin=dict(l=60, r=80, t=80, b=60),  # 增加右边和顶部边距
            bargap=0.05,
        )

        return self._to_js_dict(fig.to_dict())

    def create_hr_distribution_histogram(self, df: pd.DataFrame) -> Dict:
        """
        创建心率分布直方图
        - 按心率区间着色
        """
        if df.empty or 'avg_hr' not in df.columns:
            return {}

        hr_data = df['avg_hr'].dropna()
        if len(hr_data) < 5:
            return {}

        zone_colors = {
            'Z1-有氧基础': _ZONE_COLORS['Z1'],
            'Z2-有氧耐力': _ZONE_COLORS['Z2'],
            'Z3-乳酸阈值': _ZONE_COLORS['Z3'],
            'Z4-无氧耐力': _ZONE_COLORS['Z4'],
            'Z5-最大强度': _ZONE_COLORS['Z5'],
        }

        fig = go.Figure()

        # 按区间分堆
        for zone, color in zone_colors.items():
            zone_df = df[df['hr_zone'] == zone]
            if not zone_df.empty:
                fig.add_trace(go.Histogram(
                    x=zone_df['avg_hr'].tolist(),
                    name=zone,
                    marker_color=color,
                    opacity=0.8,
                    hovertemplate=f"{zone}<br>心率: %{{x:.0f}} bpm<br>次数: %{{y}}<extra></extra>"
                ))

        fig.update_layout(
            title=None,
            xaxis=dict(title='平均心率 (bpm)'),
            yaxis=dict(title='次数'),
            barmode='stack',
            height=400,
            bargap=0.05,
            **self._common_layout_style
        )

        return self._to_js_dict(fig.to_dict())

    def generate_all_charts(self, df: pd.DataFrame) -> Dict[str, Dict]:
        """生成所有图表"""
        charts = {}

        try:
            charts['pace_hr_trend'] = self.create_pace_hr_trend_chart(df)
        except Exception as e:
            logger.warning(f"图表生成失败: pace_hr_trend")
            charts['pace_hr_trend'] = {}

        try:
            charts['monthly_volume'] = self.create_monthly_volume_chart(df)
        except Exception as e:
            logger.warning(f"图表生成失败: monthly_volume")
            charts['monthly_volume'] = {}

        try:
            charts['hr_zone_pie'] = self.create_hr_zone_pie_chart(df)
        except Exception as e:
            logger.warning(f"图表生成失败: hr_zone_pie")
            charts['hr_zone_pie'] = {}

        try:
            charts['category_pie'] = self.create_category_pie_chart(df)
        except Exception as e:
            logger.warning(f"图表生成失败: category_pie")
            charts['category_pie'] = {}

        try:
            charts['hr_zone_stacked'] = self.create_hr_zone_stacked_bar(df)
        except Exception as e:
            logger.warning(f"图表生成失败: hr_zone_stacked")
            charts['hr_zone_stacked'] = {}

        try:
            charts['distance_trend'] = self.create_distance_trend_chart(df)
        except Exception as e:
            logger.warning(f"图表生成失败: distance_trend")
            charts['distance_trend'] = {}

        try:
            charts['training_effect'] = self.create_training_effect_chart(df)
        except Exception as e:
            logger.warning(f"图表生成失败: training_effect")
            charts['training_effect'] = {}

        try:
            charts['power_distribution'] = self.create_power_distribution_chart(df)
        except Exception as e:
            logger.warning(f"图表生成失败: power_distribution")
            charts['power_distribution'] = {}

        try:
            charts['hr_distribution'] = self.create_hr_distribution_histogram(df)
        except Exception as e:
            logger.warning(f"图表生成失败: hr_distribution")
            charts['hr_distribution'] = {}

        return charts
    
    def _compute_total_km(self, lap_data: list[dict]) -> int:
        """根据分圈数据计算总距离，向下取整为整数KM"""
        total_m = sum(lap.get('distance_m', 0) for lap in lap_data)
        return int(total_m // 1000)

    def generate_lap_pace_chart_v2(self, lap_data: list[dict], recent_laps: list[list[dict]],
                                    cat_name: str = '') -> str:
        """生成分圈配速对比图表（独立配速图）
        
        Args:
            lap_data: 本次分圈数据列表
            recent_laps: 前 N 次同类型分圈数据列表
            cat_name: 跑步类型名称
        
        Returns:
            Plotly 图表的 JSON 字符串
        """
        try:
            if not lap_data:
                return json.dumps({})
            
            current = sorted(lap_data, key=lambda x: x.get('lap_index', 0))
            
            # 需求 2：距离取整，只显示到 total_km
            total_km = self._compute_total_km(lap_data)
            if total_km <= 0:
                return json.dumps({})
            
            # 只取 1~total_km 的分圈数据
            current = [lap for lap in current if 1 <= lap.get('lap_index', 0) <= total_km]
            if not current:
                return json.dumps({})
            
            x_km = [lap.get('lap_index', i + 1) for i, lap in enumerate(current)]
            pace_values = [lap.get('pace_sec_per_km', 0) for lap in current]
            pace_fmt = [self._format_pace(p) for p in pace_values]
            
            fig = go.Figure()
            
            # 本次配速曲线
            fig.add_trace(go.Scatter(
                x=x_km,
                y=pace_values,
                mode='lines+markers',
                name='本次配速',
                line=dict(color='#4169E1', width=3, shape='spline'),
                marker=dict(size=8, color='#4169E1'),
                hovertemplate='公里 %{x}<br>配速: %{customdata}/KM<extra></extra>',
                customdata=pace_fmt,
            ))
            
            # 需求 3：历史数据处理——同一 KM 序号，只使用有数据的记录计算
            if recent_laps:
                hist_avg_pace, hist_max_pace, hist_min_pace = [], [], []
                
                for lap_idx in range(1, total_km + 1):
                    paces = []
                    for run_laps in recent_laps:
                        for rl in run_laps:
                            if rl.get('lap_index') == lap_idx:
                                p = rl.get('pace_sec_per_km', 0)
                                if p > 0:
                                    paces.append(p)
                    
                    if paces:
                        hist_avg_pace.append(sum(paces) / len(paces))
                        hist_max_pace.append(max(paces))
                        hist_min_pace.append(min(paces))
                    else:
                        hist_avg_pace.append(None)
                        hist_max_pace.append(None)
                        hist_min_pace.append(None)
                
                hist_x = list(range(1, total_km + 1))
                
                # 历史平均配速（灰色虚线）
                fig.add_trace(go.Scatter(
                    x=hist_x,
                    y=hist_avg_pace,
                    mode='lines',
                    name='历史均配速',
                    line=dict(color='#999999', width=2, dash='dash', shape='spline'),
                    hovertemplate='公里 %{x}<br>历史均配速: %{customdata}/KM<extra></extra>',
                    customdata=[self._format_pace(v) if v is not None else '--' for v in hist_avg_pace],
                ))
                
                # 填充区域：历史最高 vs 最低配速区间
                fig.add_trace(go.Scatter(
                    x=hist_x + hist_x[::-1],
                    y=[v if v is not None else 0 for v in hist_max_pace] +
                      [v if v is not None else 0 for v in hist_min_pace[::-1]],
                    fill='toself',
                    fillcolor='rgba(65, 105, 225, 0.15)',
                    line=dict(color='rgba(255,255,255,0)'),
                    name='历史配速区间',
                    hoverinfo='skip',
                    showlegend=True,
                ))
            
            # 需求 1：Y 轴使用自定义 ticktext 显示 X:XX/KM 格式
            valid_paces = [p for p in pace_values if p > 0]
            max_pace = max(valid_paces) if valid_paces else 420
            min_pace = min(valid_paces) if valid_paces else 300
            y_padding = (max_pace - min_pace) * 0.15 if max_pace > min_pace else 15
            
            # 生成 Y 轴刻度（以 15 秒为间隔），确保范围覆盖所有刻度
            tick_start = int((min_pace - y_padding) // 15) * 15
            tick_end = int((max_pace + y_padding) // 15 + 1) * 15
            tick_vals = list(range(tick_start, tick_end + 1, 15))
            tick_texts = [self._format_pace(v) for v in tick_vals]
            
            fig.update_layout(
                title=None,
                xaxis=dict(
                    title='公里',
                    range=[0.5, total_km + 0.5],  # 横轴从1开始，避免从0开始显示多余刻度
                    tickmode='linear',
                    tick0=1,
                    dtick=1,
                    ticktext=[f'{k}KM' for k in range(1, total_km + 1)],
                    tickvals=list(range(1, total_km + 1)),
                ),
                yaxis=dict(
                    title='配速',
                    autorange='reversed',  # 配速越小越快，反转 Y 轴
                    tickmode='array',
                    tickvals=tick_vals,
                    ticktext=tick_texts,
                    range=[max_pace + y_padding, max(min_pace - y_padding, 0)],
                ),
                height=450,
                hovermode='x unified',
                **self._common_layout_style,
            )
            
            fig_dict = self._to_js_dict(fig.to_dict())
            return json.dumps(fig_dict, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"分圈配速图表生成失败: {e}")
            return json.dumps({})

    def generate_lap_hr_chart(self, lap_data: list[dict], recent_laps: list[list[dict]],
                               cat_name: str = '') -> str:
        """生成分圈心率对比图表（独立心率图）
        
        Args:
            lap_data: 本次分圈数据列表
            recent_laps: 前 N 次同类型分圈数据列表
            cat_name: 跑步类型名称
        
        Returns:
            Plotly 图表的 JSON 字符串
        """
        try:
            if not lap_data:
                return json.dumps({})
            
            current = sorted(lap_data, key=lambda x: x.get('lap_index', 0))
            
            # 距离取整，与配速图保持一致
            total_km = self._compute_total_km(lap_data)
            if total_km <= 0:
                return json.dumps({})
            
            # 只取 1~total_km 的分圈数据
            current = [lap for lap in current if 1 <= lap.get('lap_index', 0) <= total_km]
            if not current:
                return json.dumps({})
            
            x_km = [lap.get('lap_index', i + 1) for i, lap in enumerate(current)]
            hr_values = [lap.get('avg_hr') for lap in current]
            
            fig = go.Figure()
            
            # 本次心率曲线
            fig.add_trace(go.Scatter(
                x=x_km,
                y=hr_values,
                mode='lines+markers',
                name='本次心率',
                line=dict(color='#FF6B6B', width=3, shape='spline'),
                marker=dict(size=8, color='#FF6B6B'),
                hovertemplate='公里 %{x}<br>心率: %{y:.0f} bpm<extra></extra>',
            ))
            
            # 历史心率数据——同一 KM 序号，只使用有数据的记录计算
            if recent_laps:
                hist_avg_hr, hist_max_hr, hist_min_hr = [], [], []
                
                for lap_idx in range(1, total_km + 1):
                    hrs = []
                    for run_laps in recent_laps:
                        for rl in run_laps:
                            if rl.get('lap_index') == lap_idx:
                                h = rl.get('avg_hr')
                                if h is not None and h > 0:
                                    hrs.append(h)
                    
                    if hrs:
                        hist_avg_hr.append(sum(hrs) / len(hrs))
                        hist_max_hr.append(max(hrs))
                        hist_min_hr.append(min(hrs))
                    else:
                        hist_avg_hr.append(None)
                        hist_max_hr.append(None)
                        hist_min_hr.append(None)
                
                hist_x = list(range(1, total_km + 1))
                
                # 历史平均心率（灰色虚线）
                fig.add_trace(go.Scatter(
                    x=hist_x,
                    y=hist_avg_hr,
                    mode='lines',
                    name='历史均心率',
                    line=dict(color='#999999', width=2, dash='dash', shape='spline'),
                    hovertemplate='公里 %{x}<br>历史均心率: %{y:.0f} bpm<extra></extra>',
                ))
                
                # 填充区域：历史最高 vs 最低心率区间
                fig.add_trace(go.Scatter(
                    x=hist_x + hist_x[::-1],
                    y=[v if v is not None else 0 for v in hist_max_hr] +
                      [v if v is not None else 0 for v in hist_min_hr[::-1]],
                    fill='toself',
                    fillcolor='rgba(255, 107, 107, 0.15)',
                    line=dict(color='rgba(255,255,255,0)'),
                    name='历史心率区间',
                    hoverinfo='skip',
                    showlegend=True,
                ))
            
            # Y 轴范围：取实际数据的 ±5%
            all_hr_values = [h for h in hr_values if h is not None and h > 0]
            if recent_laps:
                for run_laps in recent_laps:
                    for rl in run_laps:
                        h = rl.get('avg_hr')
                        if h is not None and h > 0:
                            all_hr_values.append(h)
            
            if all_hr_values:
                hr_min = min(all_hr_values)
                hr_max = max(all_hr_values)
                hr_padding = (hr_max - hr_min) * 0.05
                hr_range = [max(hr_min - hr_padding, 60), hr_max + hr_padding]
            else:
                hr_range = [100, 200]
            
            fig.update_layout(
                title=None,
                xaxis=dict(
                    title='公里',
                    range=[0.5, total_km + 0.5],  # 横轴从1开始
                    tickmode='linear',
                    tick0=1,
                    dtick=1,
                    ticktext=[f'{k}KM' for k in range(1, total_km + 1)],
                    tickvals=list(range(1, total_km + 1)),
                ),
                yaxis=dict(
                    title='心率 (bpm)',
                    range=hr_range,
                ),
                height=450,
                hovermode='x unified',
                **self._common_layout_style,
            )
            
            fig_dict = self._to_js_dict(fig.to_dict())
            return json.dumps(fig_dict, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"分圈心率图表生成失败: {e}")
            return json.dumps({})
