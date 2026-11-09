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
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import DEFAULT_CONFIG, USER_CONFIG, HR_ZONE_PERCENTAGES, FIELD_MAPPING
from src.utils import (
    format_duration_hm,
    format_duration_hhmmss,
    format_pace_chinese,
    format_pace_mmss,
    ensure_report_assets,
)
from src.data_fetcher import GarminDataFetcher
from src.data_processor import DataProcessor
from src.classifier import HeartRateClassifier, RunClassifier
from src.chart_generator import ChartGenerator
from src.report_generator import ReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("PowerFun")

# LLM prompt 缓存版本号：prompt 结构变更时 +1，旧版本缓存视为无效
LLM_PROMPT_VERSION = 12


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
    parser.add_argument("--max-hr", type=int, default=DEFAULT_CONFIG.get('max_hr'), help=f"最大心率 (默认 {DEFAULT_CONFIG.get('max_hr')})")
    parser.add_argument("--resting-hr", type=int, default=DEFAULT_CONFIG.get('resting_hr'), help=f"静息心率 (默认 {DEFAULT_CONFIG.get('resting_hr')})")
    parser.add_argument("--output", type=str, default=None, help="报告输出目录")
    parser.add_argument("--dry-run", action="store_true", help="仅拉取数据，不生成报告")
    parser.add_argument("--json-out", type=str, default=None, help="输出 JSON 数据文件")
    parser.add_argument("--test-data", type=str, default=None, help="使用本地测试数据文件 (跳过 API 拉取)")
    parser.add_argument("--deep-analyze", type=str, default=None,
                        help="对指定跑步做深度分析（日期 YYYY-MM-DD、latest 或关键词）")
    parser.add_argument("--force", action="store_true",
                        help="强制重新调用 LLM 并覆盖缓存（仅 --deep-analyze 有效）")
    parser.add_argument("--deep-analyze-all", action="store_true",
                        help="对所有跑步批量生成深析报告")
    parser.add_argument("--load-parquet", action="store_true",
                        help="从全量数据文件加载（跳过 API 拉取和清洗，直接从 parquet 读取报告数据）")
    parser.add_argument("--prepare-llm", action="store_true",
                        help="第一阶段：计算分析数据并准备 KimiWork 模型请求（写 .runtime/llm/<id>/request.md）")
    parser.add_argument("--llm-response", type=str, default=None,
                        help="第二阶段：使用 KimiWork 已生成的 response.md 渲染深析报告")
    parser.add_argument("--garmin-check", action="store_true",
                        help="仅验证 Garmin Personal API 认证、资料和单次活动读取，不改正式数据")
    parser.add_argument("--fetch-new", action="store_true",
                        help="增量拉取 Garmin 新增数据（默认写正式 data/，配合 --stage 写隔离目录）")
    parser.add_argument("--stage", type=str, default=None,
                        help="隔离输出目录（仅 --fetch-new 有效）：原始响应、处理结果和分圈全部写入该目录，不覆盖正式 data/")
    parser.add_argument("--user-note", type=str, default=None,
                        help="跑者体感备注（仅 --deep-analyze 模式有效，将与客观数据一起提交给 AI 综合分析）")

    return parser.parse_args()


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


def _load_similar_lap_history(df: pd.DataFrame, category, target_ts, activity_id, N: int,
                               fetcher, temp_bucket=None) -> tuple:
    """加载历史分圈基线（PRD F3）：近90天同温区 → 近90天跨温区 → 最近N次同类型（兜底）

    Returns:
        (recent_laps, baseline_note)：recent_laps 为历史分圈数据列表，
        baseline_note 为基线构成标注（如「同温区 8 次」「跨温区 9 次」「跨全年 12 次」）
    """
    from src.deep_analyzer import DeepRunAnalyzer, NO_TEMP_FILTER_CATEGORIES

    if category and 'category' in df.columns:
        df_same = df[df['category'] == category]
    else:
        df_same = df
    # 排除本次
    df_same = df_same[df_same['activity_id'] != activity_id]
    # 排除目标日期之后的所有数据，同时允许同日期更早的记录作为历史基线
    df_same = df_same[df_same['date'] <= target_ts]

    # 基线选择（PRD F3）：近90天同温区(≥5次) → 近90天跨温区(≥5次) → 最近N次同类型(兜底)
    # LSD 豁免温度过滤（PRD F1）：跳过同温区优先档直接不限温区档，标注「全部 LSD N 次」
    no_temp = category in NO_TEMP_FILTER_CATEGORIES
    cutoff_90 = target_ts - pd.Timedelta(days=90)
    df_90 = df_same[df_same['date'] >= cutoff_90]

    def _with_temp_bucket(d: pd.DataFrame) -> pd.DataFrame:
        """计算温区桶并剔除无温区记录（与 deep_analyzer._get_temp_bucket 同口径）"""
        d = d.copy()
        d['_temp_bucket'] = d.apply(lambda r: DeepRunAnalyzer._get_temp_bucket(r), axis=1)
        return d[d['_temp_bucket'].notna()]

    df_sel = None
    baseline_note = ''
    if 'min_temperature' in df_same.columns and 'max_temperature' in df_same.columns:
        if temp_bucket is not None and not no_temp:
            d = _with_temp_bucket(df_90)
            d = d[d['_temp_bucket'] == temp_bucket]
            if len(d) >= 5:
                df_sel = d
                baseline_note = f'同温区 {len(d)} 次'
        if df_sel is None:
            d = _with_temp_bucket(df_90)
            if len(d) >= 5:
                df_sel = d
                baseline_note = f'跨温区 {len(d)} 次'
    if df_sel is None:
        # 兜底：最近 N 次同类型（跨全年）
        df_sel = df_same.sort_values('date', ascending=False).head(N)
        baseline_note = f'跨全年 {len(df_sel)} 次'
    if no_temp and len(df_sel) > 0:
        # LSD 统一标注全部同池（PRD F1：baseline_note 不再出现同温区/跨温区/跨全年字样）
        baseline_note = f'全部 LSD {len(df_sel)} 次'

    # 按日期排序，取最近 N 次
    df_sel = df_sel.sort_values('date', ascending=False).head(N)

    recent_laps = []
    for _, row in df_sel.iterrows():
        hist_id = row.get('activity_id')
        if hist_id:
            hist_laps = fetcher._load_lap_cache(hist_id)
            if hist_laps:
                recent_laps.append(hist_laps)
    return recent_laps, baseline_note


def _build_pa_hr_history_chart(df: pd.DataFrame, activity_id, target_ts,
                               max_hr: int, resting_hr: int, fetcher) -> str:
    """构建 Pa:Hr 有氧解耦历史趋势图（>=3km 且非目标跑步）"""
    from src.deep_analyzer import DeepRunAnalyzer
    from src.chart_generator import ChartGenerator

    pa_hr_history_data = df[
        (df['distance'] >= 3.0) &
        (df['activity_id'] != activity_id) &
        (df['date'] <= target_ts)
    ].copy()

    if len(pa_hr_history_data) < 3:
        return None

    pa_hr_history_list = []
    for _, row in pa_hr_history_data.iterrows():
        hist_activity_id = row.get('activity_id')
        if hist_activity_id:
            hist_laps = fetcher._load_lap_cache(hist_activity_id)
            if hist_laps:
                hist_analyzer = DeepRunAnalyzer(df, max_hr=max_hr, resting_hr=resting_hr)
                hist_pa_hr = hist_analyzer._calc_pa_hr(hist_laps)
                if hist_pa_hr:
                    pa_hr_history_list.append({
                        'date': row['date'].strftime('%Y-%m-%d'),
                        'category': row.get('category', 'unknown'),
                        'category_color': row.get('category_color', '#999999'),
                        'category_icon': row.get('category_icon', '🏃'),
                        'distance': row.get('distance', 0),
                        'mid_temp': (row.get('min_temperature', 0) + row.get('max_temperature', 0)) / 2
                        if pd.notna(row.get('min_temperature')) and pd.notna(row.get('max_temperature'))
                        else 0,
                        'pa_hr_pct': hist_pa_hr.get('pa_hr_pct', 0),
                        'pa_hr_abs': hist_pa_hr.get('pa_hr_abs', 0)
                    })

    if not pa_hr_history_list:
        return None

    chart_gen = ChartGenerator()
    return chart_gen.create_pa_hr_trend_chart(pa_hr_history_list)


def _llm_cache_path(activity_id):
    """深析 LLM 输出缓存路径（项目级 cache/llm/）；无有效 activity_id 时返回 None（不缓存）"""
    if activity_id and str(activity_id) not in ('', 'unknown', 'None'):
        return Path(DEFAULT_CONFIG['cache_dir']) / "llm" / f"llm_{activity_id}.md"
    return None


def _user_note_hash(user_note: str) -> str:
    """user_note 的 sha256（未传备注时为空串）"""
    import hashlib
    return hashlib.sha256(user_note.encode('utf-8')).hexdigest() if user_note else ''


# 教练点评六个必需小节（完整且顺序固定）
REQUIRED_LLM_SECTIONS = [
    '## 🔥 本次跑步小结',
    '## 🏃 强度与负荷分析',
    '## ⚙️ 技术效率分析',
    '## 📈 能力变化趋势',
    '## 🔄 分圈表现分析',
    '## 🛠️ 问题与修正',
]


def _validate_llm_response(content: str) -> list:
    """校验 KimiWork 生成的 response：六小节完整且顺序正确、含 BRIEF 块。

    Returns:
        问题列表；空列表表示通过
    """
    problems = []
    pos = 0
    for sec in REQUIRED_LLM_SECTIONS:
        idx = content.find(sec, pos)
        if idx == -1:
            problems.append(f"缺少或顺序错误的小节: {sec}")
            break
        pos = idx + len(sec)
    if '<<<BRIEF>>>' not in content or '<<<END>>>' not in content:
        problems.append("缺少 <<<BRIEF>>>...<<<END>>> 简报块")
    return problems


def _write_llm_request(activity_id, prompt: str, user_note: str) -> Path:
    """第一阶段：将模型请求写入 .runtime/llm/<activity_id>/，并记录请求上下文"""
    req_dir = Path(DEFAULT_CONFIG['llm_runtime_dir']) / str(activity_id)
    req_dir.mkdir(parents=True, exist_ok=True)
    request_path = req_dir / "request.md"
    request_path.write_text(prompt, encoding='utf-8')
    (req_dir / "context.json").write_text(
        json.dumps({
            'activity_id': str(activity_id),
            'user_note_hash': _user_note_hash(user_note),
            'prompt_version': LLM_PROMPT_VERSION,
        }, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return request_path


def _read_llm_cache(cache_path, user_note: str):
    """读取 LLM 缓存。命中返回 (content, model)，未命中返回 None

    命中条件：缓存存在、prompt_version 与当前版本一致，
    且（本次未传 --user-note 或 hash 与缓存一致）
    """
    if cache_path is None or not cache_path.exists():
        return None
    try:
        lines = cache_path.read_text(encoding='utf-8').split('\n')
        # 新格式 frontmatter：user_note_hash / model / prompt_version + 空行 + 正文
        if len(lines) < 5:
            return None
        if not lines[0].startswith('user_note_hash: ') or not lines[1].startswith('model: '):
            return None
        if not lines[2].startswith('prompt_version: '):
            return None
        if lines[2].split(': ', 1)[1].strip() != str(LLM_PROMPT_VERSION):
            return None
        if user_note and lines[0].split(': ', 1)[1] != _user_note_hash(user_note):
            return None
        model = lines[1].split(': ', 1)[1]
        content = '\n'.join(lines[4:])
        return content, model
    except Exception as e:
        logger.warning(f"LLM 缓存读取失败，忽略缓存: {e}")
        return None


def _write_llm_cache(cache_path, user_note: str, model: str, content: str) -> None:
    """写入 LLM 缓存（frontmatter 三行 + 正文）"""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            f"user_note_hash: {_user_note_hash(user_note)}\n"
            f"model: {model}\n"
            f"prompt_version: {LLM_PROMPT_VERSION}\n"
            f"\n"
            f"{content}",
            encoding='utf-8',
        )
    except Exception as e:
        logger.warning(f"LLM 缓存写入失败: {e}")


def _resolve_llm_report(df: pd.DataFrame, analysis_data: dict, activity_id,
                        user_note: str = None, force: bool = False,
                        response_path: str = None, on_miss: str = 'exit') -> tuple:
    """KimiWork 两阶段模型编排，返回 (llm_report, actual_model)。

    流程：
    - 缓存命中（且非 --force、未指定 --llm-response）：打印 LLM_CACHE_HIT，直接渲染。
    - 指定 --llm-response（第二阶段）：校验 activity_id/请求上下文、六小节顺序与 BRIEF 块，
      通过后写缓存（model=KimiWork）并渲染；校验失败退出，不写缓存、不生成报告。
    - 缓存未命中（第一阶段）：构建原 Prompt 写入 .runtime/llm/<id>/request.md，
      打印 LLM_REQUEST_REQUIRED=<path> 后退出（on_miss='exit'）或返回 None（on_miss='skip'）。

    任何情况下都不调用外部模型、不用空点评生成正式报告。
    """
    from src.deep_analyzer import LLMReportGenerator

    cache_path = _llm_cache_path(activity_id)

    if response_path is not None:
        # ---------------- 第二阶段：渲染 KimiWork 已生成的回复 ----------------
        resp_file = Path(response_path).expanduser()
        if not resp_file.exists():
            logger.error(f"response 文件不存在: {resp_file}")
            sys.exit(1)
        content = resp_file.read_text(encoding='utf-8')
        # 请求上下文一致性校验（防止响应错配）
        context_file = resp_file.parent / "context.json"
        if context_file.exists():
            try:
                ctx = json.loads(context_file.read_text(encoding='utf-8'))
            except json.JSONDecodeError as e:
                logger.error(f"请求上下文解析失败: {e}")
                sys.exit(1)
            cur_ctx = {
                'activity_id': activity_id,
                'user_note_hash': _user_note_hash(user_note),
                'prompt_version': LLM_PROMPT_VERSION,
            }
            for key, cur_val in cur_ctx.items():
                if str(ctx.get(key)) != str(cur_val):
                    logger.error(
                        f"response 上下文不一致: {key} 期望 {cur_val!r}，实际 {ctx.get(key)!r}。"
                        "请确认 response.md 对应当前活动、体感和 Prompt 版本。"
                    )
                    sys.exit(1)
        problems = _validate_llm_response(content)
        if problems:
            for p in problems:
                logger.error(f"response 校验失败: {p}")
            logger.error("请修正 response.md 后重试；未写缓存、未生成正式报告。")
            sys.exit(1)
        _write_llm_cache(cache_path, user_note, 'KimiWork', content)
        llm_report, brief = LLMReportGenerator._parse_brief(content)
        analysis_data['brief_summary'] = brief
        logger.info("✅ response 校验通过，已写入 LLM 缓存（model=KimiWork）")
        return llm_report, 'KimiWork'

    if not force and cache_path is not None:
        cached = _read_llm_cache(cache_path, user_note)
        if cached is not None:
            content, model = cached
            print("LLM_CACHE_HIT")
            llm_report, brief = LLMReportGenerator._parse_brief(content)
            analysis_data['brief_summary'] = brief
            return llm_report, model

    # ---------------- 第一阶段：准备模型请求 ----------------
    llm_gen = LLMReportGenerator(df_all=df)
    prompt = llm_gen._build_prompt(analysis_data, user_note=user_note)
    request_path = _write_llm_request(activity_id, prompt, user_note)
    print(f"LLM_REQUEST_REQUIRED={request_path}")
    if on_miss == 'skip':
        logger.warning("批量模式：已跳过本次深析报告渲染，等待 response 后单独渲染")
        return None, None
    logger.info("等待 KimiWork 会话生成 response.md 后，使用 --llm-response 重新运行第二阶段")
    sys.exit(0)


def _generate_deep_report(df: pd.DataFrame, target_run: pd.Series,
                          analysis_dir: Path, output_dir: Path,
                          max_hr: int, resting_hr: int,
                          fetcher=None, user_note: str = None,
                          force: bool = False, response_path: str = None,
                          on_miss: str = 'exit') -> str:
    """对单次跑步生成深度分析报告"""

    from src.deep_analyzer import DeepRunAnalyzer, LLMReportGenerator
    from src.analysis_report import AnalysisReportGenerator
    from src.chart_generator import ChartGenerator

    # 加载分圈数据
    activity_id = target_run.get('activity_id')
    target_ts = pd.Timestamp(target_run.get('date'))  # 目标日期，用于排除未来数据污染
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
            # 加载前 N 次同类型的分圈数据（P20-P80 百分位统计需要足够样本）
            # 图表层会按分类总样本和每公里样本阈值过滤，N 取足够大以保证 per-km 样本量
            category = target_run.get('category', '')
            N = DEFAULT_CONFIG.get('deep_lap_history_n', 100)
            temp_bucket = DeepRunAnalyzer._get_temp_bucket(target_run)
            recent_laps, lap_baseline_note = _load_similar_lap_history(
                df, category, target_ts, activity_id, N, fetcher_obj,
                temp_bucket=temp_bucket,
            )

            # 使用 DeepRunAnalyzer 的 _analyze_laps 方法
            analyzer_for_laps = DeepRunAnalyzer(df, target_date=target_run.get('date'),
                                                 max_hr=max_hr, resting_hr=resting_hr)
            lap_data = analyzer_for_laps._analyze_laps(current_laps, recent_laps)
            lap_data['baseline_note'] = lap_baseline_note

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
                               max_hr=max_hr, resting_hr=resting_hr, lap_data=lap_data,
                               raw_laps=current_laps)
    analysis_data = analyzer.analyze(target_run)

    # 计算Pa:Hr历史趋势（如果当前跑步>=3km且有lap数据）
    pa_hr_current = analysis_data.get('pa_hr')
    pa_hr_history_chart = _build_pa_hr_history_chart(
        df, activity_id, target_ts, max_hr, resting_hr,
        fetcher_obj if activity_id and fetcher else fetcher
    )

    llm_report, actual_model = _resolve_llm_report(
        df, analysis_data, activity_id,
        user_note=user_note, force=force,
        response_path=response_path, on_miss=on_miss)
    if llm_report is None:
        return None  # 批量模式等待 response，不渲染正式报告

    report_gen = AnalysisReportGenerator(str(analysis_dir))
    html_path = report_gen.generate(analysis_data, llm_report,
                                    lap_pace_chart_html=lap_pace_chart_html,
                                    lap_hr_chart_html=lap_hr_chart_html,
                                    lap_count=lap_count,
                                    pa_hr=pa_hr_current,
                                    pa_hr_history=pa_hr_history_chart,
                                    model_name=actual_model)

    logger.info(f"✅ 深度分析报告已生成: {html_path}")
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
    print(f"⏱️ 总时长：{format_duration_hm(total_min)}")

    pace = stats.get('avg_pace', 0)
    if pace:
        print(f"⚡ 平均配速：{int(pace // 60)}:{int(pace % 60):02d} /km")

    print(f"💓 平均心率：{stats.get('avg_hr', 0):.0f} bpm")
    print("=" * 50)


def _run_reports(df: pd.DataFrame, output_dir: Path, stats: dict,
                 dry_run: bool, deep_analyze: str, deep_analyze_all: bool,
                 max_hr: int, resting_hr: int, user_note: str = None,
                 fetcher=None, force: bool = False,
                 response_path: str = None) -> None:
    """从 parquet 数据生成报告（跑步分析报告 + 深度分析报告）

    这是报告的统一入口。正常模式和 --load-parquet 模式都走这条路。
    max_hr 和 resting_hr 由 argparse 默认从 DEFAULT_CONFIG 读取。
    """
    from src.config import LLM_CONFIG
    model_name = LLM_CONFIG.get('display_name', 'AI模型')
    
    if dry_run:
        logger.info("Dry-run 模式，跳过报告生成")
        return

    # 确保报告本地静态资源（Plotly/jQuery/DataTables）就位
    ensure_report_assets(output_dir)

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

            if query.strip().lower() == 'latest':
                # 字面量 latest：取 parquet 中最新一次跑步
                matched = df[df['date'].dt.date == df['date'].max().date()]
            else:
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

            # 在深度分析分支创建可复用 fetcher（如主流程未提供）
            deep_fetcher = fetcher or GarminDataFetcher(state_file=DEFAULT_CONFIG["state_file"])
            _generate_deep_report(df, target_run, analysis_dir, output_dir,
                                  max_hr=max_hr, resting_hr=resting_hr,
                                  fetcher=deep_fetcher,
                                  user_note=user_note, force=force,
                                  response_path=response_path)
            if not fetcher:
                deep_fetcher.close()
        else:
            # --deep-analyze-all: 遍历所有记录
            logger.info(f"📊 批量深度分析: {len(df)} 条记录...")
            existing_files = set()
            if analysis_dir.exists():
                for f in os.listdir(analysis_dir):
                    if f.startswith('run_analysis_') and f.endswith('.html'):
                        existing_files.add(f)

            # 创建可复用的 fetcher，供分圈缓存读取使用
            shared_fetcher = fetcher or GarminDataFetcher(state_file=DEFAULT_CONFIG["state_file"])

            count = 0
            for idx, row in df.iterrows():
                date_str = row.get('date', pd.Timestamp.now()).strftime('%Y%m%d')
                activity_id = row.get('activity_id')
                if activity_id and str(activity_id) not in ('', 'unknown', 'None'):
                    expected_html = f"run_analysis_{date_str}_{activity_id}.html"
                else:
                    expected_html = f"run_analysis_{date_str}.html"
                if expected_html in existing_files:
                    logger.info(f"⏭️ 跳过已有报告: {expected_html}")
                    continue

                logger.info(f"📝 分析: {row.get('title', '')} ({row.get('date', '')})")
                _generate_deep_report(df, row, analysis_dir, output_dir,
                                      max_hr=max_hr, resting_hr=resting_hr,
                                      fetcher=shared_fetcher,
                                      on_miss='skip')
                count += 1

            # 批量深析完成后关闭复用的 fetcher
            if not fetcher:
                shared_fetcher.close()

            logger.info(f"✅ 批量深度分析完成: 共生成 {count} 条新报告")

    # ----------------------------------------------------------
    # Step 7: 生成深度分析报告（正常模式：最近一次跑步）
    # ----------------------------------------------------------
    if not deep_analyze and not deep_analyze_all:
        logger.info("Step 7/10: 生成深度分析报告（最近一次跑步）...")
        from src.deep_analyzer import DeepRunAnalyzer, LLMReportGenerator
        from src.analysis_report import AnalysisReportGenerator

        analysis_dir = output_dir / "PowerFun_Reports"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        latest_run = df.iloc[-1]  # DataFrame 已按日期排序
        activity_id = latest_run.get('activity_id')
        target_ts = pd.Timestamp(latest_run.get('date'))  # 用于过滤未来数据（正常模式即为最新日期）
        lap_data = {}
        recent_laps = []
        lap_pace_chart_html = ''
        lap_hr_chart_html = ''
        lap_count = 0
        current_laps = None

        if activity_id:
            temp_fetcher = GarminDataFetcher(state_file=DEFAULT_CONFIG["state_file"])
            current_laps = temp_fetcher._load_lap_cache(activity_id)

            if current_laps:
                lap_count = len(current_laps)
                category = latest_run.get('category', '')
                N = DEFAULT_CONFIG.get('deep_lap_history_n', 100)
                temp_bucket = DeepRunAnalyzer._get_temp_bucket(latest_run)
                recent_laps, lap_baseline_note = _load_similar_lap_history(
                    df, category, target_ts, activity_id, N, temp_fetcher,
                    temp_bucket=temp_bucket,
                )

                analyzer_for_laps = DeepRunAnalyzer(df, target_date=latest_run.get('date'),
                                                     max_hr=max_hr, resting_hr=resting_hr)
                lap_data = analyzer_for_laps._analyze_laps(current_laps, recent_laps)
                lap_data['baseline_note'] = lap_baseline_note

                try:
                    cat_name = latest_run.get('category_name', '跑步')
                    chart_gen_lap = ChartGenerator()
                    lap_pace_chart_html = chart_gen_lap.generate_lap_pace_chart_v2(current_laps, recent_laps, cat_name)
                    lap_hr_chart_html = chart_gen_lap.generate_lap_hr_chart(current_laps, recent_laps, cat_name)
                except Exception as e:
                    logger.warning(f"分圈图表生成失败: {e}")
                    lap_pace_chart_html = ''
                    lap_hr_chart_html = ''

        analyzer = DeepRunAnalyzer(df, target_date=latest_run.get('date'),
                                   max_hr=max_hr, resting_hr=resting_hr, lap_data=lap_data,
                                   raw_laps=current_laps)
        analysis_data = analyzer.analyze(latest_run)

        pa_hr_current = analysis_data.get('pa_hr')
        pa_hr_history_chart = _build_pa_hr_history_chart(
            df, latest_run.get('activity_id'), target_ts, max_hr, resting_hr, temp_fetcher
            if activity_id else None
        )

        # 在 Pa:Hr 历史计算完成后关闭 fetcher（避免在关闭后访问 lap 缓存）
        if activity_id:
            temp_fetcher.close()

        llm_report, actual_model = _resolve_llm_report(
            df, analysis_data, activity_id,
            user_note=user_note, response_path=response_path)

        report_gen_deep = AnalysisReportGenerator(str(analysis_dir))
        html_path = report_gen_deep.generate(analysis_data, llm_report,
                                             lap_pace_chart_html=lap_pace_chart_html,
                                             lap_hr_chart_html=lap_hr_chart_html,
                                             lap_count=lap_count,
                                             pa_hr=pa_hr_current,
                                             pa_hr_history=pa_hr_history_chart,
                                             model_name=actual_model)

        logger.info(f"✅ 深度分析报告已生成: {html_path}")

    # ----------------------------------------------------------
    # Step 8: 生成可视化图表
    # ----------------------------------------------------------
    logger.info("Step 8/10: 生成可视化图表...")
    chart_gen = ChartGenerator()
    charts_data = chart_gen.generate_all_charts(df)
    logger.info(f"✅ 已生成 {len(charts_data)} 个图表")

    # 确保深析报告目录存在（综合报告需要扫描此目录）
    analysis_dir = output_dir / "PowerFun_Reports"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------
    # Step 9: 生成 HTML 综合报告（深析报告已在上一步生成，链接可见）
    # ----------------------------------------------------------
    logger.info("Step 9/10: 生成 HTML 报告...")

    main_report_path = str(output_dir / "PowerFun.html")

    report_gen = ReportGenerator()
    report_gen.generate_html(df, charts_data, stats, main_report_path,
                             analysis_dir=str(analysis_dir),
                             model_name=model_name)

    logger.info("=" * 60)
    logger.info(f"✅ 主报告已生成: {main_report_path}")
    logger.info("=" * 60)

    _print_summary(stats)


def main():
    """主流程"""
    args = parse_args()

    if args.garmin_check:
        from src.personal_api import garmin_check
        ok = garmin_check()
        sys.exit(0 if ok else 1)

    _main_inner(args)


def _main_inner(args):
    """主流程内部逻辑"""
    data_dir = Path(DEFAULT_CONFIG["data_dir"]).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path(args.output or DEFAULT_CONFIG["report_dir"]).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = data_dir / "running_data.parquet"

    logger.info("=" * 60)
    logger.info("🏃 PowerFun 跑步数据分析")
    logger.info("=" * 60)

    fetcher = None

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
                     args.max_hr, args.resting_hr, user_note=args.user_note,
                     fetcher=fetcher, force=args.force,
                     response_path=args.llm_response)
        return

    # ==========================================================
    # 路径 A2: --fetch-new（Garmin 增量拉取；--stage 写隔离目录）
    # ==========================================================
    if args.fetch_new:
        from src.personal_api import fetch_new
        ok = fetch_new(stage_dir=args.stage)
        sys.exit(0 if ok else 1)

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
        # garth SSO 抓取已移除（Personal API 验收通过）。
        # 在线更新请使用 --fetch-new（中国区 Personal API）；
        # 本地报告请使用 --load-parquet；调试请使用 --test-data。
        logger.error("未指定数据来源。在线增量: --fetch-new；本地报告: --load-parquet；测试: --test-data")
        sys.exit(1)

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

    excluded_keywords = DEFAULT_CONFIG.get('excluded_title_keywords', ['间歇跑'])
    title_pattern = '|'.join(excluded_keywords)
    title_mask = ~df['title'].str.contains(title_pattern, na=False, regex=True)
    title_excluded = int((~title_mask).sum())

    df = df[dist_mask & title_mask].copy()
    total_excluded = int((~(dist_mask & title_mask)).sum())

    if total_excluded > 0:
        logger.info(f"已排除 {total_excluded} 条数据（其中超长距离 {dist_excluded} 条、间歇训练 {title_excluded} 条）")
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
    csv_path = data_dir / "running_data_cleaned.csv"
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
    # Step 7.5: 分圈数据
    # 在线分圈拉取已迁移至 --fetch-new（Personal API + FIT 解析），此处不再拉取
    # ----------------------------------------------------------
    logger.info("Step 7.5/10: 分圈数据由 --fetch-new 维护，本流程跳过")

    # ==========================================================
    # 统一报告入口：所有报告从 parquet 读取
    # ==========================================================
    df = _load_df_from_parquet(parquet_path)
    stats = _get_summary_stats(df)
    _run_reports(df, output_dir, stats, args.dry_run,
                 args.deep_analyze, args.deep_analyze_all,
                 args.max_hr, args.resting_hr, user_note=args.user_note,
                 force=args.force,
                 response_path=args.llm_response)


if __name__ == "__main__":
    main()
