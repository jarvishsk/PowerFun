"""PowerFun 共享工具函数

集中处理跨模块重复的格式化等辅助逻辑。
"""

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


def load_version(version_path: Optional[Path] = None) -> str:
    """从 VERSION 文件读取版本号"""
    try:
        if version_path is None:
            version_path = Path(__file__).resolve().parent.parent / 'VERSION'
        return version_path.read_text().strip()
    except Exception:
        return '3.0'


# 报告所需的本地静态资源（位于项目 static/，生成报告时复制到 <报告目录>/assets/）
REPORT_ASSET_FILES = [
    'plotly-2.27.0.min.js',
    'jquery.min.js',
    'jquery.dataTables.min.js',
    'jquery.dataTables.min.css',
    'datatables-zh.json',
]


def ensure_report_assets(output_dir) -> Path:
    """将项目 static/ 报告资源复制到 <output_dir>/assets/，确保报告相对引用始终有效。

    复制整个 reports/ 目录后，HTML 中的相对资源链接（assets/ 或 ../assets/）依然有效。
    """
    import shutil
    src_dir = Path(__file__).resolve().parent.parent / 'static'
    dest_dir = Path(output_dir) / 'assets'
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in REPORT_ASSET_FILES:
        src = src_dir / name
        if src.exists():
            shutil.copy2(src, dest_dir / name)
    return dest_dir
