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

logger = logging.getLogger(__name__)


class ChartGenerator:
    """图表生成器"""
    
    HR_ZONE_COLORS = {
        'Z1-有氧基础': '#808080',
        'Z2-有氧耐力': '#87CEEB',
        'Z3-乳酸阈值': '#32CD32',
        'Z4-无氧耐力': '#FFA500',
        'Z5-最大强度': '#FF0000',
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
    
    def _to_js_dict(self, fig_dict: Dict) -> Dict:
        """将Plotly字典转换为可JSON序列化的字典"""
        return json.loads(json.dumps(fig_dict, default=lambda x: x.tolist() if hasattr(x, 'tolist') else str(x) if isinstance(x, pd.Timestamp) else x))
    
    def _format_pace(self, seconds: int) -> str:
        """将秒数转换为分:秒格式"""
        minutes = seconds // 60
        secs = seconds % 60
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
        
        # 4种类型：轻松跑、有氧耐力、LSD、比赛(合并全马半马赛事)
        cat_list = ['easy_run', 'aerobic_run', 'lsd', 'race']
        date_range_list = ['all', '1y', 'ytd', '6m', '3m']
        
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        # 为每个（类型，日期范围）组合创建2个trace（配速+心率）
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
                
                # 默认显示：有氧耐力 + 全部
                is_visible = (cat == 'aerobic_run' and date_range == 'all')
                
                if len(cat_df) > 0:
                    # 添加配速格式化列
                    cat_df = cat_df.copy()
                    cat_df['pace_fmt'] = cat_df['avg_pace_sec'].apply(self._format_pace)
                    
                    # 配速曲线 - hover显示分:秒格式
                    fig.add_trace(go.Scatter(
                        x=cat_df['date_str'].tolist(),
                        y=cat_df['avg_pace_sec'].tolist(),
                        mode='lines+markers',
                        name=f"{cat_name}",
                        line=dict(color=color, width=2),
                        marker=dict(size=8, color=color),
                        visible=is_visible,
                        hovertemplate="<b>%{customdata[0]}</b><br>日期: %{x}<br>配速: %{customdata[1]}<extra></extra>",
                        customdata=np.stack([cat_df['title'].values, cat_df['pace_fmt'].values], axis=-1)
                    ), secondary_y=False)
                    
                    # 心率曲线
                    fig.add_trace(go.Scatter(
                        x=cat_df['date_str'].tolist(),
                        y=cat_df['avg_hr'].tolist(),
                        mode='lines+markers',
                        name=f"{cat_name} - 心率",
                        line=dict(color=color, width=2, dash='dash'),
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
        
        # 生成指定（类型，日期范围）的visible列表
        def make_visible(cat_idx: int, date_idx: int) -> List[bool]:
            visible = [False] * total_traces
            start_idx = (cat_idx * 5 + date_idx) * traces_per_combo
            visible[start_idx] = True
            visible[start_idx + 1] = True
            return visible
        
        fig.update_layout(
            title=None,
            xaxis=dict(
                tickangle=-90,  # 竖排显示（右转90度）
                type='category'
            ),
            yaxis=dict(
                title='配速',
                autorange='reversed',
                tickformat='%M:%S',
                tickmode='array',
                tickvals=[300, 360, 420, 480, 540, 600],
                ticktext=['5:00', '6:00', '7:00', '8:00', '9:00', '10:00']
            ),
            yaxis2=dict(title='心率 (bpm)', range=[100, 200]),
            legend=dict(orientation='h', yanchor='bottom', y=1.15, xanchor='center', x=0.5),
            hovermode='x unified',
            template='plotly_white',
            height=500,
            # 增加顶部和左侧margin，给按钮留出空间
            margin=dict(l=80, r=60, t=120, b=80),
            updatemenus=[
                # 类型筛选按钮（图表上方外部）
                dict(
                    type='buttons',
                    direction='right',
                    x=0.5,
                    y=1.08,  # 放到图表外面
                    xanchor='center',
                    yanchor='bottom',
                    showactive=True,
                    buttons=list([
                        dict(label='轻松跑', method='update', args=[{'visible': make_visible(0, 0)}]),
                        dict(label='有氧耐力', method='update', args=[{'visible': make_visible(1, 0)}]),
                        dict(label='LSD', method='update', args=[{'visible': make_visible(2, 0)}]),
                        dict(label='比赛', method='update', args=[{'visible': make_visible(3, 0)}]),
                    ])
                ),
                # 日期筛选按钮（图表左侧外部）
                dict(
                    type='buttons',
                    direction='down',
                    x=-0.08,  # 放到图表外面
                    y=1.0,
                    xanchor='right',
                    yanchor='top',
                    showactive=True,
                    buttons=list([
                        dict(label='全部', method='update', args=[{'visible': make_visible(1, 0)}]),
                        dict(label='近一年', method='update', args=[{'visible': make_visible(1, 1)}]),
                        dict(label='今年以来', method='update', args=[{'visible': make_visible(1, 2)}]),
                        dict(label='近半年', method='update', args=[{'visible': make_visible(1, 3)}]),
                        dict(label='近三个月', method='update', args=[{'visible': make_visible(1, 4)}]),
                    ])
                )
            ]
        )
        
        return self._to_js_dict(fig.to_dict())
    
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
            template='plotly_white',
            height=400,
            margin=dict(l=60, r=40, t=40, b=60)
        )
        
        return self._to_js_dict(fig.to_dict())
    
    def create_hr_zone_pie_chart(self, df: pd.DataFrame) -> Dict:
        """创建心率分布饼图（带时间筛选）- 按钮放到图表外面"""
        if df.empty or 'hr_zone' not in df.columns:
            return {}
        
        zone_order = ['Z1-有氧基础', 'Z2-有氧耐力', 'Z3-乳酸阈值', 'Z4-无氧耐力', 'Z5-最大强度']
        
        # 准备各时间范围的数据
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
            
            range_zone = range_df.groupby('hr_zone').agg({
                'duration_min': 'sum',
                'hr_zone_color': 'first'
            }).reset_index()
            range_zone = range_zone[range_zone['hr_zone'].str.contains(r'Z\d', na=False)]
            range_zone['sort_key'] = range_zone['hr_zone'].apply(lambda x: zone_order.index(x) if x in zone_order else 99)
            range_zone = range_zone.sort_values('sort_key')
            
            range_data[range_key] = {
                'labels': range_zone['hr_zone'].tolist(),
                'values': range_zone['duration_min'].tolist(),
                'colors': range_zone['hr_zone_color'].tolist()
            }
        
        fig = go.Figure()
        
        for range_key in ['all', '3m', '6m', 'ytd', '1y']:
            fig.add_trace(go.Pie(
                labels=range_data[range_key]['labels'],
                values=range_data[range_key]['values'],
                marker_colors=range_data[range_key]['colors'],
                hole=0.4,
                textinfo='label+percent',
                textposition='outside',
                hovertemplate="%{label}<br>%{value:.0f} 分钟<br>%{percent}<extra></extra>",
                visible=(range_key == 'all')
            ))
        
        fig.update_layout(
            title=None,
            template='plotly_white',
            height=400,
            showlegend=False,
            # 增加顶部margin，给按钮留出空间
            margin=dict(l=40, r=40, t=100, b=40),
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
    
    def create_category_pie_chart(self, df: pd.DataFrame) -> Dict:
        """创建跑分类别分布饼图（带时间筛选）- 按钮放到图表外面"""
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
            template='plotly_white',
            height=400,
            showlegend=False,
            # 增加顶部margin，给按钮留出空间
            margin=dict(l=40, r=40, t=100, b=40),
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
        if df.empty or 'hr_zone' not in df.columns or 'year_month' not in df.columns:
            return {}
        
        df_recent = self._get_recent_months(df, 12)
        monthly_zone = df_recent.groupby(['year_month', 'hr_zone'])['duration_min'].sum().reset_index()
        pivot_df = monthly_zone.pivot(index='year_month', columns='hr_zone', values='duration_min').fillna(0)
        
        zone_order = ['Z1-有氧基础', 'Z2-有氧耐力', 'Z3-乳酸阈值', 'Z4-无氧耐力', 'Z5-最大强度']
        for zone in zone_order:
            if zone not in pivot_df.columns:
                pivot_df[zone] = 0
        pivot_df = pivot_df[[z for z in zone_order if z in pivot_df.columns]]
        pivot_df = pivot_df.sort_index()
        
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
                hovertemplate=f"{zone}<br>%{{x}}: %{{y:.0f}} 分钟<extra></extra>"
            ))
        
        fig.update_layout(
            title=None,
            xaxis=dict(tickangle=0, title=None, type='category'),
            yaxis=dict(title='时长 (分钟)'),
            barmode='stack',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            template='plotly_white',
            height=450,
            margin=dict(l=60, r=40, t=60, b=60)
        )
        
        return self._to_js_dict(fig.to_dict())
    
    def create_distance_trend_chart(self, df: pd.DataFrame) -> Dict:
        """
        创建距离趋势图
        - 散点图 + 移动平均线
        - 按分类着色
        """
        if df.empty:
            return {}

        df = df.copy().sort_values('date')
        df['date_str'] = df['date'].dt.strftime('%m-%d')

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
                x=cat_df['date_str'].tolist(),
                y=cat_df['distance'].tolist(),
                mode='markers',
                name=name,
                marker=dict(color=color, size=10, symbol='circle'),
                hovertemplate="<b>%{customdata[0]}</b><br>日期: %{x}<br>距离: %{y:.1f} km<extra></extra>",
                customdata=np.stack([cat_df['title'].values, cat_df['avg_pace_fmt'].values], axis=-1)
            ))

        # 移动平均线（窗口=5）
        if len(df) >= 5:
            rolling_avg = df['distance'].rolling(window=5, center=True).mean()
            fig.add_trace(go.Scatter(
                x=df['date_str'].tolist(),
                y=rolling_avg.tolist(),
                mode='lines',
                name='5次移动平均',
                line=dict(color='#FF6B6B', width=3, dash='dash'),
                hovertemplate="移动平均: %{y:.1f} km<extra></extra>"
            ))

        fig.update_layout(
            title=None,
            xaxis=dict(tickangle=-90, title=None, type='category'),
            yaxis=dict(title='距离 (km)'),
            template='plotly_white',
            height=400,
            margin=dict(l=60, r=40, t=40, b=80),
            hovermode='x unified',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5)
        )

        return self._to_js_dict(fig.to_dict())

    def create_training_effect_chart(self, df: pd.DataFrame) -> Dict:
        """
        创建训练效果趋势图
        - 有氧效果 + 无氧效果双线图
        - 仅在有氧/无氧效果数据可用时显示
        """
        if df.empty:
            return {}

        # 检查是否有训练效果数据
        has_aerobic = 'aerobic_effect' in df.columns and df['aerobic_effect'].notna().any()
        has_anaerobic = 'anaerobic_effect' in df.columns and df['anaerobic_effect'].notna().any()

        if not has_aerobic and not has_anaerobic:
            return {}

        df = df.copy().sort_values('date')
        df['date_str'] = df['date'].dt.strftime('%m-%d')

        fig = go.Figure()

        if has_aerobic:
            fig.add_trace(go.Scatter(
                x=df['date_str'].tolist(),
                y=df['aerobic_effect'].tolist(),
                mode='lines+markers',
                name='有氧效果',
                line=dict(color='#4169E1', width=2),
                marker=dict(size=8, color='#4169E1'),
                hovertemplate="<b>%{customdata}</b><br>日期: %{x}<br>有氧效果: %{y:.1f}<extra></extra>",
                customdata=df['title'].values
            ))

        if has_anaerobic:
            fig.add_trace(go.Scatter(
                x=df['date_str'].tolist(),
                y=df['anaerobic_effect'].tolist(),
                mode='lines+markers',
                name='无氧效果',
                line=dict(color='#FF6B6B', width=2),
                marker=dict(size=8, symbol='diamond', color='#FF6B6B'),
                hovertemplate="<b>%{customdata}</b><br>日期: %{x}<br>无氧效果: %{y:.1f}<extra></extra>",
                customdata=df['title'].values
            ))

        # 添加参考线
        fig.add_hline(y=3.0, line_dash="dot", line_color="#cccccc",
                      annotation_text="维持健康线")
        fig.add_hline(y=4.0, line_dash="dot", line_color="#999999",
                      annotation_text="提升体能线")
        fig.add_hline(y=5.0, line_dash="dot", line_color="#FF6B6B",
                      annotation_text="过度训练线")

        fig.update_layout(
            title=None,
            xaxis=dict(tickangle=-90, title=None, type='category'),
            yaxis=dict(title='训练效果评分', range=[0, 6]),
            template='plotly_white',
            height=400,
            margin=dict(l=60, r=40, t=40, b=80),
            hovermode='x unified',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5)
        )

        return self._to_js_dict(fig.to_dict())

    def create_power_distribution_chart(self, df: pd.DataFrame) -> Dict:
        """
        创建功率分布图
        - 直方图 + 核密度估计
        - 仅在有功率数据时显示
        """
        if df.empty or 'avg_power' not in df.columns or df['avg_power'].notna().sum() < 5:
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

        fig.add_vline(x=mean_power, line_dash="dash", line_color="#FF6B6B",
                      annotation_text=f"平均: {mean_power:.0f}W")
        fig.add_vline(x=median_power, line_dash="dot", line_color="#32CD32",
                      annotation_text=f"中位数: {median_power:.0f}W")

        fig.update_layout(
            title=None,
            xaxis=dict(title='平均功率 (W)'),
            yaxis=dict(title='次数'),
            template='plotly_white',
            height=400,
            margin=dict(l=60, r=40, t=40, b=60),
            bargap=0.05
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
            'Z1-有氧基础': '#808080',
            'Z2-有氧耐力': '#87CEEB',
            'Z3-乳酸阈值': '#32CD32',
            'Z4-无氧耐力': '#FFA500',
            'Z5-最大强度': '#FF0000',
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
            template='plotly_white',
            height=400,
            margin=dict(l=60, r=40, t=40, b=60),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5),
            bargap=0.05
        )

        return self._to_js_dict(fig.to_dict())

    def generate_all_charts(self, df: pd.DataFrame) -> Dict[str, Dict]:
        """生成所有图表"""
        charts = {}

        try:
            charts['pace_hr_trend'] = self.create_pace_hr_trend_chart(df)
        except Exception as e:
            logger.error(f"生成配速-心率趋势图失败: {e}")
            charts['pace_hr_trend'] = {}

        try:
            charts['monthly_volume'] = self.create_monthly_volume_chart(df)
        except Exception as e:
            logger.error(f"生成月跑量图失败: {e}")
            charts['monthly_volume'] = {}

        try:
            charts['hr_zone_pie'] = self.create_hr_zone_pie_chart(df)
        except Exception as e:
            logger.error(f"生成心率分布饼图失败: {e}")
            charts['hr_zone_pie'] = {}

        try:
            charts['category_pie'] = self.create_category_pie_chart(df)
        except Exception as e:
            logger.error(f"生成分类分布饼图失败: {e}")
            charts['category_pie'] = {}

        try:
            charts['hr_zone_stacked'] = self.create_hr_zone_stacked_bar(df)
        except Exception as e:
            logger.error(f"生成心率区间堆叠图失败: {e}")
            charts['hr_zone_stacked'] = {}

        try:
            charts['distance_trend'] = self.create_distance_trend_chart(df)
        except Exception as e:
            logger.error(f"生成距离趋势图失败: {e}")
            charts['distance_trend'] = {}

        try:
            charts['training_effect'] = self.create_training_effect_chart(df)
        except Exception as e:
            logger.error(f"生成训练效果趋势图失败: {e}")
            charts['training_effect'] = {}

        try:
            charts['power_distribution'] = self.create_power_distribution_chart(df)
        except Exception as e:
            logger.error(f"生成功率分布图失败: {e}")
            charts['power_distribution'] = {}

        try:
            charts['hr_distribution'] = self.create_hr_distribution_histogram(df)
        except Exception as e:
            logger.error(f"生成心率分布直方图失败: {e}")
            charts['hr_distribution'] = {}

        return charts
