"""PDF 报告生成器

使用 Playwright 将 HTML 报告转换为 PDF。
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from src.config import DEFAULT_CONFIG

logger = logging.getLogger("PowerFun.pdf_generator")


def _check_playwright() -> bool:
    """检查 Playwright 是否已安装"""
    try:
        import playwright
        return True
    except ImportError:
        logger.error(
            "Playwright 未安装，无法生成 PDF。\n"
            "请运行: pip install playwright && playwright install chromium && playwright install-deps"
        )
        return False


def generate_pdf(
    html_path: str,
    output_path: str,
    icloud_dir: Optional[str] = None,  # 目录路径（函数内部会拼接文件名）
    height: str = "1400mm",    # PDF 页面高度，默认 1400mm
    width: str = "370mm",      # PDF 页面宽度，默认 370mm
    browser=None,              # 可选：传入已启动的 Playwright browser 实例以复用
) -> bool:
    """将 HTML 报告转换为 PDF，并可选复制到 iCloud 目录。

    Args:
        html_path: HTML 报告文件路径
        output_path: PDF 输出路径（本地）
        icloud_dir: iCloud 同步目录路径（可选，函数内部会拼接文件名）
        height: PDF 页面高度，默认 1400mm
        width: PDF 页面宽度，默认 370mm

    Returns:
        True 表示 PDF 生成成功，False 表示跳过或失败
    """
    # --- 前置校验 ---
    if not os.path.exists(html_path):
        logger.warning(f"[PDF] HTML 文件不存在，跳过 PDF 生成: {html_path}")
        return False

    # --- 检查 playwright 依赖 ---
    if not _check_playwright():
        return False

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("[PDF] playwright 导入异常，跳过 PDF 生成")
        return False

    # --- 生成 PDF ---
    try:
        logger.info(f"[PDF] 正在生成 PDF: {output_path}")
        file_url = Path(html_path).as_uri()

        own_browser = browser is None
        if own_browser:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1400, "height": 900})
                page.goto(file_url, wait_until="networkidle")
                page.pdf(
                    path=output_path,
                    width=width,
                    height=height,
                    print_background=True,
                    margin={
                        "top": "10mm",
                        "bottom": "10mm",
                        "left": "10mm",
                        "right": "10mm",
                    },
                )
                browser.close()
        else:
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            try:
                page.goto(file_url, wait_until="networkidle")
                page.pdf(
                    path=output_path,
                    width=width,
                    height=height,
                    print_background=True,
                    margin={
                        "top": "10mm",
                        "bottom": "10mm",
                        "left": "10mm",
                        "right": "10mm",
                    },
                )
            finally:
                page.close()

        logger.info(f"[PDF] ✅ PDF 生成成功: {output_path}")

        # --- 复制到 iCloud ---
        if icloud_dir:
            icloud_dir_expanded = os.path.expanduser(icloud_dir)
            icloud_pdf = os.path.join(icloud_dir_expanded, os.path.basename(output_path))
            _copy_to_icloud(output_path, icloud_pdf)

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
