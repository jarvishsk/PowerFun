"""PowerFun 配置模块

定义字段映射表、心率区间、默认参数等。
"""
from pathlib import Path

# 项目根目录（基于 config.py 所在目录计算）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

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
        'source': 'distance',
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
    },
    'hr_zone_1_sec': { 'source': 'hrTimeInZone_1', 'transform': 'identity', 'description': 'Z1 心率区间时长（秒）' },
    'hr_zone_2_sec': { 'source': 'hrTimeInZone_2', 'transform': 'identity', 'description': 'Z2 心率区间时长（秒）' },
    'hr_zone_3_sec': { 'source': 'hrTimeInZone_3', 'transform': 'identity', 'description': 'Z3 心率区间时长（秒）' },
    'hr_zone_4_sec': { 'source': 'hrTimeInZone_4', 'transform': 'identity', 'description': 'Z4 心率区间时长（秒）' },
    'hr_zone_5_sec': { 'source': 'hrTimeInZone_5', 'transform': 'identity', 'description': 'Z5 心率区间时长（秒）' },
    # 功率区间字段
    'power_zone_1_sec': { 'source': 'powerTimeInZone_1', 'transform': 'identity', 'description': '功率 Z1 时长（秒）' },
    'power_zone_2_sec': { 'source': 'powerTimeInZone_2', 'transform': 'identity', 'description': '功率 Z2 时长（秒）' },
    'power_zone_3_sec': { 'source': 'powerTimeInZone_3', 'transform': 'identity', 'description': '功率 Z3 时长（秒）' },
    'power_zone_4_sec': { 'source': 'powerTimeInZone_4', 'transform': 'identity', 'description': '功率 Z4 时长（秒）' },
    'power_zone_5_sec': { 'source': 'powerTimeInZone_5', 'transform': 'identity', 'description': '功率 Z5 时长（秒）' },
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
    'start_lon',          # 起点经度,
    'aerobic_training_effect',   # 有氧训练效果
    'anaerobic_training_effect', # 无氧训练效果
    'training_effect_label',     # 训练效果文字
    'training_load',             # 训练负荷
    'aerobic_te_message',        # 有氧 TE 文字消息
    'anaerobic_te_message',      # 无氧 TE 文字消息
    'stride_length',             # 步幅 (cm)
    'vO2_max',                   # 最大摄氧量
    'bmr_calories',              # 基础代谢卡路里
]

# ============================================================
# 📝 用户可配置参数（首次使用时按实测数据修改）
# ============================================================
# max_hr: 最大心率（实测值，不同用户不同）
# resting_hr: 静息心率（实测值，不同用户不同）
USER_CONFIG = {
    'max_hr': 188,
    'resting_hr': 60,
}

# ============================================================
# 心率区间定义（Karvonen HRR 法固定百分比，禁止修改）
# ============================================================
HR_ZONE_PERCENTAGES = {
    'Z1': {'min_pct': 0.01, 'max_pct': 0.74,  'name': '有氧基础',     'name_en': 'Aerobic Base',       'purpose': '恢复跑、基础有氧'},
    'Z2': {'min_pct': 0.74, 'max_pct': 0.84,  'name': '有氧耐力',     'name_en': 'Aerobic Endurance',  'purpose': 'MAF训练、LSD'},
    'Z3': {'min_pct': 0.84, 'max_pct': 0.88,  'name': '乳酸阈值',     'name_en': 'Lactate Threshold',  'purpose': 'Tempo跑、半马配速'},
    'Z4': {'min_pct': 0.88, 'max_pct': 0.94,  'name': '无氧耐力',     'name_en': 'Anaerobic Endurance', 'purpose': '间歇训练、10K配速'},
    'Z5': {'min_pct': 0.94, 'max_pct': 1.00,  'name': '最大强度',     'name_en': 'Maximum Effort',     'purpose': '冲刺、最大心率训练'},
}

# ============================================================
# 默认配置
# ============================================================
DEFAULT_CONFIG = {
    'data_dir': str(PROJECT_ROOT / '.data'),
    'state_file': str(PROJECT_ROOT / '.data' / 'last_fetch.json'),
    'report_dir': str(Path.home() / 'Documents' / 'Run'),
    'cache_dir': str(PROJECT_ROOT / '.data'),
    'max_retries': 3,
    'rate_limit_wait_sec': 3600,  # 限流时等待 1 小时
    'page_size': 100,             # Garmin API 分页大小
    'default_date_range_days': 30,
    'hr_zone_method': 'hrr',        # 心率区间计算方法: Garmin 原生数据与本地计算均使用 Karvonen HRR（心率储备法）
    'icloud_deep_analysis_dir': str(Path.home() / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs' / 'RUN'),
    # 心率参数
    'max_hr': USER_CONFIG.get('max_hr'),             # 默认最大心率（老板实测）
    'resting_hr': USER_CONFIG.get('resting_hr'),          # 默认静息心率
    # 过滤阈值
    'max_distance_km': 50,     # 单次跑步最大距离过滤阈值
    # 深析参数
    'deep_analysis_max_runs': 5,  # 对比分析取最近 N 次同类型
    # PDF 尺寸
    'pdf_height': '1600mm',    # PDF 页面高度默认值（主报告）
    'pdf_width': '370mm',      # PDF 页面宽度默认值（主报告）
    'deep_pdf_height': '1400mm',    # 深析报告 PDF 高度
    'deep_pdf_width': '230mm',     # 深析报告 PDF 宽度
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

# 心率区间颜色（供各模块统一使用）
ZONE_COLORS = {
    'Z1': '#808080',    # 灰色
    'Z2': '#87CEEB',    # 天蓝色
    'Z3': '#32CD32',    # 绿色
    'Z4': '#FFA500',    # 橙色
    'Z5': '#FF0000',    # 红色
}
