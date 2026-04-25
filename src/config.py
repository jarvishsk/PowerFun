"""PowerFun 配置模块

定义字段映射表、心率区间、默认参数等。
"""

# ============================================================
# 字段映射：跑分期望字段 -> Garmer API 实际字段 + 转换逻辑
# ============================================================
FIELD_MAPPING = {
    'date': {
        'source': 'startTimeLocal',
        'transform': 'extract_datetime',
        'description': '活动日期时间'
    },
    'title': {
        'source': 'activityName',
        'transform': 'identity',
        'description': '活动标题'
    },
    'distance': {
        'source': 'distance_km',
        'transform': 'identity',
        'description': '距离 (km)'
    },
    'avg_hr': {
        'source': 'avg_hr',
        'transform': 'identity',
        'description': '平均心率 (bpm)'
    },
    'max_hr': {
        'source': 'max_hr',
        'transform': 'identity',
        'description': '最大心率 (bpm)'
    },
    'avg_pace': {
        'source': 'pace_min_per_km',
        'transform': 'pace_to_mmss',
        'description': '平均配速 (mm:ss/km)'
    },
    'best_pace': {
        'source': 'maxSpeed',
        'transform': 'speed_to_pace_mmss',
        'description': '最佳配速 (mm:ss/km)'
    },
    'duration': {
        'source': 'elapsed_min',
        'transform': 'minutes_to_hhmmss',
        'description': '持续时间 (hh:mm:ss)'
    },
    'calories': {
        'source': 'calories',
        'transform': 'identity',
        'description': '卡路里 (kcal)'
    },
    'cadence': {
        'source': 'avg_cadence',
        'transform': 'identity',
        'description': '平均步频 (spm)'
    },
    'vertical_ratio': {
        'source': 'verticalRatio',
        'transform': 'identity',
        'description': '垂直振幅比 (%)'
    },
    'avg_power': {
        'source': 'avg_power',
        'transform': 'identity',
        'description': '平均功率 (W)'
    },
    'elevation_gain': {
        'source': 'elevation_gain_m',
        'transform': 'identity',
        'description': '累计爬升 (m)'
    },
    'activity_type': {
        'source': 'activity_type',
        'transform': 'identity',
        'description': '活动类型'
    }
}

# 额外保留字段（用于未来扩展）
EXTRA_FIELDS = [
    'activity_id',        # Garmin 活动 ID
    'location',           # 地点/路线名称
    'elevation_loss_m',   # 累计下降 (m)
    'steps',              # 总步数
    'training_effect',    # 训练效果 (TE)
    'max_power',          # 最大功率 (W)
    'normalized_power',   # 标准化功率 (NP)
    'ground_contact_time', # 触地时间 (ms)
    'start_lat',          # 起点纬度
    'start_lon',          # 起点经度
]

# ============================================================
# 心率区间定义 (基于最大心率百分比)
# ============================================================
HEART_RATE_ZONES = {
    'Z1_热身':    {'min_pct': 0.50, 'max_pct': 0.60, 'color': '#95a5a6', 'emoji': '🩶'},
    'Z2_燃脂':    {'min_pct': 0.60, 'max_pct': 0.70, 'color': '#3498db', 'emoji': '💙'},
    'Z3_有氧':    {'min_pct': 0.70, 'max_pct': 0.80, 'color': '#2ecc71', 'emoji': '💚'},
    'Z4_无氧':    {'min_pct': 0.80, 'max_pct': 0.90, 'color': '#e67e22', 'emoji': '🧡'},
    'Z5_极限':    {'min_pct': 0.90, 'max_pct': 1.00, 'color': '#e74c3c', 'emoji': '❤️'},
}

# ============================================================
# 配速等级参考 (min/km)
# ============================================================
PACE_LEVELS = {
    '精英':   {'max': 3.5,  'emoji': '🏆'},
    '优秀':   {'max': 4.0,  'emoji': '⭐'},
    '良好':   {'max': 4.5,  'emoji': '👍'},
    '中等':   {'max': 5.0,  'emoji': '🏃'},
    '入门':   {'max': 5.5,  'emoji': '🐢'},
    '休闲':   {'max': 99.0, 'emoji': '🚶'},
}

# ============================================================
# 默认配置
# ============================================================
DEFAULT_CONFIG = {
    'data_dir': '~/.powerfun/data',
    'state_file': '~/.powerfun/last_fetch.json',
    'report_dir': '~/.powerfun/reports',
    'cache_dir': '~/.powerfun/cache',
    'max_retries': 3,
    'rate_limit_wait_sec': 3600,  # 限流时等待 1 小时
    'page_size': 100,             # Garmin API 分页大小
    'default_date_range_days': 30,
    'hr_zone_method': 'max_hr',   # 心率区间计算方法: max_hr | hrr (心率储备)
}

# Garmin API 端点 (China 区域)
GARMIN_API = {
    'base_url': 'https://connect.garmin.cn',
    'sso_url': 'https://sso.garmin.cn/sso',
    'modern_url': 'https://connect.garmin.cn/modern',
    'activities': '/modern/proxy/activitylist-service/activities',
    'activity_details': '/modern/proxy/activity-service/activity',
    'user_summary': '/modern/proxy/userprofile-service/user-profile',
}
