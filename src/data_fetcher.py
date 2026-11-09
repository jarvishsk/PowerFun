"""PowerFun 本地数据访问模块

Garmin 在线拉取已迁移至 src/personal_api.py（中国区 Personal API + FIT 分圈解析）。
本模块仅保留本地持久化访问能力：分圈 Parquet 缓存的读写。
"""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from src.config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class GarminDataFetcher:
    """本地数据访问器（历史类名保留，在线认证/拉取能力已移除）

    职责：分圈数据 Parquet 缓存的读取与增量合并保存。
    """

    def __init__(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
        token_dir: Optional[str] = None,
        token_file: str = "garmin_tokens",
        state_file: Optional[str] = None,
    ):
        # email/password/token_dir/token_file 仅为历史签名兼容，不再使用
        self._state_file = Path(state_file or DEFAULT_CONFIG["state_file"]).expanduser()
        self._activities_cache = self._state_file.parent / "activities_cache.json"
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------
    # 分圈数据持久化（Parquet）
    # ----------------------------------------------------------
    def _lap_parquet_path(self) -> Path:
        """返回分圈数据 Parquet 文件路径"""
        return Path(DEFAULT_CONFIG["data_dir"]).expanduser() / "lap_data.parquet"

    def _save_lap_cache(self, laps: list[dict]) -> None:
        """将分圈数据追加保存到 Parquet 文件（按 activity_id + lap_index 去重，新数据覆盖旧数据）"""
        if not laps:
            return

        path = self._lap_parquet_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        existing = pd.DataFrame()
        if path.exists():
            try:
                existing = pd.read_parquet(path)
            except Exception:
                existing = pd.DataFrame()

        new_df = pd.DataFrame(laps)
        if existing.empty:
            merged = new_df
        else:
            merged = pd.concat([existing, new_df], ignore_index=True)
            merged = merged.drop_duplicates(subset=["activity_id", "lap_index"], keep="last")

        merged.to_parquet(path, index=False)
        logger.info(f"分圈数据已保存: {len(merged)} 条记录 -> {path}")

    def _load_lap_cache(self, activity_id: int) -> list[dict]:
        """从 Parquet 加载指定活动的分圈数据，无数据时返回空列表"""
        path = self._lap_parquet_path()
        if not path.exists():
            return []
        try:
            df = pd.read_parquet(path)
            laps = df[df["activity_id"] == activity_id]
            if laps.empty:
                return []
            return laps.to_dict(orient="records")
        except Exception as e:
            logger.warning(f"加载分圈缓存失败 (activity {activity_id}): {e}")
            return []

    def load_all_lap_data(self) -> pd.DataFrame:
        """加载全部分圈数据，无数据时返回空 DataFrame"""
        path = self._lap_parquet_path()
        if not path.exists():
            return pd.DataFrame()
        try:
            return pd.read_parquet(path)
        except Exception as e:
            logger.warning(f"加载全部分圈数据失败: {e}")
            return pd.DataFrame()

    def close(self):
        """历史接口兼容（无 HTTP 连接需要释放）"""
        pass
