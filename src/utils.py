"""PowerFun 共享工具函数

集中处理跨模块重复的格式化、文件复制等辅助逻辑。
"""

import shutil
from pathlib import Path
from typing import Optional


def format_pace_mmss(seconds) -> str:
    """将秒数转为 mm:ss /km 格式（图表 hover 用）"""
    if seconds is None or seconds <= 0:
        return "--:--"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


def format_pace_chinese(seconds) -> str:
    """将配速秒数转为 X分X秒/KM 格式（文本报告用）"""
    if seconds is None or seconds <= 0:
        return "--"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}分{secs:02d}秒/KM"


def format_duration_hhmmss(total_min: float) -> str:
    """将分钟数转为 hh:mm:ss"""
    if total_min is None or total_min < 0:
        return "--:--:--"
    total_seconds = int(round(float(total_min) * 60))
    hours = total_seconds // 3600
    mins = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{mins:02d}:{secs:02d}"


def format_duration_hm(total_min: float) -> str:
    """将分钟数转为 XhXm"""
    if total_min is None or total_min < 0:
        return "--h--m"
    h = int(total_min // 60)
    m = int(total_min % 60)
    return f"{h}h{m}m"


def copy_to_icloud(src_path: Path, icloud_dir: Path, filename: str) -> Path:
    """复制报告到 iCloud，先删除旧文件，再返回目标路径"""
    icloud_dir.mkdir(parents=True, exist_ok=True)
    dest = icloud_dir / filename
    dest.unlink(missing_ok=True)
    shutil.copy2(src_path, dest)
    return dest


def load_version(version_path: Optional[Path] = None) -> str:
    """从 VERSION 文件读取版本号"""
    try:
        if version_path is None:
            version_path = Path(__file__).resolve().parent.parent / 'VERSION'
        return version_path.read_text().strip()
    except Exception:
        return '3.0'
