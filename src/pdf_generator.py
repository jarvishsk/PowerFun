"""PDF 生成模块 - 使用 Playwright 将 HTML 报告转为 iPhone 适配 PDF"""

import logging
from pathlib import Path
from typing import Optional

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

logger = logging.getLogger("PowerFun.pdf_generator")


# ============================================================
# 路径常量
# ============================================================
REPORT_DIR = Path.home() / "Documents" / "Run"
DEEP_REPORT_DIR = REPORT_DIR / "PowerFun_Reports"
ICLOUD_RUN_DIR = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "RUN"

COMPREHENSIVE_HTML = REPORT_DIR / "PowerFun.html"
COMPREHENSIVE_PDF = ICLOUD_RUN_DIR / "综合分析报告.PDF"
DEEP_PDF = ICLOUD_RUN_DIR / "深度分析报告.PDF"

VIEWPORT_WIDTH = 956  # iPhone 16 Pro Max 横屏视口宽度


def _find_latest_deep_html() -> Optional[Path]:
    """查找最新的深度分析报告 HTML"""
    if not DEEP_REPORT_DIR.exists():
        return None
    files = sorted(
        DEEP_REPORT_DIR.glob("run_analysis_*.html"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def _ensure_icloud_dir() -> None:
    """确保 iCloud 输出目录存在"""
    ICLOUD_RUN_DIR.mkdir(parents=True, exist_ok=True)


def _html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    """使用 Playwright 将单个 HTML 转为 PDF（390px 宽度，高度自适应）"""
    if not html_path.exists():
        raise FileNotFoundError(f"HTML 文件不存在: {html_path}")

    # 覆盖策略：先删除旧文件（容错 iCloud 同步竞争）
    if pdf_path.exists():
        try:
            pdf_path.unlink()
        except OSError:
            import time
            time.sleep(1)
            pdf_path.unlink(missing_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": 844})

        page.goto(f"file://{html_path.resolve()}")
        page.wait_for_load_state("networkidle")

        # 获取实际内容高度（滚动高度）
        actual_height = page.evaluate("document.body.scrollHeight")
        logger.info(f"  HTML 内容高度: {actual_height}px ({html_path.name})")

        # 加 100px 缓冲，防止 footer 被挤到第二页
        page.pdf(
            path=str(pdf_path),
            width=f"{VIEWPORT_WIDTH}px",
            height=f"{actual_height + 100}px",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        )
        browser.close()

    # 检查文件大小
    size_mb = pdf_path.stat().st_size / (1024 * 1024)
    logger.info(f"  PDF 已生成: {pdf_path} ({size_mb:.2f} MB)")
    if size_mb > 5:
        logger.warning(f"  PDF 文件超过 5MB，建议优化图表或图片")


def generate_pdf_reports() -> dict:
    """生成 PDF 报告（综合分析 + 深度分析）

    Returns:
        dict: {"comprehensive": str|None, "deep": str|None} PDF 文件路径
    """
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("Playwright 未安装，请运行: pip install playwright && playwright install chromium")

    _ensure_icloud_dir()
    results = {"comprehensive": None, "deep": None}

    # 1. 综合分析报告 PDF
    if COMPREHENSIVE_HTML.exists():
        logger.info(f"📄 生成综合分析报告 PDF...")
        _html_to_pdf(COMPREHENSIVE_HTML, COMPREHENSIVE_PDF)
        results["comprehensive"] = str(COMPREHENSIVE_PDF)
    else:
        logger.warning(f"综合分析报告 HTML 不存在: {COMPREHENSIVE_HTML}")

    # 2. 深度分析报告 PDF（取最新一份）
    latest_deep_html = _find_latest_deep_html()
    if latest_deep_html:
        logger.info(f"📄 生成深度分析报告 PDF ({latest_deep_html.name})...")
        _html_to_pdf(latest_deep_html, DEEP_PDF)
        results["deep"] = str(DEEP_PDF)
    else:
        logger.warning(f"深度分析报告 HTML 不存在: {DEEP_REPORT_DIR}")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    generate_pdf_reports()
