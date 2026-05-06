#!/usr/bin/env python3
"""PowerFun - 跑步数据分析主程序

整合 Garmin Connect (China) 数据获取 + 跑步数据分析 + 可视化报告生成。

数据流（核心原则：parquet 是唯一数据源）:

    正常模式:
      API → 清洗 → 过滤 → 心率分类 → 跑分类 → 保存 parquet
                                                        ↓ 读取
                                          跑步分析报告 ─┤
                                          深度分析报告 ─┤

    --load-parquet 模式:
      读取 parquet（已处理完毕的最终数据）
          ↓ 读取
          跑步分析报告 ─┤
          深度分析报告 ─┤

    --test-data 模式:
      本地 JSON → 清洗 → 过滤 → 心率分类 → 跑分类 → 保存 parquet
                                                        ↓ 读取
                                          跑步分析报告 ─┤
                                          深度分析报告 ─┤

使用方式:
    # 首次运行 (输入账号密码)
    python main.py

    # 指定账号密码
    python main.py --email YOUR_EMAIL --password YOUR_PASSWORD

    # 指定天数
    python main.py --email YOUR_EMAIL --password YOUR_PASSWORD --days 90

    # 指定最大心率
    python main.py --email YOUR_EMAIL --password YOUR_PASSWORD --max-hr 180

    # 使用已保存的 token (无需输入密码)
    python main.py --days 30

    # 从全量数据文件加载（跳过 API 拉取和清洗）
    python main.py --load-parquet

    # 仅拉取数据，不生成报告
    python main.py --dry-run

    # 输出 JSON 数据
    python main.py --json-out data.json

    # 使用本地测试数据
    python main.py --test-data /path/to/activities.json
"""

import argparse
import getpass
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import DEFAULT_CONFIG, USER_CONFIG, HR_ZONE_PERCENTAGES, FIELD_MAPPING
from src.data_fetcher import GarminDataFetcher, AuthenticationError
from src.data_processor import DataProcessor
from src.classifier import HeartRateClassifier, RunClassifier
from src.chart_generator import ChartGenerator
from src.report_generator import ReportGenerator
from src.pdf_generator import generate_pdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("PowerFun")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="🏃 PowerFun - 跑步数据分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
    # 首次运行
    python main.py --email user@example.com --password mypass

    # 使用已保存的 token
    python main.py --days 90

    # 从全量数据文件加载（跳过 API 拉取和清洗）
    python main.py --load-parquet

    # 指定最大心率
    python main.py --max-hr 180 --resting-hr 60

    # 使用本地测试数据
    python main.py --test-data activities.json

    # 仅拉取数据，不生成报告
    python main.py --dry-run
        """,
    )
    parser.add_argument("--email", help="Garmin Connect 账号")
    parser.add_argument("--password", help="Garmin Connect 密码")
    parser.add_argument("--days", type=int, default=30, help="拉取天数 (默认 30)")
    parser.add_argument("--max-hr", type=int, default=DEFAULT_CONFIG.get('max_hr'), help=f"最大心率 (默认 {DEFAULT_CONFIG.get('max_hr')})")
    parser.add_argument("--resting-hr", type=int, default=DEFAULT_CONFIG.get('resting_hr'), help=f"静息心率 (默认 {DEFAULT_CONFIG.get('resting_hr')})")
    parser.add_argument("--output", type=str, default=None, help="报告输出目录")
    parser.add_argument("--dry-run", action="store_true", help="仅拉取数据，不生成报告")
    parser.add_argument("--json-out", type=str, default=None, help="输出 JSON 数据文件")
    parser.add_argument("--test-data", type=str, default=None, help="使用本地测试数据文件 (跳过 API 拉取)")
    parser.add_argument("--force-login", action="store_true", help="强制重新登录 (忽略已保存的 token)")
    parser.add_argument("--logout", action="store_true", help="删除已保存的 token 并退出")
    parser.add_argument("--deep-analyze", type=str, default=None,
                        help="对指定跑步做深度分析（日期 YYYY-MM-DD 或关键词）")
    parser.add_argument("--deep-analyze-all", action="store_true",
                        help="对所有跑步批量生成深析报告")
    parser.add_argument("--load-parquet", action="store_true",
                        help="从全量数据文件加载（跳过 API 拉取和清洗，直接从 parquet 读取报告数据）")

    return parser.parse_args()


def get_credentials(args) -> tuple:
    """获取账号密码 (命令行参数 或 交互式输入)"""
    email = args.email
    password = args.password

    if not email:
        email = input("Garmin 账号 (email): ").strip()

    if not password:
        password = getpass.getpass("Garmin 密码: ").strip()

    if not email or not password:
        logger.error("账号和密码不能为空")
        sys.exit(1)

    return email, password


def _load_df_from_parquet(parquet_path: Path) -> pd.DataFrame:
    """从 parquet 文件加载数据（报告的唯一数据源）"""
    df = pd.read_parquet(parquet_path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    logger.info(f"✅ 从 parquet 加载: {parquet_path} ({len(df)} 行 × {len(df.columns)} 列)")
    logger.info(f"   数据时间范围: {df['date'].min()} 至 {df['date'].max()}")
    return df


def _save_df_to_parquet(df: pd.DataFrame, parquet_path: Path) -> None:
    """保存全量数据到 parquet（唯一数据源）"""
    df.to_parquet(parquet_path, index=False)
    logger.info(f"✅ 全量数据已保存到 parquet: {parquet_path} ({len(df)} 行 × {len(df.columns)} 列)")


def _export_csv(df: pd.DataFrame, csv_path: Path) -> None:
    """导出精简 CSV（12 列，供外部查看）"""
    output_cols = [
        "date_str", "distance", "avg_hr", "max_hr", "avg_pace",
        "best_pace", "duration_min", "calories", "cadence",
        "vertical_ratio", "avg_power", "elevation_gain",
    ]
    available = [c for c in output_cols if c in df.columns]
    df[available].to_csv(csv_path, index=False, encoding="utf-8-sig")
    logger.info(f"✅ CSV 已导出: {csv_path} ({len(df)} 行)")


def _generate_deep_report(df: pd.DataFrame, target_run: pd.Series,
                          analysis_dir: Path, output_dir: Path,
                          max_hr: int = None, resting_hr: int = None,
                          fetcher=None) -> str:
    """对单次跑步生成深度分析报告（HTML + PDF + iCloud 备份）"""
    # 使用传入的值，如果未传入则使用配置中的默认值
    max_hr = max_hr or DEFAULT_CONFIG.get('max_hr')
    resting_hr = resting_hr or DEFAULT_CONFIG.get('resting_hr')
    
    from src.deep_analyzer import DeepRunAnalyzer, LLMReportGenerator
    from src.analysis_report import AnalysisReportGenerator
    from src.chart_generator import ChartGenerator

    # 加载分圈数据
    activity_id = target_run.get('activity_id')
    lap_data = {}
    recent_laps = []
    lap_pace_chart_html = ''
    lap_hr_chart_html = ''
    lap_count = 0

    if activity_id:
        fetcher_obj = fetcher or GarminDataFetcher(state_file=DEFAULT_CONFIG["state_file"])
        # 加载本次分圈数据
        current_laps = fetcher_obj._load_lap_cache(activity_id)
        
        if current_laps:
            lap_count = len(current_laps)
            # 加载前 N 次同类型的分圈数据（N=min(5, 可用次数), N≥1）
            category = target_run.get('category', '')
            N = min(5, len(df))
            if category and 'category' in df.columns:
                df_same = df[df['category'] == category]
            else:
                df_same = df
            # 排除本次
            df_same = df_same[df_same['activity_id'] != activity_id]
            # 按日期排序，取最近 N 次
            df_same = df_same.sort_values('date', ascending=False).head(N)
            
            for _, row in df_same.iterrows():
                hist_id = row.get('activity_id')
                if hist_id:
                    hist_laps = fetcher_obj._load_lap_cache(hist_id)
                    if hist_laps:
                        recent_laps.append(hist_laps)
            
            # 确保至少有一次历史数据
            if not recent_laps and len(df_same) > 0:
                # 没有历史分圈数据，只用本次数据
                recent_laps = []
            
            # 使用 DeepRunAnalyzer 的 _analyze_laps 方法
            analyzer_for_laps = DeepRunAnalyzer(df, target_date=target_run.get('date'),
                                                 max_hr=max_hr, resting_hr=resting_hr)
            lap_data = analyzer_for_laps._analyze_laps(current_laps, recent_laps)
            
            # 生成分圈配速图和心率图（需求 4：拆分为两张图）
            try:
                cat_name = target_run.get('category_name', '跑步')
                chart_gen = ChartGenerator()
                lap_pace_chart_html = chart_gen.generate_lap_pace_chart_v2(current_laps, recent_laps, cat_name)
                lap_hr_chart_html = chart_gen.generate_lap_hr_chart(current_laps, recent_laps, cat_name)
            except Exception as e:
                logger.warning(f"分圈图表生成失败: {e}")
                lap_pace_chart_html = ''
                lap_hr_chart_html = ''

    analyzer = DeepRunAnalyzer(df, target_date=target_run.get('date'),
                               max_hr=max_hr, resting_hr=resting_hr, lap_data=lap_data)
    analysis_data = analyzer.analyze(target_run)

    llm_gen = LLMReportGenerator()
    llm_report = llm_gen.generate(analysis_data)

    report_gen = AnalysisReportGenerator(str(analysis_dir))
    html_path = report_gen.generate(analysis_data, llm_report,
                                    lap_pace_chart_html=lap_pace_chart_html,
                                    lap_hr_chart_html=lap_hr_chart_html,
                                    lap_count=lap_count)

    date_str = target_run.get('date', pd.Timestamp.now()).strftime('%Y%m%d')
    local_pdf = str(analysis_dir / f"run_analysis_{date_str}.pdf")
    generate_pdf(html_path, local_pdf, icloud_dir=DEFAULT_CONFIG["icloud_deep_analysis_dir"],
                 height=DEFAULT_CONFIG["deep_pdf_height"], width=DEFAULT_CONFIG["deep_pdf_width"])

    logger.info(f"✅ 深度分析报告已生成: {html_path}")
    logger.info(f"   PDF: {local_pdf}")
    return html_path


def _get_summary_stats(df: pd.DataFrame) -> dict:
    """获取汇总统计 (兼容原始 ReportGenerator 格式)"""
    stats = {}
    stats['total_runs'] = len(df)
    stats['total_distance'] = float(df['distance'].sum()) if 'distance' in df.columns else 0
    stats['total_duration'] = float(df['duration_min'].sum()) if 'duration_min' in df.columns else 0
    stats['avg_hr'] = float(df['avg_hr'].mean()) if 'avg_hr' in df.columns and df['avg_hr'].notna().any() else 0
    stats['avg_pace'] = float(df['avg_pace_sec'].mean()) if 'avg_pace_sec' in df.columns and df['avg_pace_sec'].notna().any() else 0
    if 'date' in df.columns:
        stats['date_range'] = {
            'start': df['date'].min().strftime('%Y-%m-%d'),
            'end': df['date'].max().strftime('%Y-%m-%d'),
        }
    else:
        stats['date_range'] = {'start': '--', 'end': '--'}
    return stats


def _print_summary(stats: dict):
    """打印分析摘要"""
    print("\n" + "=" * 50)
    print("📊 跑步数据分析摘要")
    print("=" * 50)
    print(f"📅 数据时间范围：{stats.get('date_range', {}).get('start', '--')} 至 {stats.get('date_range', {}).get('end', '--')}")
    print(f"🏃 总跑步次数：{stats.get('total_runs', 0)} 次")
    print(f"📏 总跑步距离：{stats.get('total_distance', 0):.1f} km")

    total_min = stats.get('total_duration', 0)
    h = int(total_min // 60)
    m = int(total_min % 60)
    print(f"⏱️ 总时长：{h}h{m}m")

    pace = stats.get('avg_pace', 0)
    if pace:
        print(f"⚡ 平均配速：{int(pace // 60)}:{int(pace % 60):02d} /km")

    print(f"💓 平均心率：{stats.get('avg_hr', 0):.0f} bpm")
    print("=" * 50)


def _run_reports(df: pd.DataFrame, output_dir: Path, stats: dict,
                 dry_run: bool, deep_analyze: str, deep_analyze_all: bool,
                 max_hr: int = None, resting_hr: int = None) -> None:
    """从 parquet 数据生成报告（跑步分析报告 + 深度分析报告）

    这是报告的统一入口。正常模式和 --load-parquet 模式都走这条路。
    """
    # 使用传入的值，如果未传入则使用配置中的默认值
    max_hr = max_hr or DEFAULT_CONFIG.get('max_hr')
    resting_hr = resting_hr or DEFAULT_CONFIG.get('resting_hr')
    
    if args.dry_run:
        logger.info("Dry-run 模式，跳过报告生成")
        return

    # ----------------------------------------------------------
    # --deep-analyze / --deep-analyze-all 模式
    # ----------------------------------------------------------
    if deep_analyze or deep_analyze_all:
        from src.deep_analyzer import DeepRunAnalyzer, LLMReportGenerator
        from src.analysis_report import AnalysisReportGenerator

        analysis_dir = output_dir / "PowerFun_Reports"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        if deep_analyze:
            query = deep_analyze
            matched = pd.DataFrame()

            # 尝试日期格式匹配
            try:
                target_date = pd.Timestamp(query)
                matched = df[df['date'].dt.date == target_date.date()]
            except (ValueError, TypeError):
                pass

            # 如果没匹配到，尝试标题模糊匹配
            if matched.empty:
                matched = df[df['title'].str.contains(query, case=False, na=False)]

            if len(matched) == 0:
                logger.error(f"未找到匹配的跑步记录: {query}")
                sys.exit(1)
            elif len(matched) > 1:
                logger.error(f"匹配到 {len(matched)} 条记录，请更精确地指定：")
                for _, r in matched.iterrows():
                    date_str = r['date'].strftime('%Y-%m-%d') if pd.notna(r.get('date')) else 'unknown'
                    logger.error(f"  - {date_str} {r.get('title', '')}")
                sys.exit(1)

            target_run = matched.iloc[0]
            logger.info(f"🎯 深度分析: {target_run.get('title', '')} ({target_run.get('date', '')})")

            _generate_deep_report(df, target_run, analysis_dir, output_dir,
                                  max_hr=max_hr, resting_hr=resting_hr)
        else:
            # --deep-analyze-all: 遍历所有记录
            logger.info(f"📊 批量深度分析: {len(df)} 条记录...")
            existing_files = set()
            if analysis_dir.exists():
                for f in os.listdir(analysis_dir):
                    if f.startswith('run_analysis_') and f.endswith('.html'):
                        existing_files.add(f)

            count = 0
            for idx, row in df.iterrows():
                date_str = row.get('date', pd.Timestamp.now()).strftime('%Y%m%d')
                expected_html = f"run_analysis_{date_str}.html"
                if expected_html in existing_files:
                    logger.info(f"⏭️ 跳过已有报告: {expected_html}")
                    continue

                logger.info(f"📝 分析: {row.get('title', '')} ({row.get('date', '')})")
                _generate_deep_report(df, row, analysis_dir, output_dir,
                                      max_hr=max_hr, resting_hr=resting_hr)
                count += 1

            logger.info(f"✅ 批量深度分析完成: 共生成 {count} 条新报告")

        return

    # ----------------------------------------------------------
    # Step 7: 生成可视化图表
    # ----------------------------------------------------------
    logger.info("Step 7/10: 生成可视化图表...")
    chart_gen = ChartGenerator()
    charts_data = chart_gen.generate_all_charts(df)
    logger.info(f"✅ 已生成 {len(charts_data)} 个图表")

    # 确保深析报告目录存在（综合报告需要扫描此目录）
    analysis_dir = output_dir / "PowerFun_Reports"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------
    # Step 8: 生成 HTML 综合报告
    # ----------------------------------------------------------
    logger.info("Step 8/10: 生成 HTML 报告...")

    main_report_path = str(output_dir / "PowerFun.html")

    report_gen = ReportGenerator()
    report_gen.generate_html(df, charts_data, stats, main_report_path,
                             analysis_dir=str(analysis_dir))

    logger.info("=" * 60)
    logger.info(f"✅ 主报告已生成: {main_report_path}")
    logger.info("=" * 60)

    # ----------------------------------------------------------
    # Step 9: 生成 PDF 综合报告
    # ----------------------------------------------------------
    logger.info("Step 9/10: 生成 PDF 报告...")
    local_pdf = str(output_dir / '综合分析报告.pdf')
    os.makedirs(os.path.dirname(local_pdf), exist_ok=True)
    generate_pdf(
        html_path=main_report_path,
        output_path=local_pdf,
        icloud_dir=DEFAULT_CONFIG['icloud_deep_analysis_dir'],
        height=DEFAULT_CONFIG['pdf_height'],
        width=DEFAULT_CONFIG['pdf_width'],
    )

    # ----------------------------------------------------------
    # Step 10: 生成深度分析报告（最近一次跑步）
    # ----------------------------------------------------------
    logger.info("Step 10/10: 生成深度分析报告（最近一次跑步）...")
    from src.deep_analyzer import DeepRunAnalyzer, LLMReportGenerator
    from src.analysis_report import AnalysisReportGenerator

    # 加载分圈数据
    latest_run = df.iloc[-1]  # DataFrame 已按日期排序
    activity_id = latest_run.get('activity_id')
    lap_data = {}
    recent_laps = []
    lap_pace_chart_html = ''
    lap_hr_chart_html = ''
    lap_count = 0

    if activity_id:
        # 创建临时 fetcher 用于读取缓存（无需认证）
        temp_fetcher = GarminDataFetcher(state_file=DEFAULT_CONFIG["state_file"])
        current_laps = temp_fetcher._load_lap_cache(activity_id)
        
        if current_laps:
            lap_count = len(current_laps)
            # 加载前 N 次同类型的分圈数据
            category = latest_run.get('category', '')
            N = min(5, len(df))
            if category and 'category' in df.columns:
                df_same = df[df['category'] == category]
            else:
                df_same = df
            df_same = df_same[df_same['activity_id'] != activity_id]
            df_same = df_same.sort_values('date', ascending=False).head(N)
            
            for _, row in df_same.iterrows():
                hist_id = row.get('activity_id')
                if hist_id:
                    hist_laps = temp_fetcher._load_lap_cache(hist_id)
                    if hist_laps:
                        recent_laps.append(hist_laps)
            
            # 分析分圈数据
            analyzer_for_laps = DeepRunAnalyzer(df, target_date=latest_run.get('date'),
                                                 max_hr=max_hr, resting_hr=resting_hr)
            lap_data = analyzer_for_laps._analyze_laps(current_laps, recent_laps)
            
            # 生成分圈配速图和心率图（需求 4：拆分为两张图）
            try:
                cat_name = latest_run.get('category_name', '跑步')
                chart_gen = ChartGenerator()
                lap_pace_chart_html = chart_gen.generate_lap_pace_chart_v2(current_laps, recent_laps, cat_name)
                lap_hr_chart_html = chart_gen.generate_lap_hr_chart(current_laps, recent_laps, cat_name)
            except Exception as e:
                logger.warning(f"分圈图表生成失败: {e}")
                lap_pace_chart_html = ''
                lap_hr_chart_html = ''
        temp_fetcher.close()

    analyzer = DeepRunAnalyzer(df, target_date=latest_run.get('date'),
                               max_hr=max_hr, resting_hr=resting_hr, lap_data=lap_data)
    analysis_data = analyzer.analyze(latest_run)

    llm_gen = LLMReportGenerator()
    llm_report = llm_gen.generate(analysis_data)

    report_gen_deep = AnalysisReportGenerator(str(analysis_dir))
    html_path = report_gen_deep.generate(analysis_data, llm_report,
                                         lap_pace_chart_html=lap_pace_chart_html,
                                         lap_hr_chart_html=lap_hr_chart_html,
                                         lap_count=lap_count)

    date_str = latest_run.get('date', pd.Timestamp.now()).strftime('%Y%m%d')
    pdf_path = str(analysis_dir / f"深度分析报告_{date_str}.pdf")
    generate_pdf(html_path, pdf_path, icloud_dir=DEFAULT_CONFIG["icloud_deep_analysis_dir"],
                 height=DEFAULT_CONFIG["deep_pdf_height"], width=DEFAULT_CONFIG["deep_pdf_width"])

    logger.info(f"✅ 深度分析报告已生成: {html_path}")
    logger.info(f"   PDF: {pdf_path}")

    _print_summary(stats)


def main():
    """主流程"""
    global args  # _run_reports 引用
    args = parse_args()

    fetcher = None

    if args.logout:
        fetcher = GarminDataFetcher()
        fetcher.logout(delete_tokens=True)
        fetcher.close()
        logger.info("已删除认证 token")
        return

    try:
        _main_inner(args, fetcher)
    finally:
        if fetcher is not None:
            fetcher.close()


def _main_inner(args, fetcher):
    """主流程内部逻辑"""
    output_dir = Path(args.output or DEFAULT_CONFIG["report_dir"]).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = output_dir / "running_data.parquet"

    logger.info("=" * 60)
    logger.info("🏃 PowerFun 跑步数据分析")
    logger.info("=" * 60)

    # ==========================================================
    # 路径 A: --load-parquet（直接从 parquet 读取，报告数据源）
    # ==========================================================
    if args.load_parquet:
        if not parquet_path.exists():
            logger.error(f"parquet 文件不存在: {parquet_path}，请先正常运行一次程序生成数据")
            sys.exit(1)

        df = _load_df_from_parquet(parquet_path)
        stats = _get_summary_stats(df)
        _run_reports(df, output_dir, stats, args.dry_run,
                     args.deep_analyze, args.deep_analyze_all,
                     args.max_hr, args.resting_hr)
        return

    # ==========================================================
    # 路径 B: --test-data（从本地 JSON 加载）
    # ==========================================================
    if args.test_data:
        logger.info("📂 测试数据模式: 从本地文件加载数据")
        test_path = Path(args.test_data)
        if not test_path.exists():
            logger.error(f"测试数据文件不存在: {test_path}")
            sys.exit(1)
        with open(test_path, "r", encoding="utf-8") as f:
            activities = json.load(f)
        logger.info(f"加载了 {len(activities)} 条测试活动")
    else:
        # ==========================================================
        # 路径 C: 正常模式（API 拉取 → 清洗 → 过滤 → 保存 parquet）
        # ==========================================================
        logger.info("Step 1/10: 认证 Garmin Connect...")
        fetcher = GarminDataFetcher(state_file=DEFAULT_CONFIG["state_file"])

        authenticated = False
        if not args.force_login:
            if fetcher.load_tokens():
                logger.info("✅ 使用已保存的认证 token")
                authenticated = True

        if not authenticated:
            email, password = get_credentials(args)
            try:
                if fetcher.login(email, password):
                    authenticated = True
                    logger.info("✅ 登录成功，token 已保存")
                else:
                    logger.error("登录失败")
                    sys.exit(1)
            except AuthenticationError as e:
                logger.error(f"认证失败: {e}")
                sys.exit(1)

        logger.info("Step 2/10: 拉取跑步数据...")
        try:
            activities = fetcher.fetch_with_retry()
            logger.info(f"✅ 成功拉取 {len(activities)} 条活动")
        except Exception as e:
            logger.error(f"数据拉取失败: {e}")
            sys.exit(1)

        if not activities:
            logger.warning("无活动数据，退出")
            sys.exit(0)

    # ----------------------------------------------------------
    # Step 3: 数据清洗与字段映射
    # ----------------------------------------------------------
    logger.info("Step 3/10: 数据清洗与字段映射...")
    processor = DataProcessor()
    df = processor.process(activities)

    issues = processor.validate(df)
    if issues:
        logger.warning(f"数据质量问题: {issues}")

    if df.empty:
        logger.warning("数据处理后无有效记录，退出")
        sys.exit(0)

    logger.info(f"✅ 有效记录: {len(df)} 条")

    # ----------------------------------------------------------
    # Step 4: 过滤数据
    # ----------------------------------------------------------
    logger.info("Step 4/10: 过滤数据...")

    dist_mask = df['distance'] <= DEFAULT_CONFIG['max_distance_km']
    dist_excluded = int((~dist_mask).sum())

    title_mask = ~df['title'].str.contains('间歇跑', na=False)
    title_excluded = int((~title_mask).sum())

    df = df[dist_mask & title_mask].copy()
    total_excluded = int((~(dist_mask & title_mask)).sum())

    if total_excluded > 0:
        logger.info(f"已排除 {total_excluded} 条数据（{dist_excluded} 条超长距离，{title_excluded} 条间歇训练）")
        logger.info(f"✅ 过滤后有效记录: {len(df)} 条")
    else:
        logger.info("无需过滤")

    if df.empty:
        logger.warning("过滤后无有效记录，退出")
        sys.exit(0)

    # 可选: 输出 JSON
    if args.json_out:
        json_path = Path(args.json_out)
        df_out = df.copy()
        if "date" in df_out.columns:
            df_out["date"] = df_out["date"].dt.strftime("%Y-%m-%d %H:%M:%S")
        df_out.to_json(json_path, orient="records", force_ascii=False, indent=2)
        logger.info(f"JSON 数据已保存: {json_path}")

    # 可选: 输出 CSV（12 列，供外部查看）
    csv_path = output_dir / "running_data_cleaned.csv"
    _export_csv(df, csv_path)

    # ----------------------------------------------------------
    # Step 5: 心率区间分类
    # ----------------------------------------------------------
    logger.info("Step 5/10: 心率区间分类...")
    hr_classifier = HeartRateClassifier(args.max_hr, args.resting_hr)
    df = hr_classifier.classify_dataframe(df)
    logger.info(f"✅ 心率分类完成")

    # ----------------------------------------------------------
    # Step 6: 跑分类
    # ----------------------------------------------------------
    logger.info("Step 6/10: 跑分类...")
    run_classifier = RunClassifier(hr_classifier)
    df = run_classifier.classify_dataframe(df)
    logger.info(f"✅ 跑分类完成")

    # ----------------------------------------------------------
    # Step 7: 保存 parquet（最终数据源，包含所有处理后的列）
    # ----------------------------------------------------------
    _save_df_to_parquet(df, parquet_path)

    # ----------------------------------------------------------
    # Step 7.5: 拉取分圈数据（新增活动）
    # ----------------------------------------------------------
    logger.info("Step 7.5/10: 拉取分圈数据...")
    all_laps = []
    for idx, row in df.iterrows():
        act_id = row.get('activity_id')
        if not act_id:
            continue
        # 仅拉取还没有分圈数据的活动
        existing = fetcher._load_lap_cache(act_id)
        if existing:
            continue
        laps = fetcher.fetch_lap_data(act_id)
        if laps:
            all_laps.extend(laps)
    if all_laps:
        fetcher._save_lap_cache(all_laps)
        logger.info(f"✅ 分圈数据拉取完成: {len(all_laps)} 条记录")
    else:
        logger.info("✅ 无新增分圈数据")

    # ==========================================================
    # 统一报告入口：所有报告从 parquet 读取
    # ==========================================================
    df = _load_df_from_parquet(parquet_path)
    stats = _get_summary_stats(df)
    _run_reports(df, output_dir, stats, args.dry_run,
                 args.deep_analyze, args.deep_analyze_all,
                 args.max_hr, args.resting_hr)


if __name__ == "__main__":
    main()
