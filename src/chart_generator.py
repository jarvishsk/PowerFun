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
        'race_event': '#FFD700',
        'race': '#FFD700'
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

                    cat_df = cat_df.copy()
                    cat_df['seq'] = range(1, len(cat_df) + 1)
                    # 配速曲线 - hover显示分:秒格式
                    fig.add_trace(go.Scatter(
                        x=cat_df['seq'].tolist(),
                        y=cat_df['avg_pace_sec'].tolist(),
                        mode='lines+markers',
                        name=f"{cat_name}",
                        line=dict(color=color, width=2),
                        line_shape='spline',
                        marker=dict(size=8, color=color),
                        visible=is_visible,
                        hovertemplate="<b>%{customdata[0]}</b><br>第%{customdata[3]}次<br>日期: %{customdata[1]}<br>配速: %{customdata[2]}<extra></extra>",
                        customdata=np.stack([cat_df['title'].values, cat_df['date_str'].values, cat_df['pace_fmt'].values, cat_df['seq'].astype(str).values], axis=-1)
                    ), secondary_y=False)

                    # 心率曲线
                    fig.add_trace(go.Scatter(
                        x=cat_df['seq'].tolist(),
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

        # 找到最大序列数
        max_seq = df['date'].nunique()
        tick_vals = [1] + list(range(5, max_seq + 5, 5))
        tick_texts = [str(t) for t in tick_vals]

        fig.update_layout(
            title=None,
            xaxis=dict(
                tickangle=0,
                tickmode='array',
                tickvals=tick_vals,
                ticktext=tick_texts,
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
        # 合并全马和半马为同一个跑类
        df = df.copy()
        df.loc[df['category'].isin(['full_marathon', 'half_marathon']), 'category'] = 'race'

        categories = df['category'].unique() if 'category' in df.columns else ['other']
        cat_color_map = {
            'race': '#FFD700',
            'lsd': '#4169E1', 'easy_run': '#808080', 'aerobic_run': '#87CEEB',
            'tempo_run': '#32CD32', 'intensity_run': '#FFA500', 'short_run': '#9370DB',
            'other': '#999999'
        }
        cat_name_map = {
            'race': '比赛',
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

        # 移动平均线(窗口=10)
        if len(df) >= 10:
            rolling_avg = df['distance'].rolling(window=10, center=True).mean()
            fig.add_trace(go.Scatter(
                x=df['date'].tolist(),
                y=rolling_avg.tolist(),
                mode='lines',
                name='10次移动平均',
                line=dict(color='#FF6B6B', width=2, dash='dash'),
                hovertemplate="日期: %{x|%Y-%m-%d}<br>移动平均: %{y:.1f} km<extra></extra>"
            ))

        fig.update_layout(
            title=None,
            xaxis=dict(tickangle=0, title=None, type='date', tickformat='%m-%d'),
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
            xaxis=dict(tickangle=0, title=None, type='date', tickformat='%m-%d'),
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

    def _prepare_temp_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """准备气温+心率+配速的衍生数据"""
        if df.empty:
            return pd.DataFrame()
        temp_df = df.dropna(subset=['min_temperature', 'max_temperature', 'avg_hr', 'avg_pace_sec']).copy()
        if len(temp_df) < 3:
            return pd.DataFrame()
        temp_df['mid_temp'] = (temp_df['min_temperature'] + temp_df['max_temperature']) / 2
        temp_df['pace_min'] = temp_df['avg_pace_sec'] / 60.0
        # 效率 = 时速(m/h) ÷ 心率(bpm) = (3600×1000/配速秒) ÷ 心率 = 3600000 / (配速秒×心率)
        temp_df['hr_pace_ratio'] = 3600000.0 / (temp_df['avg_hr'] * temp_df['avg_pace_sec'])
        return temp_df

    def create_temp_hr_scatter_chart(self, df: pd.DataFrame) -> Dict:
        """
        气温-心率影响分析（双轴时间序列）
        - X 轴：日期（MM-DD 格式）
        - 左 Y 轴：心率配速比
        - 右 Y 轴：气温区间填充
        - 按跑类筛选，默认轻松跑，轻松跑排在最前面
        - 平滑曲线
        """
        temp_df = self._prepare_temp_data(df)
        if temp_df.empty or len(temp_df) < 3:
            return {}

        temp_df = temp_df.copy().sort_values('date')
        temp_df['date_str'] = temp_df['date'].dt.strftime('%m-%d')

        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # 合并全马和半马为同一个跑类（必须在 cat_order 之前）
        temp_df.loc[temp_df['category'].isin(['full_marathon', 'half_marathon']), 'category'] = 'race'

        # 跑类排序：轻松跑排最前
        all_cats = temp_df['category'].unique().tolist()
        cat_order = ['easy_run'] + [c for c in all_cats if c != 'easy_run']

        cat_label_map = {
            'easy_run': '轻松跑',
            'aerobic_run': '有氧耐力跑',
            'lsd': 'LSD长距离',
            'race': '比赛',
        }

        # 为每个跑类独立编号次数序列（按日期排序，该跑类自己的次数）
        # 同时构建气温数据（按日期，需要映射到各跑类的次数序号上）
        daily_temp = temp_df.groupby('date').agg(
            min_temp=('min_temperature', 'min'),
            max_temp=('max_temperature', 'max')
        ).reset_index().sort_values('date')

        for cat in cat_order:
            color = self.CATEGORY_COLORS.get(cat, '#667eea')
            cat_label = cat_label_map.get(cat, cat)
            cat_data = temp_df[temp_df['category'] == cat].sort_values('date').copy()
            is_visible = (cat == 'easy_run')

            if len(cat_data) > 0:
                # 按该跑类自己的日期排序编号（1, 2, 3...）
                cat_data = cat_data.reset_index(drop=True)
                cat_data['cat_seq'] = range(1, len(cat_data) + 1)
                # 把日期映射到气温
                cat_data = cat_data.merge(daily_temp, on='date', how='left')
                fig.add_trace(go.Scatter(
                    x=cat_data['cat_seq'].tolist(),
                    y=cat_data['hr_pace_ratio'].tolist(),
                    mode='lines+markers',
                    name=cat_label,
                    line=dict(color=color, width=2),
                    line_shape='spline',
                    marker=dict(size=6, color=color),
                    visible=is_visible,
                    customdata=list(zip(cat_data['title'], cat_data['date_str'].astype(str), cat_data['distance'].astype(float))),
                    hovertemplate="<b>%{customdata[0]}</b><br>第%{x}次<br>日期: %{customdata[1]}<br>效率: %{y:.0f} (m/h)/bpm<br>距离: %{customdata[2]:.2f} km<extra></extra>"
                ), secondary_y=False)

                # 每个跑类的气温填充（右轴）—— 用该跑类自己的次数序列
                fig.add_trace(go.Scatter(
                    x=cat_data['cat_seq'].tolist(),
                    y=cat_data['max_temp'].tolist(),
                    mode='lines',
                    line=dict(width=0),
                    showlegend=False,
                    yaxis='y2',
                    visible=is_visible,
                    fillcolor='rgba(255, 165, 0, 0.15)',
                    hoverinfo='skip',
                ), secondary_y=True)
                fig.add_trace(go.Scatter(
                    x=cat_data['cat_seq'].tolist(),
                    y=cat_data['min_temp'].tolist(),
                    mode='lines',
                    line=dict(width=0),
                    showlegend=False,
                    yaxis='y2',
                    visible=is_visible,
                    fill='tonexty',
                    fillcolor='rgba(255, 165, 0, 0.15)',
                    hoverinfo='skip',
                ), secondary_y=True)
                fig.add_trace(go.Scatter(
                    x=cat_data['cat_seq'].tolist(),
                    y=cat_data['max_temp'].tolist(),
                    mode='lines',
                    line=dict(color='rgba(255, 140, 0, 0.6)', width=1, dash='dash', shape='spline'),
                    name=f'{cat_label} 最高气温',
                    showlegend=False,
                    visible=is_visible,
                    hovertemplate="第%{x}次<br>最高气温: %{y:.0f}°C<extra></extra>"
                ), secondary_y=True)
                fig.add_trace(go.Scatter(
                    x=cat_data['cat_seq'].tolist(),
                    y=cat_data['min_temp'].tolist(),
                    mode='lines',
                    line=dict(color='rgba(100, 180, 255, 0.6)', width=1, dash='dash', shape='spline'),
                    name=f'{cat_label} 最低气温',
                    showlegend=False,
                    visible=is_visible,
                    hovertemplate="第%{x}次<br>最低气温: %{y:.0f}°C<extra></extra>"
                ), secondary_y=True)
            else:
                fig.add_trace(go.Scatter(x=[], y=[], visible=False), secondary_y=False)

        total_traces = len(fig.data)
        n_cats = len(cat_order)
        traces_per_cat = 5  # pace ratio + 4 temp traces

        cat_labels_display = [cat_label_map.get(c, c) for c in cat_order]

        def make_visible(cat_idx: int) -> List[bool]:
            visible = [False] * total_traces
            start = cat_idx * traces_per_cat
            for j in range(start, min(start + traces_per_cat, total_traces)):
                visible[j] = True
            return visible

        visibility_matrix = {}
        for cat_idx in range(n_cats):
            visibility_matrix[f"{cat_idx}"] = make_visible(cat_idx)

        fig.update_layout(
            title=None,
            xaxis=dict(title='次数', dtick=1),
            yaxis=dict(title='效率 (m/h)/bpm', side='left'),
            yaxis2=dict(
                title='气温 (°C)',
                side='right',
                overlaying='y',
                showgrid=False,
            ),
            height=400,
            **self._common_layout_style
        )
        
        # 设置X轴刻度：1, 5, 10, 15...（取最大跑类次数）
        max_seq = 0
        for cat in cat_order:
            cat_count = len(temp_df[temp_df['category'] == cat])
            if cat_count > max_seq:
                max_seq = cat_count
        tick_vals = [1] + list(range(5, max_seq + 1, 5))
        tick_texts = [str(t) for t in tick_vals]
        fig.update_xaxes(
            tickmode='array',
            tickvals=tick_vals,
            ticktext=tick_texts,
        )

        result = self._to_js_dict(fig.to_dict())
        result['_temp_hr_filter'] = {
            'cat_labels': cat_labels_display,
            'visibility_matrix': visibility_matrix,
        }
        return result

    # ========================================
    # 新增：气温-功率-心率替代分析（3张图）
    # ========================================

    def create_beats_per_km_chart(self, df: pd.DataFrame) -> Dict:
        """
        beats/km 心率成本趋势图
        - 按跑步类型筛选，默认显示轻松跑
        - 横轴：月份均匀分布，同月内多点抖动散开
        - 点按气温着色（蓝=冷，红=热）
        - 右上角标注平均值
        """
        if df.empty:
            return {}

        df = df.copy().sort_values('date')
        df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
        df['year_month'] = df['date'].dt.strftime('%y%m')

        # 合并半马/全马为"比赛"
        race_mask = df['category'].isin(['half_marathon', 'full_marathon', 'race_event'])
        df.loc[race_mask, 'category'] = 'race'
        df.loc[race_mask, 'category_name'] = '比赛'

        # 过滤无效数据
        valid = df[(df['avg_hr'] > 0) & (df['avg_pace_sec'] > 0)].copy()
        if len(valid) < 3:
            return {}

        # 计算 beats/km
        valid['beats_km'] = valid['avg_hr'] * (valid['avg_pace_sec'] / 60.0)

        # 计算气温
        has_temp = 'min_temperature' in valid.columns and 'max_temperature' in valid.columns
        if has_temp:
            temp_mask = valid['min_temperature'].notna() & valid['max_temperature'].notna()
            valid.loc[temp_mask, 'avg_temperature'] = (valid.loc[temp_mask, 'min_temperature'] + valid.loc[temp_mask, 'max_temperature']) / 2

        # 跑类列表
        cat_list = [c for c in ['easy_run', 'aerobic_run', 'lsd', 'race']
                    if c in valid['category'].values]
        cat_names = {'easy_run': '轻松跑', 'aerobic_run': '有氧耐力', 'lsd': 'LSD', 'race': '比赛'}
        cat_colors = {'easy_run': '#808080', 'aerobic_run': '#87CEEB', 'lsd': '#4169E1', 'race': '#FFD700'}

        valid = valid.copy()
        fig = go.Figure()

        # 气温色带范围（全局统一）
        if has_temp and valid['avg_temperature'].notna().any():
            cmin = valid['avg_temperature'].min() - 2
            cmax = valid['avg_temperature'].max() + 2
        else:
            cmin, cmax = 0, 30
            has_temp = False

        # 按分类添加 trace
        for cat in cat_list:
            cat_df = valid[valid['category'] == cat].sort_values('date')
            color = cat_colors.get(cat, '#999999')
            name = cat_names.get(cat, cat)
            is_visible = True

            fig.add_trace(go.Scatter(
                x=cat_df['date'].tolist(),
                y=cat_df['beats_km'].tolist(),
                mode='markers',
                name=name,
                marker=dict(
                    size=6,
                    symbol='circle',
                    color=cat_df['avg_temperature'].tolist() if has_temp else color,
                    colorscale='RdBu_r' if has_temp else None,
                    cmin=cmin if has_temp else None,
                    cmax=cmax if has_temp else None,
                    colorbar=dict(title='气温(°C)', thickness=12, len=0.5) if has_temp else None,
                ),
                visible=is_visible,
                hovertemplate=(
                    '<b>%{customdata[0]}</b><br>'
                    '日期: %{customdata[1]}<br>'
                    '心率: %{customdata[2]:.0f} bpm<br>'
                    '配速: %{customdata[3]}/km<br>'
                    '心率成本: %{y:.0f} beats/km'
                    '%{customdata[4]}'
                    '<extra></extra>'
                ),
                customdata=np.stack([
                    cat_df['title'].values,
                    cat_df['date_str'].values,
                    cat_df['avg_hr'].values.astype(float),
                    [self._format_pace(p) for p in cat_df['avg_pace_sec'].values],
                    [f'<br>气温: {t:.0f}°C' if pd.notna(t) else '' for t in cat_df['avg_temperature'].values],
                ], axis=-1),
            ))

        # 可见性矩阵
        visibility_matrix = {}
        # "全部"：显示所有跑类
        all_vis = [True] * len(cat_list)
        visibility_matrix['all'] = all_vis
        for cat in cat_list:
            vis = [False] * len(cat_list)
            for i, c2 in enumerate(cat_list):
                if c2 == cat:
                    vis[i] = True
            visibility_matrix[cat] = vis

        # 平均值标注
        easy_df = valid[valid['category'] == 'easy_run']
        avg_beats = easy_df['beats_km'].mean() if len(easy_df) > 0 else valid['beats_km'].mean()
        fig.add_annotation(
            x=1.0, y=1.0, xref='paper', yref='paper',
            text=f'Avg: {avg_beats:.0f} beats/km',
            showarrow=False, font=dict(size=12, color='#666'),
            xanchor='right', yanchor='top',
            bgcolor='rgba(255,255,255,0.8)',
            bordercolor='#ccc', borderwidth=1,
        )

        fig.update_layout(
            title=None,
            xaxis=dict(title='日期', tickangle=0, type='date', tickformat='%m-%d'),
            yaxis=dict(title='心率成本 (beats/km)'),
            height=450,
            **self._common_layout_style,
        )

        fig_dict = self._to_js_dict(fig.to_dict())
        fig_dict['_beats_km_filter'] = {
            'cat_labels': ['全部'] + [cat_names.get(c, c) for c in cat_list],
            'cat_keys': ['all'] + cat_list,
            'visibility_matrix': visibility_matrix,
        }
        return fig_dict

    def create_speed_hr_scatter_chart(self, df: pd.DataFrame) -> Dict:
        """
        配速-心率散点图（颜色=气温）
        - 横轴：配速 (min/km)，倒序（左慢右快）
        - 纵轴：心率 (bpm)
        - 颜色编码：连续色带映射气温
        - 趋势线：线性回归（黑色虚线）
        """
        if df.empty:
            return {}

        df = df.copy()

        # 计算配速 (min/km)
        df = df[df['avg_pace_sec'] > 0].copy()
        if df.empty:
            return {}
        df['pace_min_km'] = df['avg_pace_sec'] / 60.0

        # 计算气温
        if 'min_temperature' in df.columns and 'max_temperature' in df.columns:
            df = df[df['min_temperature'].notna() | df['max_temperature'].notna()].copy()
            temp_mask = df['min_temperature'].notna() & df['max_temperature'].notna()
            df.loc[temp_mask, 'avg_temperature'] = (
                df.loc[temp_mask, 'min_temperature'] + df.loc[temp_mask, 'max_temperature']
            ) / 2.0
            only_min = df['min_temperature'].notna() & df['max_temperature'].isna()
            df.loc[only_min, 'avg_temperature'] = df.loc[only_min, 'min_temperature']
            only_max = df['max_temperature'].notna() & df['min_temperature'].isna()
            df.loc[only_max, 'avg_temperature'] = df.loc[only_max, 'max_temperature']
        else:
            return {}

        # 过滤异常值
        valid = df[
            (df['avg_hr'] >= 60) &
            (df['pace_min_km'] >= 4) &
            (df['pace_min_km'] <= 12) &
            (df['avg_temperature'].notna())
        ].copy()

        if len(valid) < 5:
            return {}

        df = valid
        df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')

        fig = go.Figure()

        # hover 信息
        hover_texts = []
        for _, row in df.iterrows():
            power_info = f"<br>功率: {row['avg_power']:.0f} W" if pd.notna(row.get('avg_power')) else ''
            hover_texts.append(
                f"<b>{row.get('title', '')}</b><br>"
                f"日期: {row['date_str']}<br>"
                f"配速: {self._format_pace(row['avg_pace_sec'])}/km<br>"
                f"心率: {row['avg_hr']:.0f} bpm<br>"
                f"气温: {row['avg_temperature']:.0f}°C"
                f"{power_info}"
            )

        # 色带范围：min/max 温度 ±2°C
        temp_min = df['avg_temperature'].min()
        temp_max = df['avg_temperature'].max()
        cmin = temp_min - 2
        cmax = temp_max + 2

        fig.add_trace(go.Scatter(
            x=df['pace_min_km'].tolist(),
            y=df['avg_hr'].tolist(),
            mode='markers',
            marker=dict(
                size=10,
                color=df['avg_temperature'].tolist(),
                colorscale='RdBu_r',
                cmin=cmin,
                cmax=cmax,
                opacity=0.75,
                colorbar=dict(title='气温(°C)', thickness=15, len=0.75),
                symbol='circle',
            ),
            text=hover_texts,
            hoverinfo='text',
            name='数据点',
        ))

        # 线性回归趋势线（黑色虚线）
        x_vals = df['pace_min_km'].values
        y_vals = df['avg_hr'].values
        if len(x_vals) >= 3:
            coeffs = np.polyfit(x_vals, y_vals, 1)
            x_range = np.linspace(x_vals.min(), x_vals.max(), 50)
            y_fit = coeffs[0] * x_range + coeffs[1]
            fig.add_trace(go.Scatter(
                x=x_range.tolist(),
                y=y_fit.tolist(),
                mode='lines',
                name='趋势线',
                line=dict(color='#333333', width=2, dash='dash'),
                hoverinfo='skip',
                showlegend=True,
            ))

        # 动态配速范围（±5秒 = ±0.083分）
        pace_min = df['pace_min_km'].min()
        pace_max = df['pace_min_km'].max()
        pad = 5.0 / 60.0  # 5秒
        pace_lo = pace_max + pad  # 最慢+5秒
        pace_hi = pace_min - pad  # 最快-5秒

        fig.update_layout(
            title=None,
            xaxis=dict(
                title='配速 (min/km)',
                range=[pace_lo, pace_hi],  # 左慢右快
            ),
            yaxis=dict(title='心率 (bpm)'),
            height=450,
            **self._common_layout_style,
        )

        return self._to_js_dict(fig.to_dict())

    def create_speed_hr_temp_curves(self, df: pd.DataFrame) -> Dict:
        """
        配速-心率温度分层曲线
        - 按温度分组，每组一条趋势线
        - 横轴：配速 (min/km)，倒序（左慢右快）
        - 纵轴：心率 (bpm)
        """
        if df.empty:
            return {}

        df = df.copy()

        # 计算配速
        df = df[df['avg_pace_sec'] > 0].copy()
        if df.empty:
            return {}
        df['pace_min_km'] = df['avg_pace_sec'] / 60.0

        # 计算气温
        if 'min_temperature' in df.columns and 'max_temperature' in df.columns:
            temp_mask = df['min_temperature'].notna() & df['max_temperature'].notna()
            df = df[temp_mask].copy()
            df['avg_temperature'] = (df['min_temperature'] + df['max_temperature']) / 2.0
        else:
            return {}

        # 过滤异常值
        df = df[
            (df['avg_hr'] >= 60) &
            (df['pace_min_km'] >= 4) &
            (df['pace_min_km'] <= 12)
        ].copy()

        if df.empty:
            return {}

        # 温度分组
        bins = [
            (-float('inf'), 15, '<15°C 冷'),
            (15, 20, '15-20°C 凉爽'),
            (20, 25, '20-25°C 适中'),
            (25, 30, '25-30°C 热'),
            (30, float('inf'), '30°C+ 酷热'),
        ]
        temp_group_colors = {
            '<15°C 冷': '#1E90FF',
            '15-20°C 凉爽': '#4169E1',
            '20-25°C 适中': '#32CD32',
            '25-30°C 热': '#FF8C00',
            '30°C+ 酷热': '#FF4500',
        }

        df['temp_group'] = pd.cut(df['avg_temperature'], bins=[b[0] for b in bins] + [bins[-1][1]], labels=[b[2] for b in bins], include_lowest=True)

        # 统计各组样本数
        group_counts = df.groupby('temp_group', observed=True).size()

        # 只有样本数 >= 3 的组才绘制
        valid_groups = group_counts[group_counts >= 3].index.tolist()

        if len(valid_groups) == 0:
            return {}

        total_points = df[df['temp_group'].isin(valid_groups)].shape[0]
        if total_points < 10:
            return {}

        fig = go.Figure()

        for group_label in valid_groups:
            group_df = df[df['temp_group'] == group_label]
            if group_df.empty:
                continue

            color = temp_group_colors.get(group_label, '#999999')
            n = len(group_df)
            legend_name = f"{group_label} (n={n})"

            # 按配速排序
            group_sorted = group_df.sort_values('pace_min_km')

            # 添加散点
            fig.add_trace(go.Scatter(
                x=group_sorted['pace_min_km'].tolist(),
                y=group_sorted['avg_hr'].tolist(),
                mode='markers',
                name=legend_name,
                marker=dict(color=color, size=6, symbol='circle', opacity=0.6),
                hovertemplate=(
                    f"<b>{group_label}</b><br>"
                    f"样本数: {n}<br>"
                    f"配速: %{{x:.1f}} min/km<br>"
                    f"心率: %{{y:.0f}} bpm<extra></extra>"
                ),
            ))

            # 线性回归趋势线
            x_vals = group_sorted['pace_min_km'].values
            y_vals = group_sorted['avg_hr'].values
            if len(x_vals) >= 2:
                coeffs = np.polyfit(x_vals, y_vals, 1)
                x_range = np.linspace(x_vals.min(), x_vals.max(), 50)
                y_fit = coeffs[0] * x_range + coeffs[1]
                fig.add_trace(go.Scatter(
                    x=x_range.tolist(),
                    y=y_fit.tolist(),
                    mode='lines',
                    name=f'{legend_name} 趋势',
                    line=dict(color=color, width=2.5, dash='solid'),
                    showlegend=False,
                    hoverinfo='skip',
                ))

        # 动态配速范围（±5秒 = ±0.083分）
        pace_min = df['pace_min_km'].min()
        pace_max = df['pace_min_km'].max()
        pad = 5.0 / 60.0  # 5秒
        pace_lo = pace_max + pad  # 最慢+5秒
        pace_hi = pace_min - pad  # 最快-5秒

        fig.update_layout(
            title=None,
            xaxis=dict(
                title='配速 (min/km)',
                range=[pace_lo, pace_hi],  # 左慢右快
            ),
            yaxis=dict(title='心率 (bpm)'),
            height=450,
            **self._common_layout_style,
        )

        return self._to_js_dict(fig.to_dict())

    def create_temp_efficiency_chart(self, df: pd.DataFrame) -> Dict:
        """
        气温-心率配速比关系图
        - X 轴：温度（-5°C 到 35°C，每 1°C 一个刻度）
        - Y 轴：该温度下的心率配速比平均值
        - 以轻松跑为主
        """
        temp_df = self._prepare_temp_data(df)
        if temp_df.empty:
            return {}

        # 取气温中值作为该次跑步的代表温度，四舍五入到整数
        temp_df['round_temp'] = ((temp_df['min_temperature'] + temp_df['max_temperature']) / 2).round(0).astype(int)

        # 只取轻松跑（数据最充分）
        easy = temp_df[temp_df['category_name'] == '轻松跑']
        if len(easy) < 5:
            return {}

        # 按整数温度分组，计算平均心率配速比
        temp_avg = easy.groupby('round_temp').agg(
            count=('hr_pace_ratio', 'size'),
            avg_hr_pace_ratio=('hr_pace_ratio', 'mean'),
            std_hr_pace_ratio=('hr_pace_ratio', 'std'),
        ).reset_index()

        # 不过滤样本数（1次记录也显示）
        temp_avg = temp_avg.sort_values('round_temp')

        # 创建完整温度范围（-5 到 35）
        full_range = list(range(-5, 36))
        
        # 颜色：根据温度变化
        colors = []
        for t in full_range:
            if t <= 15:
                colors.append('rgba(100, 180, 255, 0.7)')  # 冷蓝
            elif t <= 25:
                colors.append('rgba(65, 105, 225, 0.8)')   # 适中蓝
            else:
                colors.append('rgba(231, 76, 60, 0.8)')    # 热红

        fig = go.Figure()

        # 实际数据点（连线）
        fig.add_trace(go.Scatter(
            x=temp_avg['round_temp'].tolist(),
            y=temp_avg['avg_hr_pace_ratio'].tolist(),
            mode='lines+markers',
            name='效率',
            line=dict(color='#FF6B6B', width=2, shape='spline'),
            marker=dict(size=6, color='#FF6B6B'),
            error_y=dict(
                type='data',
                array=temp_avg['std_hr_pace_ratio'].fillna(0).tolist(),
                visible=True,
                color='rgba(255, 107, 107, 0.3)',
                thickness=1.5,
                width=4,
            ),
            hovertemplate="温度: %{x}°C<br>效率: %{y:.0f} (m/h)/bpm<br>样本: %{customdata}<extra></extra>",
            customdata=temp_avg['count'].tolist(),
        ))

        # 背景温度刻度参考（灰色竖线）
        for t in full_range:
            if t % 5 == 0:  # 每 5 度画一条浅线
                fig.add_vline(x=t, line_color='rgba(150,150,150,0.15)', line_width=1)

        fig.update_layout(
            title=None,
            xaxis=dict(
                title='气温 (°C)',
                range=[-5, 35],
                dtick=1,
                tickvals=list(range(-5, 36)),
                ticktext=[str(t) if t % 5 == 0 else '' for t in range(-5, 36)],
            ),
            yaxis=dict(title='效率 (m/h)/bpm'),
            height=400,
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

        try:
            charts['temp_hr_scatter'] = self.create_temp_hr_scatter_chart(df)
        except Exception as e:
            logger.warning(f"图表生成失败: temp_hr_scatter")
            charts['temp_hr_scatter'] = {}


        try:
            charts['beats_per_km'] = self.create_beats_per_km_chart(df)
        except Exception as e:
            logger.warning(f"图表生成失败: beats_per_km")
            charts['beats_per_km'] = {}

        try:
            charts['speed_hr_scatter'] = self.create_speed_hr_scatter_chart(df)
        except Exception as e:
            logger.warning(f"图表生成失败: speed_hr_scatter")
            charts['speed_hr_scatter'] = {}

        try:
            charts['speed_hr_temp_curves'] = self.create_speed_hr_temp_curves(df)
        except Exception as e:
            logger.warning(f"图表生成失败: speed_hr_temp_curves")
            charts['speed_hr_temp_curves'] = {}

        return charts
    
    @staticmethod
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
            # IQR 异常值过滤 + numpy 真分位数插值；样本 <8 时降级只显示中位线
            hist_median_pace, hist_p20_pace, hist_p80_pace = [], [], []
            show_band = bool(recent_laps) and len(recent_laps) >= 8
            if recent_laps:
                for lap_idx in range(1, total_km + 1):
                    paces = []
                    for run_laps in recent_laps:
                        for rl in run_laps:
                            if rl.get('lap_index') == lap_idx:
                                p = rl.get('pace_sec_per_km', 0)
                                if p > 0:
                                    paces.append(p)
                    
                    if paces:
                        paces = self._iqr_filter(paces)
                        hist_median_pace.append(float(np.percentile(paces, 50)))
                        if show_band:
                            hist_p20_pace.append(float(np.percentile(paces, 20)))
                            hist_p80_pace.append(float(np.percentile(paces, 80)))
                        else:
                            hist_p20_pace.append(None)
                            hist_p80_pace.append(None)
                    else:
                        hist_median_pace.append(None)
                        hist_p20_pace.append(None)
                        hist_p80_pace.append(None)
                
                hist_x = list(range(1, total_km + 1))
                
                # 历史中位配速（灰色虚线）
                fig.add_trace(go.Scatter(
                    x=hist_x,
                    y=hist_median_pace,
                    mode='lines',
                    name='历史中位配速',
                    line=dict(color='#999999', width=2, dash='dash', shape='spline'),
                    hovertemplate='公里 %{x}<br>历史中位配速: %{customdata}/KM<extra></extra>',
                    customdata=[self._format_pace(v) if v is not None else '--' for v in hist_median_pace],
                ))
                
                # 填充区域：历史P20 vs P80配速区间（注意：配速越小越快，P20是较快区间，P80是较慢区间）
                # 样本 <8 时降级不画区间；剔除无数据公里，避免阴影掉到 0
                if show_band:
                    band = [(x, a, b) for x, a, b in zip(hist_x, hist_p20_pace, hist_p80_pace)
                            if a is not None and b is not None]
                    if band:
                        bx = [p[0] for p in band]
                        fig.add_trace(go.Scatter(
                            x=bx + bx[::-1],
                            y=[p[1] for p in band] + [p[2] for p in reversed(band)],
                            fill='toself',
                            fillcolor='rgba(65, 105, 225, 0.15)',
                            line=dict(color='rgba(255,255,255,0)'),
                            name='历史P20-P80区间',
                            hoverinfo='skip',
                            showlegend=True,
                        ))
            
            # 需求 1：Y 轴使用自定义 ticktext 显示 X:XX/KM 格式
            # 范围取本次与历史区间的并集，避免阴影溢出可视区被裁、刻度缺失
            valid_paces = [p for p in pace_values if p > 0]
            hist_vals = [v for v in (hist_median_pace + hist_p20_pace + hist_p80_pace)
                         if v is not None]
            all_vals = valid_paces + hist_vals
            max_pace = max(all_vals) if all_vals else 420
            min_pace = min(all_vals) if all_vals else 300
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
            # IQR 异常值过滤 + numpy 真分位数插值；样本 <8 时降级只显示中位线
            hist_median_hr, hist_p20_hr, hist_p80_hr = [], [], []
            show_band = bool(recent_laps) and len(recent_laps) >= 8
            if recent_laps:
                for lap_idx in range(1, total_km + 1):
                    hrs = []
                    for run_laps in recent_laps:
                        for rl in run_laps:
                            if rl.get('lap_index') == lap_idx:
                                h = rl.get('avg_hr')
                                if h is not None and h > 0:
                                    hrs.append(h)
                    
                    if hrs:
                        hrs = self._iqr_filter(hrs)
                        hist_median_hr.append(float(np.percentile(hrs, 50)))
                        if show_band:
                            hist_p20_hr.append(float(np.percentile(hrs, 20)))
                            hist_p80_hr.append(float(np.percentile(hrs, 80)))
                        else:
                            hist_p20_hr.append(None)
                            hist_p80_hr.append(None)
                    else:
                        hist_median_hr.append(None)
                        hist_p20_hr.append(None)
                        hist_p80_hr.append(None)
                
                hist_x = list(range(1, total_km + 1))
                
                # 历史中位心率（灰色虚线）
                fig.add_trace(go.Scatter(
                    x=hist_x,
                    y=hist_median_hr,
                    mode='lines',
                    name='历史中位心率',
                    line=dict(color='#999999', width=2, dash='dash', shape='spline'),
                    hovertemplate='公里 %{x}<br>历史中位心率: %{y:.0f} bpm<extra></extra>',
                ))
                
                # 填充区域：历史P20 vs P80心率区间
                # 样本 <8 时降级不画区间；剔除无数据公里，避免阴影掉到 0
                if show_band:
                    band = [(x, a, b) for x, a, b in zip(hist_x, hist_p20_hr, hist_p80_hr)
                            if a is not None and b is not None]
                    if band:
                        bx = [p[0] for p in band]
                        fig.add_trace(go.Scatter(
                            x=bx + bx[::-1],
                            y=[p[1] for p in band] + [p[2] for p in reversed(band)],
                            fill='toself',
                            fillcolor='rgba(255, 107, 107, 0.15)',
                            line=dict(color='rgba(255,255,255,0)'),
                            name='历史P20-P80区间',
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

    def create_power_hr_temp_chart(self, df: pd.DataFrame, category: str = 'easy_run') -> Dict:
        """
        功率-气温-心率分组柱状图
        
        Args:
            df: 完整 DataFrame
            category: 跑步分类（如 'easy_run'）
        
        Returns:
            Plotly chart dict（JS 可序列化）
        """
        if df.empty:
            return {}
        
        # 按分类过滤
        category_df = df[df['category'] == category].copy()
        
        # 过滤有效数据
        category_df = category_df[
            (category_df['avg_power'] > 0) &
            (category_df['avg_hr'].notna()) &
            (category_df['min_temperature'].notna()) &
            (category_df['max_temperature'].notna())
        ].copy()
        
        if len(category_df) < 5:  # 至少5个样本
            return {}
        
        # 计算中值气温
        category_df['mid_temp'] = (category_df['min_temperature'] + category_df['max_temperature']) / 2
        
        # 按5W分箱功率
        category_df['power_bin'] = (category_df['avg_power'] / 5).round() * 5
        
        # 按5°C分箱气温
        temp_bins = [-float('inf'), 15, 20, 25, 30, float('inf')]
        temp_labels = ['<15°C', '15-20°C', '20-25°C', '25-30°C', '30°C+']
        category_df['temp_bin'] = pd.cut(category_df['mid_temp'], bins=temp_bins, labels=temp_labels, include_lowest=True)
        
        # 按(功率区间, 气温区间)分组，计算平均心率和样本数
        grouped = category_df.groupby(['power_bin', 'temp_bin'], observed=False).agg({
            'avg_hr': ['mean', 'count']
        }).round(1)
        
        # 重命名列
        grouped.columns = ['avg_hr', 'count']
        grouped = grouped.reset_index()
        
        # 过滤掉样本数少于2的组合
        grouped = grouped[grouped['count'] >= 2]
        
        if grouped.empty:
            return {}
        
        # 透视表，使功率区间为x轴，气温区间为分组
        pivot_table = grouped.pivot(index='power_bin', columns='temp_bin', values='avg_hr')
        count_table = grouped.pivot(index='power_bin', columns='temp_bin', values='count')
        
        # 按功率区间排序
        pivot_table = pivot_table.sort_index()
        count_table = count_table.reindex(pivot_table.index)
        
        # 生成图表
        fig = go.Figure()
        
        # 定义气温颜色
        temp_colors = {
            '<15°C': '#4A90D9',  # 冷蓝
            '15-20°C': '#5BC0A5',  # 绿蓝
            '20-25°C': '#F5D76E',  # 暖黄
            '25-30°C': '#F7882F',  # 橙色
            '30°C+': '#E74C3C'  # 热红
        }
        
        # 添加每个气温区间的柱状图
        for temp_bin in temp_labels:
            if temp_bin in pivot_table.columns:
                x_values = [f"{int(power)-2.5:.0f}-{int(power)+2.5:.0f}W" for power in pivot_table.index]
                y_values = pivot_table[temp_bin].tolist()
                count_values = count_table[temp_bin].tolist() if temp_bin in count_table.columns else [None] * len(y_values)
                
                # 生成hover文本
                hover_text = []
                for i, (hr, cnt) in enumerate(zip(y_values, count_values)):
                    if pd.notna(hr) and pd.notna(cnt):
                        hover_text.append(f"功率区间: {x_values[i]}<br>平均心率: {hr:.1f} bpm<br>样本数: {int(cnt)}<extra></extra>")
                    else:
                        hover_text.append(f"功率区间: {x_values[i]}<extra></extra>")
                
                fig.add_trace(go.Bar(
                    x=x_values,
                    y=y_values,
                    name=temp_bin,
                    marker_color=temp_colors.get(temp_bin, '#999999'),
                    hovertemplate='%{hovertext}',
                    hovertext=hover_text
                ))
        
        fig.update_layout(
            title=None,
            xaxis=dict(title='功率区间 (W)'),
            yaxis=dict(title='平均心率 (bpm)'),
            barmode='group',
            height=500,
            **self._common_layout_style
        )
        
        return self._to_js_dict(fig.to_dict())
    
    def create_pa_hr_trend_chart(self, pa_hr_history: list) -> Dict:
        """
        Pa:Hr 历史趋势图
        
        Args:
            pa_hr_history: Pa:Hr 历史数据列表，每个元素包含:
                - date: 日期
                - category: 分类
                - category_color: 分类颜色
                - category_icon: 分类图标
                - distance: 距离(km)
                - mid_temp: 中值气温
                - pa_hr_pct: Pa:Hr 百分比
                - pa_hr_abs: Pa:Hr 绝对值
        
        Returns:
            Plotly chart dict（JS 可序列化）
        """
        if not pa_hr_history or len(pa_hr_history) < 3:  # 至少3个样本
            return {}
        
        # 转换为DataFrame便于处理
        import pandas as pd
        df = pd.DataFrame(pa_hr_history)
        
        # 按日期排序
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        fig = go.Figure()
        
        # 添加背景色带（按解读标准）
        # 绿色区域：-3% ~ +3%（稳定区）
        fig.add_hrect(y0=-3, y1=3, line_width=0, fillcolor="green", opacity=0.1)
        # 黄色区域：-5% ~ -3%（正常区）
        fig.add_hrect(y0=-5, y1=-3, line_width=0, fillcolor="yellow", opacity=0.1)
        # 橙色区域：-8% ~ -5%（漂移区）
        fig.add_hrect(y0=-8, y1=-5, line_width=0, fillcolor="orange", opacity=0.1)
        # 红色区域：< -8%（热疲劳区）
        fig.add_hrect(y0=-100, y1=-8, line_width=0, fillcolor="red", opacity=0.1)
        
        # 添加Pa:Hr趋势线
        fig.add_trace(go.Scatter(
            x=df['date'].tolist(),
            y=df['pa_hr_pct'].tolist(),
            mode='lines+markers',
            name='Pa:Hr',
            line=dict(color='blue', width=2),
            marker=dict(size=8, color=df['category_color'].tolist()),
            hovertemplate="日期: %{x}<br>Pa:Hr: %{y:.1f}%<br>类型: %{customdata[0]}<br>距离: %{customdata[1]:.1f}km<br>气温: %{customdata[2]:.1f}°C<extra></extra>",
            customdata=list(zip(df['category'].tolist(), df['distance'].tolist(), df['mid_temp'].tolist()))
        ))
        
        fig.update_layout(
            title=None,
            xaxis=dict(title='日期', tickformat='%Y-%m-%d'),
            yaxis=dict(title='Pa:Hr (%)', range=[-20, 10]),  # 负值表示后半程效率下降
            height=500,
            hovermode='x unified',
            **self._common_layout_style
        )
        
        return self._to_js_dict(fig.to_dict())
