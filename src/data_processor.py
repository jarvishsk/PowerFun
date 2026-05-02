"""PowerFun 数据清洗与字段映射模块

将 Garmin API 原始数据映射为跑分标准字段，进行数据清洗和校验。
支持 garth API 原始格式 和 garmer 导出格式。
"""

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from src.config import FIELD_MAPPING, EXTRA_FIELDS

logger = logging.getLogger(__name__)


class DataProcessor:
    """数据处理器：清洗 + 字段映射 + 校验"""

    def __init__(self):
        self.field_mapping = FIELD_MAPPING
        self.extra_fields = EXTRA_FIELDS
        self._use_summary_extractor = False  # 用于标识是否使用 summary 提取器

    def process(self, raw_activities: list[dict]) -> pd.DataFrame:
        """处理原始活动数据，返回标准化 DataFrame

        Args:
            raw_activities: Garmin API 返回的原始活动列表
                           (支持 garth connectapi 格式 和 garmer 导出格式)

        Returns:
            标准化后的 DataFrame
        """
        if not raw_activities:
            logger.warning("无活动数据")
            return pd.DataFrame()

        logger.info(f"开始处理 {len(raw_activities)} 条活动数据...")

        # 检测数据格式，在开始处理前一次性确定使用哪种提取器
        self._use_summary_extractor = any('summaryDTO' in a or ('raw_data' in a and 'summaryDTO' in a['raw_data']) for a in raw_activities)

        # Step 1: 提取并映射基础字段
        records = []
        skipped = 0
        for i, activity in enumerate(raw_activities):
            record = self._map_activity(activity)
            # 跳过距离为 0 或空的记录
            if record.get("distance") and record["distance"] > 0:
                records.append(record)
            else:
                skipped += 1

        if not records:
            logger.warning("所有活动距离均为 0，无有效数据")
            return pd.DataFrame()

        df = pd.DataFrame(records)
        logger.info(f"有效活动: {len(records)} 条 (跳过 {skipped} 条零距离)")

        # Step 2: 数据清洗
        df = self._clean(df)

        # Step 3: 派生字段
        df = self._derive(df)

        # Step 4: 排序
        if "date" in df.columns:
            df = df.sort_values("date").reset_index(drop=True)

        logger.info(f"数据处理完成: {len(df)} 条记录, {len(df.columns)} 个字段")
        return df

    def _map_activity(self, activity: dict) -> dict:
        """将单条活动映射为标准字段（支持两种格式: garth API / garmer）"""
        try:
            return self._map_activity_impl(activity)
        except Exception as e:
            act_name = activity.get("activityName") or activity.get("activity_name", "未知")
            logger.warning(f"处理活动数据异常 [{act_name}]: {e}，跳过此条活动")
            return {}

    def _map_activity_impl(self, activity: dict) -> dict:
        """_map_activity 的实际实现"""
        record = {}

        # 根据预设的标志选择提取器
        if self._use_summary_extractor:
            # 从 summaryDTO 提取数据 (garmer 格式)
            summary = activity.get("summaryDTO", {})
            raw_data = activity.get("raw_data", {})
            if raw_data and not summary:
                summary = raw_data.get("summaryDTO", {})

            # 映射标准字段
            for target_field, mapping in self.field_mapping.items():
                source = mapping["source"]
                transform = mapping["transform"]
                value = self._extract_from_summary(summary, source, activity)

                if value is not None:
                    value = self._apply_transform(value, transform, source)
                record[target_field] = value

            # 保留额外字段
            for field in self.extra_fields:
                record[field] = self._extract_extra(summary, field, activity)
        else:
            # garth API 格式: 通过字段映射提取
            for target_field, mapping in self.field_mapping.items():
                source = mapping["source"]
                transform = mapping["transform"]
                value = self._extract_from_garth(activity, source)

                if value is not None:
                    value = self._apply_transform(value, transform, source)
                record[target_field] = value

            # 保留额外字段
            for field in self.extra_fields:
                record[field] = self._extract_extra({}, field, activity)  # garth 格式无 summaryDTO

        return record

    def _extract_from_summary(self, summary: dict, source: str, activity: dict):
        """从 summaryDTO 中提取字段值 (garmer 格式)

        处理字段名映射:
        - distance_km -> summaryDTO.distance (meters) / 1000
        - elapsed_min -> summaryDTO.duration (seconds) / 60
        - pace_min_per_km -> 从 duration/distance 计算
        - maxSpeed -> summaryDTO.maxSpeed (m/s) * 3.6 -> km/h
        """
        # 直接映射 (配置 source -> summaryDTO 字段名)
        direct_map = {
            "startTimeLocal": "startTimeLocal",
            "activityName": None,  # 特殊处理：从 activity 顶层获取
            "distance_km": "distance",
            "avg_hr": "averageHR",
            "max_hr": "maxHR",
            "pace_min_per_km": None,  # 设计意图: 在下方通过 duration/distance 计算，不走 _apply_transform
            "maxSpeed": "maxSpeed",
            "elapsed_min": "duration",
            "calories": "calories",
            "avg_cadence": "averageRunCadence",
            "verticalRatio": "verticalRatio",
            "avg_power": "averagePower",
            "elevation_gain_m": "elevationGain",
            "activity_type": None,
            "hrTimeInZone_1": None,  # 特殊处理：从 activity 顶层获取
            "hrTimeInZone_2": None,  # 特殊处理：从 activity 顶层获取
            "hrTimeInZone_3": None,  # 特殊处理：从 activity 顶层获取
            "hrTimeInZone_4": None,  # 特殊处理：从 activity 顶层获取
            "hrTimeInZone_5": None,  # 特殊处理：从 activity 顶层获取
        }

        api_field = direct_map.get(source)
        if api_field is None:
            # 特殊处理
            if source == "pace_min_per_km":
                dist = summary.get("distance", 0)
                dur = summary.get("duration", 0)
                if dist and dur and dist > 0:
                    # duration in seconds, distance in meters
                    return (dur / 60.0) / (dist / 1000.0)
            elif source == "activityName":
                # activity_name 在 activity 顶层，不在 summaryDTO 中
                return activity.get("activity_name") or activity.get("activityName") or activity.get("locationName") or "--"
            elif source == "activity_type":
                return activity.get("activity_type_key") or activity.get("activityTypeKey", "running")
            elif source.startswith("hrTimeInZone_"):
                # hrTimeInZone 字段在 activity 顶层，不在 summaryDTO 中
                return activity.get(source)
            return None

        value = summary.get(api_field)

        # 单位转换
        if api_field == "distance" and value is not None:
            # meters -> km
            return value / 1000.0
        elif api_field == "duration" and value is not None:
            # seconds -> minutes
            return value / 60.0
        elif api_field == "maxSpeed" and value is not None:
            # m/s -> km/h
            return value * 3.6
        elif api_field == "averagePower" and value is not None:
            return value

        return value

    def _extract_from_garth(self, activity: dict, source: str):
        """从 garth API 格式中提取字段值（入口方法）"""
        if source == "activityName":
            return activity.get("activity_name") or activity.get("activityName") or activity.get("locationName") or "--"
        if source == "maxSpeed":
            return self._convert_garth_value("maxSpeed", activity.get("maxSpeed"))
        if source == "pace_min_per_km":
            return self._extract_pace_from_garth(activity)
        if source == "activity_type":
            return self._extract_activity_type(activity)
        if source.startswith("hrTimeInZone_"):
            return activity.get(source)
        if source in ("avg_power", "max_hr", "avg_hr"):
            return self._extract_hr_power_field(activity, source)

        garth_field = self._GARTH_FIELD_MAP.get(source)
        if garth_field is None:
            return None

        value = activity.get(garth_field)
        return self._convert_garth_value(garth_field, value)

    # ----------------------------------------------------------
    # 子方法：按字段类型拆分
    # ----------------------------------------------------------
    @staticmethod
    def _extract_activity_type(activity: dict) -> str:
        """提取活动类型"""
        act_type = activity.get("activityType", {})
        if isinstance(act_type, dict):
            return act_type.get("typeKey", "running")
        return str(act_type) if act_type else "running"

    @staticmethod
    def _extract_pace_from_garth(activity: dict):
        """从距离和时间计算配速 (min/km)"""
        dist_m = activity.get("distance", 0)   # meters
        dur_s = activity.get("duration", 0)     # seconds
        if dist_m and dur_s and dist_m > 0:
            dist_km = dist_m / 1000.0
            dur_min = dur_s / 60.0
            return dur_min / dist_km
        return None

    @staticmethod
    def _extract_hr_power_field(activity: dict, source: str):
        """提取心率/功率字段（兼容多种字段名）"""
        alt_field_map = {
            "avg_power": ["avgPower", "averagePower"],
            "max_hr": ["maxHR", "maxHeartRate"],
            "avg_hr": ["averageHR", "avgHeartRate"],
        }
        for field_name in alt_field_map.get(source, []):
            value = activity.get(field_name)
            if value is not None:
                return value
        return None

    # 基础字段映射：source -> garth API 字段名
    _GARTH_FIELD_MAP = {
        "startTimeLocal": "startTimeLocal",
        "activityName": "activityName",
        "distance": "distance",
        "elapsed_min": "duration",
        "calories": "calories",
        "avg_cadence": "averageRunningCadenceInStepsPerMinute",
        "verticalRatio": "avgVerticalRatio",
        "elevation_gain_m": "elevationGain",
        # 心率区间
        "hrTimeInZone_1": "hrTimeInZone_1",
        "hrTimeInZone_2": "hrTimeInZone_2",
        "hrTimeInZone_3": "hrTimeInZone_3",
        "hrTimeInZone_4": "hrTimeInZone_4",
        "hrTimeInZone_5": "hrTimeInZone_5",
        # 功率区间
        "powerTimeInZone_1": "powerTimeInZone_1",
        "powerTimeInZone_2": "powerTimeInZone_2",
        "powerTimeInZone_3": "powerTimeInZone_3",
        "powerTimeInZone_4": "powerTimeInZone_4",
        "powerTimeInZone_5": "powerTimeInZone_5",
    }

    @staticmethod
    def _convert_garth_value(garth_field: str, value):
        """单位转换：garth API 返回的单位转为标准单位"""
        if value is None:
            return None
        if garth_field == "distance":
            return value / 1000.0  # meters -> km
        elif garth_field == "duration":
            return value / 60.0  # seconds -> minutes
        elif garth_field == "maxSpeed":
            return value * 3.6  # m/s -> km/h
        return value

    def _extract_extra(self, summary: dict, field: str, activity: dict):
        """从 garth 格式中提取额外字段"""
        # 直接从 activity 或 summary 获取
        value = activity.get(field) or summary.get(field)
        if value is not None:
            return value

        # 特殊处理需要多字段 fallback 的
        if field == "training_effect":
            return summary.get("trainingEffect")
        elif field == "max_power":
            return summary.get("maxPower") or activity.get("maxPower")
        elif field == "normalized_power":
            return activity.get("normalizedPower") or summary.get("normalizedPower")
        elif field == "aerobic_training_effect":
            return activity.get("aerobicTrainingEffect") or summary.get("aerobicTrainingEffect")
        elif field == "anaerobic_training_effect":
            return activity.get("anaerobicTrainingEffect") or summary.get("anaerobicTrainingEffect")
        elif field == "vO2_max":
            return activity.get("vO2Max") or summary.get("vO2Max")
        elif field == "bmr_calories":
            return activity.get("bmrCalories") or summary.get("bmrCalories")
        elif field == "stride_length":
            return activity.get("strideLength")
        elif field == "ground_contact_time":
            return summary.get("groundContactTime") or activity.get("avgGroundContactTime") or activity.get("groundContactTime")
        elif field == "activity_id":
            return activity.get("activity_id") or activity.get("activityId")
        elif field == "location":
            return activity.get("locationName") or activity.get("activity_name", "").replace(" 跑步", "")
        elif field == "elevation_loss_m":
            return summary.get("elevationLoss")
        elif field == "steps":
            return summary.get("steps") or activity.get("steps")
        elif field == "start_lat":
            return summary.get("startLatitude") or activity.get("start_latitude")
        elif field == "start_lon":
            return summary.get("startLongitude") or activity.get("start_longitude")
        elif field == "training_effect_label":
            return activity.get("trainingEffectLabel")
        elif field == "training_load":
            return activity.get("activityTrainingLoad")
        elif field == "aerobic_te_message":
            return activity.get("aerobicTrainingEffectMessage")
        elif field == "anaerobic_te_message":
            return activity.get("anaerobicTrainingEffectMessage")
        return None

    def _apply_transform(self, value, transform: str, source: str = ""):
        """应用字段转换"""
        if transform == "identity":
            return value
        elif transform == "extract_datetime":
            return self._parse_datetime(value)
        elif transform == "pace_to_mmss":
            return self._pace_to_mmss(value)
        elif transform == "speed_to_pace_mmss":
            return self._speed_to_pace_mmss(value)
        elif transform == "minutes_to_hhmmss":
            return self._minutes_to_hhmmss(value)
        else:
            return value

    def _parse_datetime(self, value) -> Optional[datetime]:
        """解析日期时间字符串"""
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            # Unix timestamp (ms)
            return datetime.fromtimestamp(value / 1000)

        formats = [
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(str(value), fmt)
            except ValueError:
                continue

        logger.warning(f"无法解析日期: {value}")
        return None

    def _pace_to_mmss(self, pace_min_per_km) -> str:
        """配速 (min/km) -> mm:ss 格式

        示例: 5.78 -> "05:47"
        """
        if pace_min_per_km is None:
            return "--:--"
        try:
            pace = float(pace_min_per_km)
            if pace <= 0 or pace > 999:
                return "--:--"
            minutes = int(pace)
            seconds = int(round((pace - minutes) * 60))
            # 处理 60 秒进位
            if seconds >= 60:
                minutes += 1
                seconds -= 60
            return f"{minutes:02d}:{seconds:02d}"
        except (ValueError, TypeError):
            return "--:--"

    def _speed_to_pace_mmss(self, max_speed) -> str:
        """最大速度 (km/h) -> 配速 mm:ss/km

        示例: 10.5 km/h -> pace = 60/10.5 = 5.71 min/km -> "05:43"
        """
        if max_speed is None or max_speed <= 0:
            return "--:--"
        try:
            speed_kmh = float(max_speed)
            if speed_kmh <= 0:
                return "--:--"
            pace_min_per_km = 60.0 / speed_kmh
            minutes = int(pace_min_per_km)
            seconds = int(round((pace_min_per_km - minutes) * 60))
            if seconds >= 60:
                minutes += 1
                seconds -= 60
            return f"{minutes:02d}:{seconds:02d}"
        except (ValueError, TypeError):
            return "--:--"

    def _minutes_to_hhmmss(self, minutes) -> str:
        """分钟数 -> hh:mm:ss 格式

        示例: 99.73 min -> "01:39:44"
        """
        if minutes is None:
            return "--:--:--"
        try:
            total_seconds = int(round(float(minutes) * 60))
            if total_seconds < 0:
                return "--:--:--"
            hours = total_seconds // 3600
            mins = (total_seconds % 3600) // 60
            secs = total_seconds % 60
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        except (ValueError, TypeError):
            return "--:--:--"

    def _clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """数据清洗"""
        # 数值列类型转换
        numeric_cols = [
            "distance", "avg_hr", "max_hr", "calories", "cadence",
            "vertical_ratio", "avg_power", "elevation_gain",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 日期列
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])

        # 去除距离为 0 或 NaN 的记录
        if "distance" in df.columns:
            df = df[df["distance"] > 0].copy()

        return df

    def _derive(self, df: pd.DataFrame) -> pd.DataFrame:
        """派生字段计算"""
        # 保留原始数值 duration (分钟) 供分析器使用
        # garth 格式下 elapsed_min 已经是分钟数值，直接使用
        if "elapsed_min" in df.columns and "duration_min" not in df.columns:
            df["duration_min"] = df["elapsed_min"]
        elif "duration" in df.columns:
            def parse_duration_to_min(val):
                if pd.isna(val) or not isinstance(val, str):
                    return None
                try:
                    parts = val.split(":")
                    if len(parts) == 3:
                        return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60.0
                    elif len(parts) == 2:
                        return int(parts[0]) + int(parts[1]) / 60.0
                except (ValueError, TypeError):
                    pass
                return None
            df["duration_min"] = df["duration"].apply(parse_duration_to_min)

        # 保留原始数值配速 (min/km) 供分析器使用
        # avg_pace 列已经是 mm:ss 字符串，新增 pace_min_per_km 数值列
        if "avg_pace" in df.columns:
            def parse_pace_to_min(val):
                if pd.isna(val) or not isinstance(val, str) or val == "--:--":
                    return None
                try:
                    parts = val.split(":")
                    if len(parts) == 2:
                        return int(parts[0]) + int(parts[1]) / 60.0
                except (ValueError, TypeError):
                    pass
                return None
            df["pace_min_per_km"] = df["avg_pace"].apply(parse_pace_to_min)

        # 检查 pace_min_per_km 是否存在
        if "pace_min_per_km" not in df.columns or df["pace_min_per_km"].isna().all():
            logger.error("关键数据缺失: pace_min_per_km（平均配速）未从 Garmin API 获取，无法继续分析。")
            raise ValueError("pace_min_per_km 数据缺失，请确保 Garmin API 返回配速数据后再运行分析。")

        # 检查有多少条记录的配速为空
        missing_pace_count = df["pace_min_per_km"].isna().sum()
        if missing_pace_count > 0:
            logger.warning(f"{missing_pace_count} 条记录的 pace_min_per_km 为空（可能为异常数据），将跳过这些记录。")

        # 配速 (min/km) — 如果还没有的话，从 distance/duration_min 反推（仅作为兜底）
        if "pace_min_per_km" not in df.columns and "distance" in df.columns and "duration_min" in df.columns:
            df["pace_min_per_km"] = df.apply(
                lambda r: r["distance"] / r["duration_min"]
                if r["duration_min"] and r["distance"] and r["duration_min"] > 0
                else None, axis=1)

        # 日期相关派生
        if "date" in df.columns:
            df["year"] = df["date"].dt.year
            df["month"] = df["date"].dt.month
            df["day_of_week"] = df["date"].dt.dayofweek  # 0=Monday
            df["week"] = df["date"].dt.isocalendar().week.astype(int)
            df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
            # year_month: 用于原始报告生成器
            df["year_month"] = df["date"].dt.to_period('M').astype(str)

        # avg_pace_sec: 配速秒数 (原始报告生成器需要)
        if "avg_pace" in df.columns:
            df["avg_pace_sec"] = df["avg_pace"].apply(self._pace_str_to_seconds)

        # avg_pace_fmt: 配速格式化字符串 (原始报告生成器需要)
        if "avg_pace_sec" in df.columns:
            df["avg_pace_fmt"] = df["avg_pace_sec"].apply(self._seconds_to_pace)

        return df

    @staticmethod
    def _pace_str_to_seconds(pace_str) -> "Optional[int]":
        """将配速字符串 (mm:ss) 转换为秒数"""
        if pd.isna(pace_str) or not isinstance(pace_str, str) or pace_str == "--:--":
            return None
        try:
            parts = pace_str.split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, TypeError):
            pass
        return None

    @staticmethod
    def _seconds_to_pace(seconds) -> str:
        """将秒数转换为配速字符串 mm:ss"""
        if seconds is None or pd.isna(seconds):
            return "--"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"

    def validate(self, df: pd.DataFrame) -> dict:
        """数据质量校验"""
        issues = {}

        if df.empty:
            return {"error": "空数据"}

        # 必填字段检查
        required = ["date", "distance"]
        for col in required:
            if col not in df.columns:
                issues[col] = f"缺少必填字段: {col}"
            elif df[col].isna().any():
                issues[col] = f"字段 {col} 有 {df[col].isna().sum()} 个空值"

        # 距离合理性检查
        if "distance" in df.columns:
            outliers = df[df["distance"] > 200]  # 超过 200km 异常
            if not outliers.empty:
                issues["distance"] = f"{len(outliers)} 条记录距离 > 200km，可能异常"

        # 心率合理性检查
        if "avg_hr" in df.columns:
            outliers = df[(df["avg_hr"] > 220) | (df["avg_hr"] < 40)]
            if not outliers.empty:
                issues["avg_hr"] = f"{len(outliers)} 条记录心率异常"

        return issues

    def to_csv(self, df: pd.DataFrame, path: str) -> str:
        """导出为标准 CSV 格式 (兼容跑分技能)"""
        # 选择输出列
        output_cols = [
            "date_str", "distance", "avg_hr", "max_hr", "avg_pace",
            "best_pace", "duration_min", "calories", "cadence",
            "vertical_ratio", "avg_power", "elevation_gain",
        ]
        available = [c for c in output_cols if c in df.columns]
        export_df = df[available].copy()

        # 格式化日期
        if "date_str" not in export_df.columns and "date" in df.columns:
            export_df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")

        export_df.to_csv(path, index=False, encoding="utf-8-sig")
        logger.info(f"CSV 已导出: {path} ({len(export_df)} 行)")
        return path
