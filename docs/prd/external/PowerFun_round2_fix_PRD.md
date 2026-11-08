# PowerFun Round 2 修复 PRD

## 背景
第一轮已修复：百分位逻辑、fetcher 关闭时机（含批量深析复用）、温度缺失处理、日期过滤（<= + activity_id 排除）。
本轮处理：剩余高风险 H4、中风险正确性项、以及「气温图只算不渲染」。

## 工作目录
`~/Projects/skills/PowerFun`

## 修复范围

### 1. H4：`_analyze_laps` 百分位计算与图表层不一致
- **文件**：`src/deep_analyzer.py::_analyze_laps`
- **当前**：median 用 `sorted[len//2]`，P20/P80 用 `sorted[max(0,2*n//10)]` / `sorted[min(n-1,8*n//10)]` 整数下标近似。
- **修复**：统一改用 `np.percentile(paces, 50/20/80)`，与 `src/chart_generator.py` 分圈图的计算方式完全一致。
- 注意保持 `history_median` / `history_p20_pace` / `history_p80_pace` 的输出结构与下游（analysis_report 文字部分）兼容；样本为空时保持原有 0/None 行为。

### 2. M6：深析模板 `pa_hr_history` 渲染脚本条件不完整
- **文件**：`src/analysis_report.py`（Jinja2 模板）
- **当前**：`pa_hr_history` 的渲染脚本在 `{% if pa_hr_history %}` 块内，但目标 `<div id="pa-hr-trend-chart">` 在 `{% if pa_hr %}` 块内；`pa_hr` 为 None 而 `pa_hr_history` 存在时脚本找不到 div。
- **修复**：把渲染脚本移入与 div 相同的条件块内，或改为 `{% if pa_hr and pa_hr_history %}`。

### 3. M9：`data_processor` 全局格式开关误判混合格式
- **文件**：`src/data_processor.py::process` / `_map_activity_impl`
- **当前**：`self._use_summary_extractor = any('summaryDTO' in a ...)`，列表中只要有一条 garmin 格式，全部活动都走 summary 提取。
- **修复**：改为**按单条活动**判断格式并选择提取器（每条活动独立判断 `'summaryDTO' in activity`），消除全局状态。

### 4. M11：`fetch_lap_data` 把合法 0 值当缺失
- **文件**：`src/data_fetcher.py::fetch_lap_data`
- **当前**：`avg_hr = lap.get("averageHR") or np.nan`，Garmin 返回 0 时被替换为 NaN。
- **修复**：改为 `val if val is not None else np.nan` 的形式，功率/步频等字段同样处理。

### 5. M13：`fetch_all_laps.py` 失败计数永远为 0
- **文件**：`fetch_all_laps.py`
- **修复**：except 块中 `fail_count += 1`。

### 6. M15：深析报告文件名同天覆盖
- **文件**：`src/analysis_report.py::generate`
- **当前**：`run_analysis_{YYYYMMDD}.html`，同一天多次跑步互相覆盖。
- **修复**：文件名加 `activity_id` 后缀：`run_analysis_{YYYYMMDD}_{activity_id}.html`。iCloud 复制路径同步。若无 activity_id 则保持原格式。

### 7. M17：`df_near` 计算后未使用
- **文件**：`src/deep_analyzer.py::_compare_with_history`
- **修复**：能力变化对比（心率/配速/功率/效率中位数对比）改用 `df_near`（同类型 ±20% 距离）；若 `df_near` 样本 <3 则降级回 `df_same_temp`。与注释原意保持一致。

### 8. M18：长期趋势“分化”分支不可达
- **文件**：`src/deep_analyzer.py::_calc_long_term`
- **当前**：`elif all('升' in r or '降' in r for r in reasons)` 恒真，verdict 永不出现“分化”。
- **修复**：重写判定——
  - 负向信号：心率月升、配速月降、效率月降
  - 正向信号：心率月降、配速月升、效率月升
  - 正负兼有 → `verdict='分化'`；仅负向 → '退步'；仅正向 → '进步'；无信号 → '稳定'。

### 9. M19：缺失技术指标被标红 poor
- **文件**：`src/analysis_report.py::_eval_class`
- **当前**：`'暂无数据'` 未命中映射，返回 `'poor'`（红色“较差”徽章）。
- **修复**：缺失值返回 `'missing'`，模板/CSS 增加灰色样式（如 `.eval-missing { color:#999; }`），文案显示“暂无数据”。

### 10. M22：气温图只算不渲染（本轮重点）
- **文件**：`src/report_generator.py::_get_html_template`（以及渲染脚本区）
- **当前**：`generate_all_charts` 计算了 `temp_hr_scatter`、`beats_per_km`、`speed_hr_scatter`、`speed_hr_temp_curves`，但模板从未渲染。
- **修复**：在主报告模板中新增图表区块，按 PRD `docs/powerfun_temp_analysis_replacement_prd.md` 的原设计渲染以下图表（进**综合报告**）：
  - `temp_hr_scatter`（气温-心率影响分析，双轴时间序列）
  - `speed_hr_scatter`（速度-心率散点图，颜色=气温）
  - `speed_hr_temp_curves`（速度-心率温度分层曲线）
  - `beats_per_km`（心率成本趋势）
- 参考现有 `charts_json` 的渲染方式（`{{ charts_json.get('xxx', 'null') | safe }}`），空图表时跳过对应区块，不报错。

## 明确不做
- 不改 1km 自动分圈假设、不改残圈丢弃逻辑、不引入距离/温度分层。
- 不动中风险 M10/M12/M14/M16/M20 和低风险项（Round 3）。
- 不重构架构。

## 测试要求
1. `python3 main.py` 正常模式完整跑通；检查 `~/Documents/Run/PowerFun.html` 中包含新增的气温图表区块（grep `speed-hr-scatter` 或类似 div id）。
2. `python3 main.py --load-parquet --deep-analyze "2026-08-10"` 跑通，报告正常生成（新文件名带 activity_id）。
3. 深析报告“历史排名”P 值语义正确（效率越高 P 越高）。
4. 文字部分引用的 P20/P80 与图表一致（抽查一条）。

## 输出要求（重要）
完成后必须把工作成果写入文件 `/Users/jarvis/.openclaw/workspace/tmp/powerfun_round2_fix_report.md`，内容包括：修改的文件/函数清单、每项改动的关键代码说明、测试命令与结果、遗留问题。不要只在会话里回复。
