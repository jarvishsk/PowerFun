"""Garmin Connect Personal API 接入（中国区）。

- Personal API Key：``.secrets/garmin-personal-api-key``（权限 600，不进 Git/聊天/日志）
- Bearer token 缓存：``.secrets/garmin-personal-bearer-token.json``（token 最长 24 小时，过期自动用 Key 重换）
- 中国区端点：``personal.connectapi.garmin.cn``（通过官方客户端的 BASE_URL 环境变量切换，不回退国际区）
- 认证方案：官方 ``garmin-connect-personal-api-python`` 客户端；不使用 garth SSO、不读取账号密码

对外接口：
- ``garmin_check()``：``python main.py --garmin-check``，仅验证认证、资料和单次活动读取
- ``fetch_new(stage_dir=None)``：``python main.py --fetch-new [--stage DIR]``，增量拉取
"""

import json
import logging
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.config import DEFAULT_CONFIG, PROJECT_ROOT

logger = logging.getLogger("PowerFun.personal_api")

# ---- 凭据与端点 ----
SECRETS_DIR = PROJECT_ROOT / ".secrets"
API_KEY_FILE = SECRETS_DIR / "garmin-personal-api-key"
BEARER_TOKEN_CACHE_FILE = SECRETS_DIR / "garmin-personal-bearer-token.json"
CHINA_BASE_URL = "https://personal.connectapi.garmin.cn"

# 活动列表关键字段（B 组字段对照用）：心率区间、功率、步频、VR、GCT、温度、训练效果和负荷
# 注意：Personal API 字段名为 averageRunningCadenceInStepsPerMinute / avgVerticalRatio / avgGroundContactTime
# （旧 garth 口径 averageRunCadence / verticalRatio / groundContactTime 不存在）；vO2MaxValue 亦不在返回中
KEY_LIST_FIELDS = [
    "hrTimeInZone_1", "hrTimeInZone_2", "hrTimeInZone_3", "hrTimeInZone_4", "hrTimeInZone_5",
    "powerTimeInZone_1", "powerTimeInZone_2", "powerTimeInZone_3", "powerTimeInZone_4", "powerTimeInZone_5",
    "avgPower", "maxPower", "normPower",
    "averageRunningCadenceInStepsPerMinute", "maxRunningCadenceInStepsPerMinute",
    "avgVerticalRatio", "avgGroundContactTime",
    "minTemperature", "maxTemperature",
    "aerobicTrainingEffect", "anaerobicTrainingEffect",
    "activityTrainingLoad",
]


def _prepare_secrets_dir() -> None:
    """创建 .secrets（700）并收紧已有关键文件权限（600）"""
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS_DIR, 0o700)
    for f in (API_KEY_FILE, BEARER_TOKEN_CACHE_FILE):
        if f.exists():
            os.chmod(f, 0o600)


def _load_api_key() -> Optional[str]:
    """读取中国区 Personal API Key；不存在时返回 None（调用方须暂停在线步骤）"""
    _prepare_secrets_dir()
    if not API_KEY_FILE.exists():
        logger.error(
            f"Personal API Key 文件不存在: {API_KEY_FILE}\n"
            "请老板在本机写入 Key 文件（chmod 600），不要在聊天中发送 Key。"
        )
        return None
    os.chmod(API_KEY_FILE, 0o600)
    key = API_KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        logger.error(f"Key 文件为空: {API_KEY_FILE}")
        return None
    return key


def _build_client():
    """构建官方客户端（中国区端点 + 本地 token 缓存）。返回 (client, authenticator)"""
    from garmin_personal_api import (
        GarminPersonalApiClient,
        PersonalApiAuthenticator,
    )

    # 中国区端点：只在此进程内切换，不回退国际区
    os.environ["GARMIN_PERSONAL_API_BASE_URL"] = CHINA_BASE_URL

    api_key = _load_api_key()
    if api_key is None:
        return None, None

    authenticator = PersonalApiAuthenticator(bearer_token_cache_file=BEARER_TOKEN_CACHE_FILE)
    if BEARER_TOKEN_CACHE_FILE.exists():
        os.chmod(BEARER_TOKEN_CACHE_FILE, 0o600)
    token = authenticator.obtain_token(api_key)
    client = GarminPersonalApiClient(token.access_token)
    return client, authenticator


# ------------------------------------------------------------------
# --garmin-check：仅验证认证、资料和单次活动读取，不改正式数据
# ------------------------------------------------------------------
def garmin_check() -> bool:
    """验证中国区 Personal API 认证、用户资料和单次活动读取。

    只写凭据缓存和非敏感日志。
    """
    try:
        client, _ = _build_client()
    except Exception as e:
        logger.error(f"Garmin Personal API 认证失败: {type(e).__name__}: {e}")
        return False
    if client is None:
        return False

    try:
        profile = client.get_user_profile_settings()
        if not isinstance(profile, dict) or not profile:
            logger.error("用户资料响应为空")
            return False
        # 只报告成功/失败，不输出个人资料内容
        logger.info("✅ 认证成功，用户资料读取成功")

        acts = client.search_activities(limit=1, activity_type="running")
        act_list = acts if isinstance(acts, list) else acts.get("activities", [])
        if not act_list:
            logger.error("活动列表为空，无法验证单次活动读取")
            return False
        first = act_list[0]
        act_id = first.get("activityId") or first.get("activity_id")
        logger.info(f"✅ 活动列表读取成功: 最新活动 id={act_id}")

        detail = client.get_activity(act_id)
        detail_id = detail.get("activityId") or detail.get("activity_id")
        if str(detail_id) != str(act_id):
            logger.error(f"活动详情 id 不一致: {detail_id} != {act_id}")
            return False
        logger.info(f"✅ 单次活动详情读取成功: id={detail_id}")

        # 分圈验证：laps 端点已下线（404），改用原始 FIT 解析（只读，不写数据）
        try:
            laps = _fetch_laps_from_fit(client, act_id)
            logger.info(f"✅ FIT 分圈解析成功: id={act_id}，{len(laps)} 圈")
            # 基准活动回归锚点：此前已验证应为 16 圈
            if str(act_id) == "659451010" and len(laps) != 16:
                logger.error(f"基准活动分圈数异常: {len(laps)} != 16")
                return False
        except Exception as e:
            logger.error(f"FIT 分圈解析失败: {e}")
            return False
        return True
    except Exception as e:
        logger.error(f"Garmin 在线验证失败: {type(e).__name__}: {e}")
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass


# ------------------------------------------------------------------
# --fetch-new：增量拉取（--stage 写隔离目录，否则写正式 data/）
# ------------------------------------------------------------------
def _read_state() -> Optional[dict]:
    state_file = Path(DEFAULT_CONFIG["state_file"])
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"读取状态文件失败: {e}")
        return None


def _get_id(a: dict):
    return (a.get("activity_id") or a.get("activityId") or
            a.get("id") or a.get("activityID") or 0)


def _is_auto_title(title: str) -> bool:
    """Garmin 中文区域自动标题以"跑步"结尾（与原抓取实现同口径）"""
    if not title:
        return True
    return str(title).strip().endswith('跑步')


def _title_guard_keep_cached(cached_rec: dict, fetched_rec: dict) -> bool:
    """标题保护：缓存是自定义标题、拉取到自动标题时，保留缓存（与原实现同口径）"""
    cached_title = cached_rec.get('activityName') or ''
    fetched_title = fetched_rec.get('activityName') or ''
    if not cached_title:
        return False
    if _is_auto_title(cached_title) or not _is_auto_title(fetched_title):
        return False
    return True


def _parse_fit_laps(zip_bytes: bytes, activity_id) -> list[dict]:
    """从 download_activity 返回的 ZIP 中解析 FIT 分圈。

    Personal API 的 /activity-service/activity/{id}/laps 端点已下线（404），
    原始 FIT 是官方替代来源。映射口径与既有缓存逐圈比对一致（基准活动
    659451010，16 圈，全部字段最大差为 0）：

    - duration_sec  = total_timer_time（不含停表；total_elapsed_time 含暂停，不采用）
    - cadence       = (avg_running_cadence + avg_fractional_cadence) × 2
                      （Connect 浮点步频口径：整数步/单脚 + 小数部分，翻倍为总步频）
    - 其余字段同名直取；FIT lap 消息无 lapIndex，圈号按消息顺序从 1 编号
    """
    import io
    import zipfile

    import numpy as np
    from fitparse import FitFile

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
        if not fit_names:
            raise ValueError("活动 ZIP 内无 FIT 文件")
        fit_bytes = zf.read(fit_names[0])

    def _num(v):
        return float(v) if v is not None else np.nan

    laps = []
    fit = FitFile(io.BytesIO(fit_bytes))
    for idx, rec in enumerate(fit.get_messages("lap"), start=1):
        d = {fd.name: fd.value for fd in rec}
        distance = float(d.get("total_distance") or 0.0)
        duration = float(d.get("total_timer_time") or 0.0)
        pace = duration / (distance / 1000.0) if distance > 0 else 0.0
        cadence_raw = d.get("avg_running_cadence")
        frac = d.get("avg_fractional_cadence") or 0.0
        laps.append({
            "activity_id": activity_id,
            "lap_index": idx,
            "distance_m": distance,
            "duration_sec": duration,
            "pace_sec_per_km": round(pace, 2),
            "avg_hr": _num(d.get("avg_heart_rate")),
            "max_hr": _num(d.get("max_heart_rate")),
            "avg_power": _num(d.get("avg_power")),
            "cadence": (float(cadence_raw) + float(frac)) * 2 if cadence_raw is not None else np.nan,
            "elevation_gain_m": _num(d.get("total_ascent")),
        })
    return laps


def _fetch_laps_from_fit(client, activity_id) -> list[dict]:
    """下载原始 FIT（ZIP）并解析分圈，字段口径与既有 lap_data 一致"""
    zip_bytes = client.download_activity(activity_id)
    return _parse_fit_laps(zip_bytes, activity_id)


def _backup_data_files() -> Optional[Path]:
    """首次正式写入前，将现有数据文件备份到 .runtime/backups/<timestamp>/"""
    data_dir = Path(DEFAULT_CONFIG["data_dir"])
    backup_dir = PROJECT_ROOT / ".runtime" / "backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backed = False
    for name in ("running_data.parquet", "running_data_cleaned.csv",
                 "activities_cache.json", "lap_data.parquet", "last_fetch.json"):
        src = data_dir / name
        if src.exists():
            shutil.copy2(src, backup_dir / name)
            backed = True
    if backed:
        logger.info(f"✅ 正式数据已备份: {backup_dir}")
        return backup_dir
    return None


def fetch_new(stage_dir: Optional[str] = None) -> bool:
    """从迁移的 last_fetch.json 继续增量拉取，按 activity_id 去重，保留标题保护。

    stage_dir 为 None 时写正式 data/（写入前自动备份）；否则全部写入隔离目录。
    """
    stage: Optional[Path] = Path(stage_dir).expanduser() if stage_dir else None
    if stage:
        stage.mkdir(parents=True, exist_ok=True)
        logger.info(f"隔离模式：所有输出写入 {stage}，不覆盖正式 data/")

    client, _ = _build_client()
    if client is None:
        return False  # 密钥文件缺失时 _load_api_key 已给出指引

    data_dir = Path(DEFAULT_CONFIG["data_dir"])
    cache_file = data_dir / "activities_cache.json"

    try:
        # 1) 增量窗口：从正式 last_fetch.json 继续，不全量回填
        state = _read_state()
        if state and state.get("last_date"):
            start_date = datetime.fromisoformat(state["last_date"]) - timedelta(days=1)
            logger.info(f"增量拉取: {start_date.strftime('%Y-%m-%d')} 之后")
        else:
            logger.error("last_fetch.json 缺失，拒绝全量回填；请先恢复状态文件")
            return False
        end_date = datetime.now()

        # 2) 分页拉取活动列表
        all_new: list[dict] = []
        start = 0
        page_size = 100
        while start < 10000:
            resp = client.search_activities(
                start=start, limit=page_size,
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                activity_type="running",
            )
            items = resp if isinstance(resp, list) else resp.get("activities", [])
            if not items:
                break
            all_new.extend(items)
            logger.info(f"已获取 offset={start}, 本页 {len(items)} 条, 累计 {len(all_new)} 条")
            if len(items) < page_size:
                break
            start += page_size
            time.sleep(1)  # 温和限速

        # 3) 与现有缓存去重
        cached: list[dict] = []
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                cached = []
        cached_ids = {_get_id(a) for a in cached if isinstance(a, dict)}
        fetched_ids = {_get_id(a) for a in all_new if isinstance(a, dict)}
        dup_in_fetch = len(all_new) - len(fetched_ids)
        truly_new = [a for a in all_new if _get_id(a) not in cached_ids]
        n_dup_vs_cache = len(all_new) - len(truly_new)
        logger.info(f"拉取 {len(all_new)} 条；对缓存去重后新增 {len(truly_new)} 条"
                    f"（缓存已含 {n_dup_vs_cache} 条，本次拉取内部重复 {dup_in_fetch} 条）")

        # 4) 关键字段缺失统计
        missing_fields: dict[str, int] = {}
        for a in truly_new:
            for f in KEY_LIST_FIELDS:
                if a.get(f) is None:
                    missing_fields[f] = missing_fields.get(f, 0) + 1

        # 5) 合并缓存（标题保护：只保留缓存的自定义标题，其余字段照常更新）
        merged_map = { _get_id(a): a for a in cached if isinstance(a, dict) }
        n_updated = 0
        changed_ids: list = []
        for a in all_new:
            if not isinstance(a, dict):
                continue
            aid = _get_id(a)
            if aid not in merged_map:
                merged_map[aid] = a
                continue
            cached_rec = merged_map[aid]
            if _title_guard_keep_cached(cached_rec, a):
                # 标题保护：采用拉取记录，但保留缓存中的自定义标题（不阻断其他字段更新）
                merged_rec = dict(a)
                merged_rec['activityName'] = cached_rec.get('activityName')
            else:
                merged_rec = a
            if merged_rec != cached_rec:
                merged_map[aid] = merged_rec
                changed_ids.append(aid)
                n_updated += 1
        merged = list(merged_map.values())
        merged.sort(key=lambda x: (_parse_dt(x) or datetime.min), reverse=True)

        # 6) 待处理集合：真正新增 + 内容发生变化的已有活动（未变化的不重复处理）
        to_process = [merged_map[_get_id(a)] for a in truly_new]
        to_process += [merged_map[aid] for aid in changed_ids]
        to_process_ids = {_get_id(a) for a in to_process}
        to_process_ids_str = {str(i) for i in to_process_ids}
        logger.info(f"待处理活动: 新增 {len(truly_new)}，已有更新 {len(changed_ids)}，合计 {len(to_process)}")

        # 7) 拉取待处理活动的分圈（laps 端点已下线，走原始 FIT 解析）
        new_laps: list[dict] = []
        lap_fail_ids: list[str] = []
        for a in to_process:
            aid = _get_id(a)
            try:
                laps = _fetch_laps_from_fit(client, aid)
                new_laps.extend(laps)
            except Exception as e:
                logger.warning(f"分圈拉取失败 (id={aid}): {e}")
                lap_fail_ids.append(str(aid))
            time.sleep(1)

        # 8) 新状态
        latest = None
        for a in merged:
            dt = _parse_dt(a)
            if dt and (latest is None or dt > latest):
                latest = dt
        new_state = {
            "last_date": latest.isoformat() if latest else state.get("last_date"),
            "last_fetch": datetime.now().isoformat(),
            "total_count": len(merged),
        }

        # 9) 清洗 + 分类待处理活动（复用现有数据层，口径不变），并 upsert 主表
        processed_df = None
        processor = None
        if to_process:
            from src.data_processor import DataProcessor
            from src.classifier import HeartRateClassifier, RunClassifier
            processor = DataProcessor()
            pdf = processor.process(to_process)
            if not pdf.empty:
                dist_mask = pdf['distance'] <= DEFAULT_CONFIG['max_distance_km']
                kw = '|'.join(DEFAULT_CONFIG.get('excluded_title_keywords', ['间歇跑']))
                title_mask = ~pdf['title'].str.contains(kw, na=False, regex=True)
                filtered_out = int((~(dist_mask & title_mask)).sum())
                pdf = pdf[dist_mask & title_mask].copy()
                logger.info(f"待处理活动过滤后有效记录: {len(pdf)} 条（过滤 {filtered_out} 条）")
                hr_classifier = HeartRateClassifier(
                    DEFAULT_CONFIG['max_hr'], DEFAULT_CONFIG['resting_hr'])
                pdf = hr_classifier.classify_dataframe(pdf)
                run_classifier = RunClassifier(hr_classifier)
                pdf = run_classifier.classify_dataframe(pdf)
                processed_df = pdf

        # 10) 写出
        stats = {
            "fetched": len(all_new),
            "new": len(truly_new),
            "updated": n_updated,
            "reprocessed": len(to_process),
            "duplicate_vs_cache": n_dup_vs_cache,
            "duplicate_in_fetch": dup_in_fetch,
            "filtered_out": int((len(to_process) and processed_df is not None and
                                 len(to_process) - len(processed_df)) or 0),
            "missing_fields": missing_fields,
            "lap_rows": len(new_laps),
            "lap_failed_ids": lap_fail_ids,
            "merged_total": len(merged),
        }

        if stage:
            (stage / "activities_raw.json").write_text(
                json.dumps(truly_new, ensure_ascii=False, indent=2), encoding="utf-8")
            (stage / "activities_cache.json").write_text(
                json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            (stage / "last_fetch.json").write_text(
                json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
            if processed_df is not None:
                processed_df.to_parquet(stage / "processed.parquet", index=False)
            if new_laps:
                import pandas as pd
                pd.DataFrame(new_laps).to_parquet(stage / "lap_data.parquet", index=False)
            (stage / "fetch_stats.json").write_text(
                json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"✅ 隔离输出完成: {stage}")
        else:
            # 首次正式写入前备份
            _backup_data_files()
            (data_dir / "activities_cache.json").write_text(
                json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            Path(DEFAULT_CONFIG["state_file"]).write_text(
                json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
            if processor is not None:
                # 主表 upsert：先移除待处理活动的旧行，再并入重新清洗的结果
                import pandas as pd
                parquet_path = data_dir / "running_data.parquet"
                existing = pd.read_parquet(parquet_path) if parquet_path.exists() else pd.DataFrame()
                if not existing.empty and 'activity_id' in existing.columns:
                    existing = existing[
                        ~existing['activity_id'].astype(str).isin(to_process_ids_str)]
                if processed_df is not None and not processed_df.empty:
                    merged_df = pd.concat([existing, processed_df], ignore_index=True)
                else:
                    merged_df = existing
                if not merged_df.empty:
                    merged_df = merged_df.drop_duplicates(subset=["activity_id"], keep="last")
                    merged_df = merged_df.sort_values("date")
                    merged_df.to_parquet(parquet_path, index=False)
                    logger.info(f"✅ 主表已更新: {parquet_path} ({len(merged_df)} 行)")
                    # CSV 必须从最终合并后的主表导出（12 列固定口径）
                    processor.to_csv(merged_df, str(data_dir / "running_data_cleaned.csv"))
                else:
                    logger.warning("主表为空，跳过写出")
            elif (data_dir / "running_data.parquet").exists():
                # 无待处理活动：仍从现有主表刷新一次 CSV，保证两者口径一致（幂等）
                import pandas as pd
                from src.data_processor import DataProcessor
                current_df = pd.read_parquet(data_dir / "running_data.parquet")
                if not current_df.empty:
                    DataProcessor().to_csv(current_df, str(data_dir / "running_data_cleaned.csv"))
            if new_laps:
                import pandas as pd
                lap_path = data_dir / "lap_data.parquet"
                existing_laps = pd.read_parquet(lap_path) if lap_path.exists() else pd.DataFrame()
                new_lap_df = pd.DataFrame(new_laps)
                merged_laps = pd.concat([existing_laps, new_lap_df], ignore_index=True)
                merged_laps = merged_laps.drop_duplicates(
                    subset=["activity_id", "lap_index"], keep="last")
                merged_laps.to_parquet(lap_path, index=False)
                logger.info(f"✅ 分圈已更新: {lap_path} ({len(merged_laps)} 行)")
            logger.info(f"✅ 正式写入完成: {data_dir}")

        logger.info(
            f"📊 拉取统计: 新增 {stats['new']}，更新 {stats['updated']}，"
            f"重复(对缓存) {stats['duplicate_vs_cache']}，分圈 {stats['lap_rows']} 行，"
            f"分圈失败 {len(lap_fail_ids)}，缺失字段 {missing_fields or '无'}"
        )
        return True
    except Exception as e:
        logger.error(f"增量拉取失败: {type(e).__name__}: {e}")
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass


def _parse_dt(activity: dict) -> Optional[datetime]:
    """解析活动日期（兼容多种字段名，与 data_fetcher 同口径）"""
    for key in ("startTimeLocal", "startTime", "start_time", "startDateTimeGMT"):
        val = activity.get(key)
        if val:
            dt = _parse_datetime(val)
            if dt:
                return dt
    summary = activity.get("summaryDTO", {})
    if summary:
        for key in ("startTimeLocal", "startTimeGMT"):
            val = summary.get(key)
            if val:
                dt = _parse_datetime(val)
                if dt:
                    return dt
    return None


def _parse_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None
