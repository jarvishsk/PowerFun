"""
分类器模块
实现心率区间分类（HRR储备心率法）和跑分类逻辑
"""

import pandas as pd
import numpy as np
from typing import Tuple, Optional, Dict
import logging

from src.config import DEFAULT_CONFIG, ZONE_COLORS

logger = logging.getLogger(__name__)


class HeartRateClassifier:
    """
    心率区间分类器（HRR储备心率法）
    
    储备心率(HRR) = 最大心率 - 静息心率
    目标心率 = 静息心率 + HRR × 区间百分比
    """
    
    # 默认心率参数（从 DEFAULT_CONFIG 读取）
    DEFAULT_HR_MAX = DEFAULT_CONFIG.get('max_hr', 190)
    DEFAULT_HR_REST = DEFAULT_CONFIG.get('resting_hr', 60)
    
    # 心率区间定义 (Z1范围已扩大至1%-74%)
    # 注意: 这是类级别的共享字典，__init__ 中会 deepcopy 到实例级别
    ZONES = {
        'Z1': {
            'name': '有氧基础',
            'name_en': 'Aerobic Base',
            'range': (61, 156),  # 60+130*0.01=61.3, 60+130*0.74=156.2
            'percent': (0.01, 0.74),
            'color': ZONE_COLORS['Z1'],
            'emoji': '🩶',
            'purpose': '恢复跑、基础有氧'
        },
        'Z2': {
            'name': '有氧耐力',
            'name_en': 'Aerobic Endurance',
            'range': (157, 169),
            'percent': (0.74, 0.84),
            'color': ZONE_COLORS['Z2'],
            'emoji': '🩵',
            'purpose': 'MAF训练、LSD'
        },
        'Z3': {
            'name': '乳酸阈值',
            'name_en': 'Lactate Threshold',
            'range': (170, 174),
            'percent': (0.84, 0.88),
            'color': ZONE_COLORS['Z3'],
            'emoji': '🟢',
            'purpose': 'Tempo跑、半马配速'
        },
        'Z4': {
            'name': '无氧耐力',
            'name_en': 'Anaerobic Endurance',
            'range': (175, 182),
            'percent': (0.88, 0.94),
            'color': ZONE_COLORS['Z4'],
            'emoji': '🟠',
            'purpose': '间歇训练、10K配速'
        },
        'Z5': {
            'name': '最大强度',
            'name_en': 'Maximum Effort',
            'range': (183, 190),
            'percent': (0.94, 1.00),
            'color': ZONE_COLORS['Z5'],
            'emoji': '🔴',
            'purpose': '冲刺、最大心率训练'
        }
    }
    
    def __init__(self, hr_max: int = None, hr_rest: int = None):
        """
        初始化心率分类器
        
        Args:
            hr_max: 最大心率，默认190
            hr_rest: 静息心率，默认60
        """
        import copy
        self.ZONES = copy.deepcopy(self.__class__.ZONES)
        self.hr_max = hr_max or self.DEFAULT_HR_MAX
        self.hr_rest = hr_rest or self.DEFAULT_HR_REST
        self.hrr = self.hr_max - self.hr_rest

        # 重新计算区间边界
        self._recalculate_zones()
    
    def _recalculate_zones(self):
        """根据个性化心率参数重新计算区间"""
        for zone_id, zone_info in self.ZONES.items():
            low_pct, high_pct = zone_info['percent']
            zone_info['range'] = (
                int(self.hr_rest + self.hrr * low_pct),
                int(self.hr_rest + self.hrr * high_pct)
            )
    
    def classify(self, avg_hr: Optional[int]) -> Tuple[str, str]:
        """
        根据平均心率返回区间名称和颜色
        
        Args:
            avg_hr: 平均心率
            
        Returns:
            Tuple[str, str]: (区间名称, 颜色代码)
        """
        if avg_hr is None or pd.isna(avg_hr):
            return "无数据", "#999999"
        
        avg_hr = int(avg_hr)
        
        # 使用动态计算的 ZONES 区间进行判断（支持 --max-hr 和 --resting-hr 参数）
        for zone_id, zone_info in self.ZONES.items():
            low, high = zone_info['range']
            if low <= avg_hr <= high:
                return f"{zone_id}-{zone_info['name']}", zone_info['color']
        
        # 低于最低区间 / 高于最高区间的处理
        first_zone = next(iter(self.ZONES.values()))
        last_zone = next(reversed(self.ZONES.values()))
        if avg_hr < first_zone['range'][0]:
            return "过低心率", "#CCCCCC"
        else:  # > 最高区间上限
            return "超限心率", "#8B0000"
    
    def get_zone_details(self, avg_hr: Optional[int]) -> Dict:
        """
        获取心率区间的详细信息
        
        Args:
            avg_hr: 平均心率
            
        Returns:
            Dict: 区间详细信息
        """
        zone_name, color = self.classify(avg_hr)
        
        if zone_name == "无数据":
            return {
                'zone': None,
                'name': '无数据',
                'color': color,
                'emoji': '⚪',
                'purpose': '-'
            }
        
        # 提取区间代码
        zone_code = zone_name.split('-')[0] if '-' in zone_name else None
        
        if zone_code and zone_code in self.ZONES:
            zone_info = self.ZONES[zone_code].copy()
            zone_info['zone'] = zone_code
            return zone_info
        
        return {
            'zone': zone_code,
            'name': zone_name,
            'color': color,
            'emoji': '⚪',
            'purpose': '-'
        }
    
    def classify_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        对DataFrame中的所有记录进行心率分类
        
        Args:
            df: 包含avg_hr列的DataFrame
            
        Returns:
            DataFrame: 添加了心率区间列的DataFrame
        """
        df = df.copy()
        
        # 应用分类
        results = df['avg_hr'].apply(self.classify)
        df['hr_zone'] = results.str[0]
        df['hr_zone_color'] = results.str[1]
        
        # 提取区间代码
        df['hr_zone_code'] = df['hr_zone'].apply(
            lambda x: x.split('-')[0] if '-' in x else None
        )
        
        return df
    
    def get_zone_distribution(self, df: pd.DataFrame) -> Dict:
        """
        获取心率区间分布统计
        
        Args:
            df: 包含hr_zone列的DataFrame
            
        Returns:
            Dict: 各区间占比
        """
        if 'hr_zone' not in df.columns:
            df = self.classify_dataframe(df)
        
        total = len(df)
        distribution = df['hr_zone'].value_counts().to_dict()
        
        # 计算百分比
        result = {}
        for zone, count in distribution.items():
            result[zone] = {
                'count': count,
                'percentage': round(count / total * 100, 2)
            }
        
        return result


class RunClassifier:
    """
    跑分类器（分层判定策略）
    
    优先级从高到低：
    1. 比赛识别（Race）
    2. 长距离慢跑（LSD）
    3. 日常训练（Regular Run）
    4. 短距离训练（Short Run）
    5. 异常数据
    """
    
    # 比赛关键词（通用赛事相关词汇，已简化为 8 个通用词）
    # 删除了具体赛事名称和越野跑关键词（越野跑分类逻辑不同）
    RACE_KEYWORDS = [
        '马拉松', '半程马拉松', 'marathon', '全马', '半马', '比赛', 'full', 'half', 'race',
    ]
    
    # 分类定义
    CATEGORIES = {
        'full_marathon': {
            'name': '全马比赛',
            'name_en': 'Full Marathon',
            'color': '#FFD700',  # 金色
            'icon': '🏆'
        },
        'half_marathon': {
            'name': '半马比赛',
            'name_en': 'Half Marathon',
            'color': '#C0C0C0',  # 银色
            'icon': '🥈'
        },
        'race_event': {
            'name': '其他赛事',
            'name_en': 'Race Event',
            'color': '#CD7F32',  # 铜色
            'icon': '🏅'
        },
        'lsd': {
            'name': 'LSD长距离',
            'name_en': 'Long Slow Distance',
            'color': '#4169E1',  # 蓝色
            'icon': '🏃'
        },
        'easy_run': {
            'name': '轻松跑',
            'name_en': 'Easy Run',
            'color': '#808080',  # 灰色
            'icon': '😌'
        },
        'aerobic_run': {
            'name': '有氧耐力跑',
            'name_en': 'Aerobic Run',
            'color': '#87CEEB',  # 淡蓝色
            'icon': '💨'
        },
        'tempo_run': {
            'name': '马拉松配速跑',
            'name_en': 'Tempo Run',
            'color': '#32CD32',  # 绿色
            'icon': '⚡'
        },
        'intensity_run': {
            'name': '强度训练',
            'name_en': 'Intensity Training',
            'color': '#FFA500',  # 橙色
            'icon': '🔥'
        },
        'short_run': {
            'name': '短距离训练',
            'name_en': 'Short Run',
            'color': '#9370DB',  # 紫色
            'icon': '👟'
        },
        'other': {
            'name': '其他',
            'name_en': 'Other',
            'color': '#999999',
            'icon': '❓'
        }
    }
    
    def __init__(self, hr_classifier: HeartRateClassifier = None):
        """
        初始化跑分类器
        
        Args:
            hr_classifier: 心率分类器实例
        """
        self.hr_classifier = hr_classifier or HeartRateClassifier()
    
    def is_race(self, title: str) -> bool:
        """
        检查标题是否包含比赛关键词
        
        Args:
            title: 活动标题
            
        Returns:
            bool: 是否为比赛
        """
        if pd.isna(title):
            return False
        
        title_lower = str(title).lower()
        return any(keyword.lower() in title_lower for keyword in self.RACE_KEYWORDS)
    
    def classify(self, row: pd.Series) -> str:
        """
        对单条记录进行分类
        
        Args:
            row: 包含distance, title, avg_hr等字段的Series
            
        Returns:
            str: 分类结果
        """
        distance = row.get('distance', 0)
        title = row.get('title', '')
        avg_hr = row.get('avg_hr', None)
        
        # 第一层：比赛识别
        if self.is_race(title):
            if distance >= 40:
                return 'full_marathon'
            elif distance >= 21:
                return 'half_marathon'
            else:
                return 'race_event'
        
        # 第二层：LSD长距离（距离≥20km）
        if distance >= 20:
            return 'lsd'
        
        # 第三层：日常训练（按心率细分）
        if distance >= 5:
            hr_zone, _ = self.hr_classifier.classify(avg_hr)
            
            if 'Z1' in hr_zone:
                return 'easy_run'
            elif 'Z2' in hr_zone:
                return 'aerobic_run'
            elif 'Z3' in hr_zone:
                return 'tempo_run'
            elif 'Z4' in hr_zone or 'Z5' in hr_zone:
                return 'intensity_run'
            else:
                return 'aerobic_run'  # 默认
        
        # 第四层：短距离训练
        if distance >= 2:
            return 'short_run'
        
        # 第五层：异常数据
        return 'other'
    
    def classify_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        对DataFrame中的所有记录进行分类
        
        Args:
            df: 包含distance, title, avg_hr列的DataFrame
            
        Returns:
            DataFrame: 添加了分类列的DataFrame
        """
        df = df.copy()
        
        # 应用分类
        df['category'] = df.apply(self.classify, axis=1)
        
        # 添加分类详细信息
        df['category_name'] = df['category'].apply(
            lambda x: self.CATEGORIES.get(x, self.CATEGORIES['other'])['name']
        )
        df['category_color'] = df['category'].apply(
            lambda x: self.CATEGORIES.get(x, self.CATEGORIES['other'])['color']
        )
        df['category_icon'] = df['category'].apply(
            lambda x: self.CATEGORIES.get(x, self.CATEGORIES['other'])['icon']
        )
        
        return df
    
    def get_category_distribution(self, df: pd.DataFrame) -> Dict:
        """
        获取跑分类别分布统计
        
        Args:
            df: 包含category列的DataFrame
            
        Returns:
            Dict: 各类别占比
        """
        if 'category' not in df.columns:
            df = self.classify_dataframe(df)
        
        total = len(df)
        distribution = df['category'].value_counts().to_dict()
        
        # 计算百分比和详细信息
        result = {}
        for cat, count in distribution.items():
            cat_info = self.CATEGORIES.get(cat, self.CATEGORIES['other'])
            result[cat] = {
                'count': count,
                'percentage': round(count / total * 100, 2),
                'name': cat_info['name'],
                'color': cat_info['color'],
                'icon': cat_info['icon']
            }
        
        return result
    
    def get_monthly_stats(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        获取月度统计
        
        Args:
            df: 包含year_month, distance, duration_min等列的DataFrame
            
        Returns:
            DataFrame: 月度统计数据
        """
        if 'category' not in df.columns:
            df = self.classify_dataframe(df)
        
        monthly = df.groupby('year_month').agg({
            'distance': ['count', 'sum', 'mean'],
            'duration_min': 'sum',
            'avg_pace_sec': 'mean',
            'avg_hr': 'mean',
            'calories': 'sum'
        }).reset_index()
        
        # 扁平化列名
        monthly.columns = [
            'year_month', 'run_count', 'total_distance', 'avg_distance',
            'total_duration', 'avg_pace', 'avg_hr', 'total_calories'
        ]
        
        # 格式化
        monthly['avg_pace_fmt'] = monthly['avg_pace'].apply(
            lambda x: f"{int(x//60)}:{int(x%60):02d}" if pd.notna(x) else '--'
        )
        
        return monthly
