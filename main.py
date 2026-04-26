#!/usr/bin/env python3
"""PowerFun - 跑步数据分析主程序

整合 Garmin Connect (China) 数据获取 + 跑步数据分析 + 可视化报告生成。

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
import sys
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import DEFAULT_CONFIG
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

    # 指定最大心率
    python main.py --max-hr 180 --resting-hr 60

    # 使用本地测试数据
    python main.py --test-data activities.json
        """,
    )
    parser.add_argument("--email", help="Garmin Connect 账号")
    parser.add_argument("--password", help="Garmin Connect 密码")
    parser.add_argument("--days", type=int, default=30, help="拉取天数 (默认 30)")
    parser.add_argument("--max-hr", type=int, default=190, help="最大心率 (默认 190)")
    parser.add_argument("--resting-hr", type=int, default=60, help="静息心率 (默认 60)")
    parser.add_argument("--output", type=str, default=None, help="报告输出目录")
    parser.add_argument("--dry-run", action="store_true", help="仅拉取数据，不生成报告")
    parser.add_argument("--json-out", type=str, default=None, help="输出 JSON 数据文件")
    parser.add_argument("--test-data", type=str, default=None, help="使用本地测试数据文件 (跳过 API 拉取)")
    parser.add_argument("--force-login", action="store_true", help="强制重新登录 (忽略已保存的 token)")
    parser.add_argument("--logout", action="store_true", help="删除已保存的 token 并退出")

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


def main():
    """主流程"""
    args = parse_args()

    # 处理 logout
    if args.logout:
        fetcher = GarminDataFetcher()
        fetcher.logout(delete_tokens=True)
        logger.info("已删除认证 token")
        return

    # 配置输出目录
    output_dir = Path(args.output or DEFAULT_CONFIG["report_dir"]).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("🏃 PowerFun 跑步数据分析")
    logger.info("=" * 60)

    # ----------------------------------------------------------
    # Step 0: 处理测试数据模式
    # ----------------------------------------------------------
    if args.test_data:
        logger.info("📂 测试数据模式: 从本地文件加载数据")
        test_path = Path(args.test_data)
        if not test_path.exists():
            logger.error(f"测试数据文件不存在: {test_path}")
            sys.exit(1)

        with open(test_path, "r", encoding="utf-8") as f:
            activities = json.load(f)

        logger.info(f"加载了 {len(activities)} 条测试活动")
        # 跳过登录和数据拉取，直接进入处理
    else:
        # ----------------------------------------------------------
        # Step 1: 认证 (优先使用已保存的 token)
        # ----------------------------------------------------------
        logger.info("Step 1/7: 认证 Garmin Connect...")
        fetcher = GarminDataFetcher(
            state_file=DEFAULT_CONFIG["state_file"],
        )

        authenticated = False

        # 尝试加载已保存的 token
        if not args.force_login:
            if fetcher.load_tokens():
                logger.info("✅ 使用已保存的认证 token")
                authenticated = True

        # 如果需要登录
        if not authenticated:
            email, password = get_credentials(args)
            try:
                if fetcher.login(email, password):
                    authenticated = True
                    logger.info("✅ 登录成功，token 已保存")
                else:
                    logger.error("登录失败")
                    fetcher.close()
                    sys.exit(1)
            except AuthenticationError as e:
                logger.error(f"认证失败: {e}")
                fetcher.close()
                sys.exit(1)

        # ----------------------------------------------------------
        # Step 2: 拉取数据
        # ----------------------------------------------------------
        logger.info(f"Step 2/7: 拉取跑步数据...")
        try:
            activities = fetcher.fetch_with_retry()
            logger.info(f"✅ 成功拉取 {len(activities)} 条活动")
        except Exception as e:
            logger.error(f"数据拉取失败: {e}")
            fetcher.close()
            sys.exit(1)

        if not activities:
            logger.warning("无活动数据，退出")
            if not args.test_data:
                fetcher.close()
            sys.exit(0)

    # ----------------------------------------------------------
    # Step 3: 数据处理
    # ----------------------------------------------------------
    logger.info("Step 3/7: 数据清洗与字段映射...")
    processor = DataProcessor()
    df = processor.process(activities)

    # 数据质量校验
    issues = processor.validate(df)
    if issues:
        logger.warning(f"数据质量问题: {issues}")

    if df.empty:
        logger.warning("数据处理后无有效记录，退出")
        if not args.test_data:
            fetcher.close()
        sys.exit(0)

    logger.info(f"✅ 有效记录: {len(df)} 条")

    # ----------------------------------------------------------
    # Step 3.5: 过滤数据
    # ----------------------------------------------------------
    logger.info("Step 3.5/7: 过滤数据...")
    
    # 距离过滤（排除 > 50km）
    dist_mask = df['distance'] <= 50
    dist_excluded = int((~dist_mask).sum())
    
    # 标题过滤（排除包含"间歇跑"的活动）
    title_mask = ~df['title'].str.contains('间歇跑', na=False)
    title_excluded = int((~title_mask).sum())
    
    # 合并过滤
    df = df[dist_mask & title_mask].copy()
    total_excluded = dist_excluded + title_excluded
    
    if total_excluded > 0:
        logger.info(f"已排除 {total_excluded} 条数据（{dist_excluded} 条超长距离，{title_excluded} 条间歇训练）")
        logger.info(f"✅ 过滤后有效记录: {len(df)} 条")
    else:
        logger.info("无需过滤")
    
    if df.empty:
        logger.warning("过滤后无有效记录，退出")
        if not args.test_data:
            fetcher.close()
        sys.exit(0)

    # 可选: 输出 JSON
    if args.json_out:
        json_path = Path(args.json_out)
        df_out = df.copy()
        if "date" in df_out.columns:
            df_out["date"] = df_out["date"].dt.strftime("%Y-%m-%d %H:%M:%S")
        df_out.to_json(json_path, orient="records", force_ascii=False, indent=2)
        logger.info(f"JSON 数据已保存: {json_path}")

    # 可选: 输出 CSV (固定文件名)
    csv_path = output_dir / "running_data_cleaned.csv"
    processor.to_csv(df, str(csv_path))

    # ----------------------------------------------------------
    # Step 4: 心率区间分类
    # ----------------------------------------------------------
    logger.info("Step 4/7: 心率区间分类...")
    hr_classifier = HeartRateClassifier(args.max_hr, args.resting_hr)
    df = hr_classifier.classify_dataframe(df)
    logger.info(f"✅ 心率分类完成")

    # ----------------------------------------------------------
    # Step 5: 跑分类
    # ----------------------------------------------------------
    logger.info("Step 5/7: 跑分类...")
    run_classifier = RunClassifier(hr_classifier)
    df = run_classifier.classify_dataframe(df)
    logger.info(f"✅ 跑分类完成")

    # ----------------------------------------------------------
    # Step 6: 生成可视化图表 (使用原始 ChartGenerator)
    # ----------------------------------------------------------
    logger.info("Step 6/7: 生成可视化图表...")
    chart_gen = ChartGenerator()
    charts_data = chart_gen.generate_all_charts(df)
    logger.info(f"✅ 已生成 {len(charts_data)} 个图表")

    # ----------------------------------------------------------
    # Step 7: 生成 HTML 报告 (使用原始 ReportGenerator)
    # ----------------------------------------------------------
    if args.dry_run:
        logger.info("Dry-run 模式，跳过报告生成")
        if not args.test_data:
            fetcher.close()
        return

    logger.info("Step 7/7: 生成 HTML 报告...")

    # 获取汇总统计 (兼容原始格式)
    stats = _get_summary_stats(df)

    # 生成 HTML 报告
    report_gen = ReportGenerator()
    
    # 实现 PowerFun 报告命名策略
    main_report_path = str(output_dir / "PowerFun.html")
    backup_dir = output_dir / "PowerFun_Reports"
    
    # 创建备份目录
    backup_dir.mkdir(exist_ok=True)
    
    # 如果存在旧的主报告，备份它
    if os.path.exists(main_report_path):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = str(backup_dir / f"PowerFun_backup_{timestamp}.html")
        os.rename(main_report_path, backup_path)
        logger.info(f"已备份旧报告: {backup_path}")
    
    # 生成新报告作为主报告
    report_gen.generate_html(df, charts_data, stats, main_report_path)
    
    logger.info("=" * 60)
    logger.info(f"✅ 主报告已生成: {main_report_path}")
    logger.info("=" * 60)

    # ----------------------------------------------------------
    # Step 7.5: 生成 PDF 报告
    # ----------------------------------------------------------
    logger.info("Step 7.5/7: 生成 PDF 报告...")
    local_pdf = os.path.expanduser("/Users/jarvis/Documents/Run/PowerFun.pdf")
    icloud_pdf = os.path.expanduser(
        "~/Library/Mobile Documents/com~apple~CloudDocs/RUN/PowerFun.pdf"
    )
    # 确保本地输出目录存在
    os.makedirs(os.path.dirname(local_pdf), exist_ok=True)
    generate_pdf(
        html_path=main_report_path,
        output_path=local_pdf,
        icloud_path=icloud_pdf,
    )

    # 打印摘要
    _print_summary(stats)

    if not args.test_data:
        fetcher.close()


def _get_summary_stats(df: pd.DataFrame) -> dict:
    """获取汇总统计 (兼容原始 ReportGenerator 格式)"""
    import pandas as pd
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


if __name__ == "__main__":
    main()
