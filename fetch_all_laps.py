#!/usr/bin/env python3
"""批量拉取全量分圈数据（首次运行用）"""
import sys, os, time, logging
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import garth
from src.config import DEFAULT_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fetch_laps")

# 配置 China 区域
garth.configure(domain="garmin.cn")

# 加载 token
token_path = Path(DEFAULT_CONFIG["data_dir"]).expanduser() / "garmin_tokens"
if not token_path.exists():
    logger.error(f"Token 文件不存在: {token_path}，请先正常登录")
    sys.exit(1)

garth.resume(str(token_path))
logger.info(f"✅ 已加载 token, 用户: {garth.client.username}")

# 读取已处理的活动 ID
parquet_path = Path.home() / "Documents" / "Run" / "running_data.parquet"
df = pd.read_parquet(parquet_path)
activity_ids = df["activity_id"].dropna().astype(int).tolist()
logger.info(f"📋 共 {len(activity_ids)} 条活动需要拉取分圈数据")

# 分圈数据持久化
lap_parquet_path = Path(DEFAULT_CONFIG["data_dir"]).expanduser() / "lap_data.parquet"
all_laps = []

def load_existing_lap_ids():
    if lap_parquet_path.exists():
        existing = pd.read_parquet(lap_parquet_path)
        return set(existing["activity_id"].unique())
    return set()

existing_ids = load_existing_lap_ids()
if existing_ids:
    logger.info(f"📦 已有分圈缓存: {len(existing_ids)} 条活动，跳过")
    activity_ids = [aid for aid in activity_ids if aid not in existing_ids]
    logger.info(f"📋 还需拉取: {len(activity_ids)} 条")

def fetch_lap_data(activity_id: int) -> list:
    try:
        response = garth.connectapi(f"/activity-service/activity/{activity_id}/laps")
        if not response or not isinstance(response, dict):
            return []
        lap_dtos = response.get("lapDTOs", [])
        if not lap_dtos:
            return []
        laps = []
        for lap in lap_dtos:
            distance = lap.get("distance", 0)
            duration = lap.get("duration", 0)
            pace = duration / (distance / 1000.0) if distance > 0 else 0
            laps.append({
                "activity_id": activity_id,
                "lap_index": lap.get("lapIndex", 0),
                "distance_m": distance,
                "duration_sec": duration,
                "pace_sec_per_km": round(pace, 2),
                "avg_hr": lap.get("averageHR"),
                "max_hr": lap.get("maxHR"),
                "avg_power": lap.get("averagePower"),
                "cadence": lap.get("averageRunCadence"),
                "elevation_gain_m": lap.get("elevationGain", 0),
            })
        return laps
    except Exception as e:
        logger.warning(f"获取分圈数据失败 (activity {activity_id}): {e}")
        return []

def save_laps(laps: list):
    if not laps:
        return
    existing = pd.DataFrame()
    if lap_parquet_path.exists():
        try:
            existing = pd.read_parquet(lap_parquet_path)
        except Exception:
            existing = pd.DataFrame()
    new_df = pd.DataFrame(laps)
    if existing.empty:
        merged = new_df
    else:
        merged = pd.concat([existing, new_df], ignore_index=True)
        merged = merged.drop_duplicates(subset=["activity_id", "lap_index"], keep="last")
    merged.to_parquet(lap_parquet_path, index=False)
    logger.info(f"分圈数据已保存: {len(merged)} 条记录 -> {lap_parquet_path}")

# 逐条拉取（每 2 秒请求一次，避免触发限流）
success_count = 0
fail_count = 0
no_lap_count = 0
batch_size = 10
batch_laps = []

for i, aid in enumerate(activity_ids, 1):
    logger.info(f"[{i}/{len(activity_ids)}] 拉取 activity {aid}...")
    laps = fetch_lap_data(aid)
    
    if laps:
        batch_laps.extend(laps)
        success_count += 1
        logger.info(f"  ✅ {len(laps)} 圈")
    else:
        no_lap_count += 1
        logger.info(f"  ⏭️ 无分圈数据")
    
    # 每 10 条保存一次
    if len(batch_laps) >= batch_size * 5 or i == len(activity_ids):
        if batch_laps:
            save_laps(batch_laps)
            batch_laps = []
    
    # 频率控制：每 2 秒一次
    if i < len(activity_ids):
        time.sleep(2)

logger.info(f"✅ 分圈数据拉取完成: 成功 {success_count} 条, 无数据 {no_lap_count} 条, 失败 {fail_count} 条")
