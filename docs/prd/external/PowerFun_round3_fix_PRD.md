# PowerFun Round 3 修复 PRD

## 背景
Round 1/2 + 回归修复已完成并提交（commit 44b620b）。本轮处理剩余中风险体验项与已知的低风险项。

## 工作目录
`~/Projects/skills/PowerFun`

## 修复范围

### 1. M10：配速趋势图 Y 轴刻度硬编码
- **文件**：`src/chart_generator.py::create_pace_hr_trend_chart`
- **当前**：`tickvals=[315,330,...,480]`（5:15~8:00/km）硬编码。
- **修复**：根据数据实际范围动态生成刻度（15 秒间隔，范围向外取整到 15 的倍数），保留 mm:ss 格式化。

### 2. M12：速度-心率散点硬编码过滤区间
- **文件**：`src/chart_generator.py::create_speed_hr_scatter_chart`、`create_speed_hr_temp_curves`
- **当前**：`(df['pace_min_km'] >= 4) & (df['pace_min_km'] <= 12)` 硬编码。
- **修复**：改为按数据分位数过滤（如保留 1%~99% 分位范围），或使用 IQR 过滤；样本过少时不过滤。

### 3. M14：fallback 渲染不完整
- **文件**：`src/report_generator.py::_render_fallback`
- **修复方案**：直接强制依赖 jinja2——在 `generate_html` 入口处若 `jinja2` 不可用则抛出明确错误（提示 pip install jinja2），删除不完整的 fallback 字符串替换路径。jinja2 已是事实依赖。

### 4. M16：expected_pace 与 percentile 基线不一致
- **文件**：`src/deep_analyzer.py`、`src/analysis_report.py`
- **修复**：不改计算，在 LLM prompt（`deep_analyzer.py` 中构建对比分析文本处）明确说明两个指标口径：「预期配速=同类型历史配速中位数；历史排名=按跑步经济性 (m/h)/bpm 的百分位」。避免 AI 点评自相矛盾。

### 5. M20：训练建议阈值硬编码
- **文件**：`src/report_generator.py::generate_insights`
- **修复**：把 Z1 占比 30%/50%、步频 170、跑量增长阈值等移入 `src/config.py` 的 `INSIGHTS_CONFIG`，代码从配置读取。

### 6. L21：iCloud 路径硬编码
- **文件**：`main.py`、`src/pdf_generator.py`
- **修复**：统一使用 `DEFAULT_CONFIG['icloud_deep_analysis_dir']`；`src/pdf_generator.py` 中若有独立硬编码则改为从 config 导入。

### 7. L23：删除未使用的 `colors` 变量
- **文件**：`src/chart_generator.py::create_temp_efficiency_chart`

### 8. L24：删除死代码 `skip_pdf`
- **文件**：`main.py::_run_reports`

### 9. L25：消除全局 `args`
- **文件**：`main.py`
- **修复**：`_run_reports` 不再使用 `global args`，所需参数（dry_run、deep_analyze、deep_analyze_all、user_note 等）已全部通过形参传入；检查并删除 `global args` 声明及 `main()` 中的 `global args` 赋值（保持调用方兼容）。

### 10. L26：`fetch_all_laps.py` 硬编码 parquet 路径
- **修复**：从 `src.config.DEFAULT_CONFIG['report_dir']` 读取。

### 11. L27：`_build_temp_impact_reference` 使用归一化分类
- **文件**：`src/deep_analyzer.py::_build_temp_impact_reference`
- **修复**：与 `_get_long_term_baseline` 一致，使用 `_category_norm` 归一化后的分类过滤。

## 明确不做
- 不改 1km 分圈假设、残圈逻辑、不引入距离/温度分层。
- 不改报告整体视觉风格。
- 不动 Round 1/2 已修内容（除非 Round 3 改动直接依赖）。

## 测试要求
1. `python3 main.py` 正常模式跑通，主报告正常生成且气温图、表格（最底部）、深析链接正常。
2. `python3 main.py --load-parquet --deep-analyze "2026-08-10"` 跑通。
3. 配速趋势图刻度覆盖实际数据范围（grep 生成的图表 JSON，tickvals 应包含数据 min/max 内的刻度）。
4. 无 jinja2 时报错信息明确（可用 `python3 -c "import report_generator"` 层面验证逻辑，不必真卸载）。

## 输出要求（必须）
完成后把成果写入 `/Users/jarvis/.openclaw/workspace/tmp/powerfun_round3_fix_report.md`：修改清单、关键代码说明、测试结果、遗留问题。不要只在会话里回复。
