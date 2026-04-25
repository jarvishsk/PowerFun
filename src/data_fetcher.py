"""PowerFun 数据获取模块

基于 garth 库实现 Garmin Connect (China 区域) 认证与数据拉取。
支持自动登录、增量拉取、分页处理、429 限流恢复。
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import garth
import httpx

from src.config import GARMIN_API, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """认证失败异常"""
    pass


class SessionExpiredError(AuthenticationError):
    """会话过期异常"""
    pass


class GarminDataFetcher:
    """Garmin 数据获取器 (China 区域)

    使用 garth 库处理 SSO 认证（支持 garmin.cn），
    通过 garth.connectapi() 调用活动列表接口。
    """

    def __init__(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
        token_dir: Optional[str] = None,
        token_file: str = "garmin_tokens",
        state_file: Optional[str] = None,
    ):
        self.email = email
        self.password = password
        self._token_dir = Path(token_dir or DEFAULT_CONFIG["data_dir"]).expanduser()
        self._token_file = token_file
        self._token_path = self._token_dir / self._token_file
        self._state_file = Path(state_file or DEFAULT_CONFIG["state_file"]).expanduser()
        self._activities_cache = self._state_file.parent / "activities_cache.json"

        # 确保目录存在
        self._token_dir.mkdir(parents=True, exist_ok=True)
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

        # 配置 garth 使用 China 区域
        garth.configure(domain="garmin.cn")

        self._is_authenticated = False
        self._username: Optional[str] = None

    # ----------------------------------------------------------
    # 认证
    # ----------------------------------------------------------
    def login(self, email: Optional[str] = None, password: Optional[str] = None, save_tokens: bool = True) -> bool:
        """登录 Garmin Connect (SSO 流程)

        Args:
            email: 账号 (默认使用 __init__ 传入的)
            password: 密码 (默认使用 __init__ 传入的)
            save_tokens: 是否保存 token 到本地

        Returns:
            是否登录成功
        """
        email = email or self.email
        password = password or self.password
        if not email or not password:
            raise AuthenticationError("需要提供 email 和 password")

        try:
            logger.info("正在登录 Garmin Connect (China)...")
            garth.login(email, password)
            self._is_authenticated = True
            self._username = garth.client.username
            logger.info(f"登录成功, 用户: {self._username}")

            if save_tokens:
                self.save_tokens()

            return True

        except Exception as e:
            logger.error(f"登录失败: {e}")
            self._is_authenticated = False
            raise AuthenticationError(f"Garmin 登录失败: {e}") from e

    def load_tokens(self) -> bool:
        """从本地加载已保存的 token

        Returns:
            是否加载成功
        """
        if not self._token_path.exists():
            logger.debug(f"Token 文件不存在: {self._token_path}")
            return False

        try:
            garth.resume(str(self._token_path))
            self._is_authenticated = True
            self._username = getattr(garth.client, "username", None)
            logger.info("已加载保存的认证 token")
            return True
        except Exception as e:
            logger.warning(f"加载 token 失败: {e}")
            self._is_authenticated = False
            return False

    def save_tokens(self) -> None:
        """保存 token 到本地"""
        try:
            garth.save(str(self._token_path))
            logger.info(f"Token 已保存: {self._token_path}")
        except Exception as e:
            logger.warning(f"保存 token 失败: {e}")

    def ensure_authenticated(self) -> None:
        """确保已认证，否则抛出异常"""
        if not self._is_authenticated:
            raise AuthenticationError("未认证，请先调用 login() 或 load_tokens()")

    def logout(self, delete_tokens: bool = True) -> None:
        """登出并可选删除 token"""
        self._is_authenticated = False
        self._username = None
        if delete_tokens and self._token_path.exists():
            try:
                self._token_path.unlink()
                logger.info("已删除 token 文件")
            except Exception as e:
                logger.warning(f"删除 token 失败: {e}")

    @property
    def is_authenticated(self) -> bool:
        return self._is_authenticated

    # ----------------------------------------------------------
    # 数据拉取
    # ----------------------------------------------------------
    def fetch_activities(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        activity_type: str = "running",
        page: int = 1,
        limit: int = 100,
    ) -> list[dict]:
        """拉取活动列表 (分页)

        Args:
            start_date: 起始日期 (默认 30 天前)
            end_date: 结束日期 (默认今天)
            activity_type: 活动类型，默认 'running'
            page: 页码 (从 1 开始)
            limit: 每页数量

        Returns:
            活动列表 (garth.connectapi 原始返回)
        """
        self.ensure_authenticated()

        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=DEFAULT_CONFIG["default_date_range_days"])

        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        offset = (page - 1) * limit

        try:
            response = garth.connectapi(
                "/activitylist-service/activities/search/activities",
                params={
                    "activityType": activity_type,
                    "startDate": start_str,
                    "endDate": end_str,
                    "start": offset,
                    "limit": limit,
                },
            )
            # garth.connectapi 直接返回解析后的 JSON
            if isinstance(response, list):
                return response
            if isinstance(response, dict):
                return response.get("activityList", response.get("activities", []))
            return []

        except Exception as e:
            logger.error(f"拉取活动列表失败 (page={page}): {e}")
            raise

    def fetch_activity_detail(self, activity_id: int) -> dict:
        """拉取单个活动的详细数据

        Args:
            activity_id: 活动 ID

        Returns:
            活动详情 dict
        """
        self.ensure_authenticated()

        try:
            response = garth.connectapi(
                f"/activity-service/activity/{activity_id}",
            )
            return response if isinstance(response, dict) else {}
        except Exception as e:
            logger.error(f"拉取活动详情失败 (id={activity_id}): {e}")
            raise

    def fetch_all_new(self, max_pages: int = 200) -> list[dict]:
        """智能拉取：首次全部，后续增量

        读取状态文件判断上次拉取时间，只拉取新数据。
        自动处理分页。

        Returns:
            所有活动列表
        """
        last_fetch = self._read_state()
        start_date = None

        if last_fetch and last_fetch.get("last_date"):
            start_date = datetime.fromisoformat(last_fetch["last_date"])
            logger.info(f"增量拉取: {start_date.strftime('%Y-%m-%d')} 之后")
        else:
            # 首次拉取：从 2015-01-01 开始（覆盖所有历史数据）
            start_date = datetime(2015, 1, 1)
            logger.info("首次拉取: 获取全部历史数据 (2015-01-01 至今)")

        all_activities = []
        page = 1

        while page <= max_pages:
            try:
                activities = self.fetch_activities(
                    start_date=start_date,
                    page=page,
                    limit=DEFAULT_CONFIG["page_size"],
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = DEFAULT_CONFIG["rate_limit_wait_sec"]
                    logger.warning(f"触发限流 (429)，等待 {wait}s 后重试 ({page}/{max_pages})")
                    time.sleep(wait)
                    continue
                raise

            if not activities:
                break

            all_activities.extend(activities)
            logger.info(f"已获取第 {page} 页, 共 {len(activities)} 条, 累计 {len(all_activities)} 条")

            if len(activities) < DEFAULT_CONFIG["page_size"]:
                break  # 最后一页

            page += 1

        # 更新状态
        if all_activities:
            latest_date = self._find_latest_date(all_activities)
            if latest_date:
                self._write_state({
                    "last_date": latest_date.isoformat(),
                    "last_fetch": datetime.now().isoformat(),
                    "total_count": len(all_activities),
                })
            # 保存活动到本地缓存（增量合并）
            self._save_cache(all_activities)

        # 合并缓存数据：增量拉取 + 本地缓存
        cached = self._load_cache()
        if cached:
            def _get_id(a):
                return a.get("activity_id") or a.get("activityId")
            existing_ids = {_get_id(a) for a in all_activities if isinstance(a, dict)}
            for a in cached:
                if isinstance(a, dict) and _get_id(a) not in existing_ids:
                    all_activities.append(a)
            logger.info(f"✅ 合并缓存: {len(all_activities)} 条")

        return all_activities

    def fetch_with_retry(self, max_retries: int = None) -> list[dict]:
        """带重试和限流处理的数据拉取

        429 限流: 等待 1 小时 + 指数退避，最多 3 次重试
        其他错误: 指数退避重试

        Returns:
            活动列表
        """
        max_retries = max_retries or DEFAULT_CONFIG["max_retries"]

        for attempt in range(max_retries):
            try:
                return self.fetch_all_new()
            except httpx.HTTPStatusError as e:
                if e.response is not None and e.response.status_code == 429:
                    wait = DEFAULT_CONFIG["rate_limit_wait_sec"] * (2 ** attempt)
                    logger.warning(
                        f"触发限流 (429)，等待 {wait}s 后重试 ({attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait)
                elif attempt < max_retries - 1:
                    wait = min(2 ** attempt, 60)
                    logger.warning(f"请求失败，{wait}s 后重试 ({attempt + 1}/{max_retries})")
                    time.sleep(wait)
                else:
                    logger.error(f"拉取失败，已达最大重试次数: {e}")
                    raise
            except AuthenticationError:
                logger.error("认证失败，请重新登录")
                raise
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = min(2 ** attempt, 60)
                    logger.warning(f"未知错误，{wait}s 后重试 ({attempt + 1}/{max_retries}): {e}")
                    time.sleep(wait)
                else:
                    logger.error(f"拉取失败，已达最大重试次数: {e}")
                    raise

        return []

    # ----------------------------------------------------------
    # 状态管理
    # ----------------------------------------------------------
    def _read_state(self) -> Optional[dict]:
        """读取状态文件"""
        if not self._state_file.exists():
            return None
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取状态文件失败: {e}")
            return None

    def _write_state(self, state: dict) -> None:
        """写入状态文件"""
        with open(self._state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def _save_cache(self, activities: list[dict]) -> None:
        """保存活动到本地缓存（增量合并）"""
        # 加载已有缓存
        cached = []
        if self._activities_cache.exists():
            try:
                with open(self._activities_cache, "r", encoding="utf-8") as f:
                    cached = json.load(f)
            except (json.JSONDecodeError, IOError):
                cached = []

        # 合并去重（兼容 activityId 和 activity_id 两种字段名）
        def _get_id(a):
            return a.get("activity_id") or a.get("activityId")

        existing_ids = {_get_id(a) for a in cached if isinstance(a, dict)}
        new_count = 0
        for a in activities:
            aid = _get_id(a)
            if isinstance(a, dict) and aid not in existing_ids:
                cached.append(a)
                existing_ids.add(aid)
                new_count += 1

        # 按时间排序（最新在前）
        cached.sort(key=lambda x: _get_id(x) or 0, reverse=True)

        with open(self._activities_cache, "w", encoding="utf-8") as f:
            json.dump(cached, f, ensure_ascii=False, indent=2)

        logger.info(f"缓存已保存: {len(cached)} 条活动（新增 {new_count} 条）")

    def _load_cache(self) -> list[dict]:
        """加载本地缓存的活动数据"""
        if not self._activities_cache.exists():
            return []
        try:
            with open(self._activities_cache, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取缓存失败: {e}")
            return []

    # ----------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------
    @staticmethod
    def _find_latest_date(activities: list[dict]) -> Optional[datetime]:
        """从活动列表中找到最新的活动日期"""
        latest = None
        for a in activities:
            dt = GarminDataFetcher._parse_activity_date(a)
            if dt and (latest is None or dt > latest):
                latest = dt
        return latest

    @staticmethod
    def _parse_activity_date(activity: dict) -> Optional[datetime]:
        """解析活动日期

        支持多种字段名:
        - startTimeLocal (garth API)
        - startTime (部分接口)
        - start_time (garmer 格式)
        """
        # 尝试多种字段名
        for key in ("startTimeLocal", "startTime", "start_time", "startDateTimeGMT"):
            val = activity.get(key)
            if val:
                return GarminDataFetcher._parse_datetime(val)

        # 尝试从 summaryDTO 中获取
        summary = activity.get("summaryDTO", {})
        if summary:
            for key in ("startTimeLocal", "startTimeGMT"):
                val = summary.get(key)
                if val:
                    return GarminDataFetcher._parse_datetime(val)

        return None

    @staticmethod
    def _parse_datetime(value) -> Optional[datetime]:
        """解析日期时间"""
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
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

        return None

    def close(self):
        """关闭（兼容性方法）"""
        pass
