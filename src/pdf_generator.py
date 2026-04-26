"""PDF 报告生成器

使用 Playwright 将 HTML 报告转换为 PDF。
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger("PowerFun.pdf_generator")


def generate_pdf(
    html_path: str,
    output_path: str,
    icloud_path: Optional[str] = None,
) -> bool:
    """将 HTML 报告转换为 PDF，并可选复制到 iCloud 目录。

    Args:
        html_path: HTML 报告文件路径
        output_path: PDF 输出路径（本地）
        icloud_path: iCloud 同步路径（可选）

    Returns:
        True 表示 PDF 生成成功，False 表示跳过或失败
    """
    # --- 前置校验 ---
    if not os.path.exists(html_path):
        logger.warning(f"[PDF] HTML 文件不存在，跳过 PDF 生成: {html_path}")
        return False

    # --- 尝试导入 playwright ---
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning(
            "[PDF] playwright 未安装，跳过 PDF 生成。"
            "运行: pip install playwright && playwright install chromium"
        )
        return False

    # --- 生成 PDF ---
    try:
        logger.info(f"[PDF] 正在生成 PDF: {output_path}")
        file_url = Path(html_path).as_uri()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(file_url, wait_until="networkidle")
            page.pdf(
                path=output_path,
                width="370mm",       # 约 1400px，匹配 HTML max-width
                height="1400mm",     # 足够高度，避免分页截断
                print_background=True,
                margin={
                    "top": "10mm",
                    "bottom": "10mm",
                    "left": "10mm",
                    "right": "10mm",
                },
            )
            browser.close()

        logger.info(f"[PDF] ✅ PDF 生成成功: {output_path}")

        # --- 复制到 iCloud ---
        if icloud_path:
            _copy_to_icloud(output_path, icloud_path)

        return True

    except Exception as e:
        logger.warning(f"[PDF] PDF 生成失败: {e}")
        return False


def _copy_to_icloud(source: str, target: str) -> None:
    """将 PDF 复制到 iCloud 目录，失败仅警告不中断。"""
    try:
        target_dir = os.path.dirname(target)
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(source, target)
        logger.info(f"[PDF] ✅ 已同步到 iCloud: {target}")
    except Exception as e:
        logger.warning(f"[PDF] iCloud 同步失败（本地 PDF 保留）: {e}")
