# PowerFun 报告优化 v2 PRD

- **日期**：2026-09-28
- **项目**：`~/Projects/skills/PowerFun`
- **状态**：需求已与老板逐项确认（A1/A2/B1/B2/C1/C2/C3 + 历史回溯全部确认）
- **注意**：本 PRD 涉及 prompt 结构变更，**必须做缓存版本失效**（见通用要求 G1），否则旧缓存会让新点评逻辑不生效

## 通用要求

- G1 **缓存版本号**：`main.py` 缓存 frontmatter 增加 `prompt_version:` 字段；当前版本 `2`。读取时版本不匹配视为无缓存。LLM 调用成功后写入当前版本。这样本次部署后旧缓存自动失效，重跑同一次跑步会重新调用 LLM（预期行为，验收时说明）。
- G2 最小改动，不改图表整体样式语言（双轴新图按现有图表风格画）。
- G3 禁止 `or` 做数值 fallback（AGENTS.md Python 规则）。
- G4 全部验证用项目 venv：`cd ~/Projects/skills/PowerFun && source venv/bin/activate`。
- G5 完成后 git commit（不 push），提交信息按项目现有风格（中文 conventional）。

## A. 综合报告（`src/chart_generator.py` + `src/report_generator.py`）

### A1 删除「距离趋势」图

删除链路（全链路删干净，不留死代码）：
- `chart_generator.py` `generate_all_charts()` 中 `charts['distance_trend']` 生成调用及 try/except 块
- `chart_generator.py` `create_distance_trend_chart()` 方法本体
- `report_generator.py` 模板中「📏 距离趋势」section（约 725-728 行）
- `report_generator.py` 模板底部 JS：`const distance_trend = ...` 及 `if (distance_trend && ...) Plotly.newPlot('chart-distance', ...)` 块

### A2 新增双轴图：垂直振幅比 + 触地时间趋势

- 位置：放在原「距离趋势」的位置（心率分布直方图 section 之后）
- 新图表函数 `create_vr_gct_trend_chart(df)`：
  - X 轴：日期（全部跑步记录）
  - 左 Y 轴：vertical_ratio（%），右 Y 轴：ground_contact_time（ms）
  - 两条折线 + 各自 marker；缺失值为断点（Plotly 默认 connectgaps=False 即可，不要填 0）
  - 标题「垂直振幅比 & 触地时间趋势」，图例居中（与现有图表一致）
- 接入 `generate_all_charts()` 为 `charts['vr_gct_trend']`，模板加 section + JS 渲染块，参照现有图的写法
- 全部记录都缺这两个字段时图表为空也要 gracefully 跳过（参照现有 `temp_hr_scatter` 的条件渲染模式）

## B. 深析报告结构化层（`src/deep_analyzer.py` + `src/analysis_report.py`）

### B1 VR 进步阈值 0.5 → 0.2

`_compare_with_history()` 中 `vr_trend` 的 verdict 阈值：
```python
# 现状
'更经济' if vr_diff < -0.5 else ('更费力' if vr_diff > 0.5 else '持平')
# 改为
'更经济' if vr_diff < -0.2 else ('更费力' if vr_diff > 0.2 else '持平')
```
（VR 越低越好，diff = 当前 - 历史中位。）`_eval_vertical_ratio()` 的绝对值分级（优秀/良好/一般）**不动**。

### B2 「状态与趋势」三行结论丰富化

现状：心率/配速/效率三行只显示一个 verdict badge（如「偏轻松」）。改为 badge 后追加一句数据解释，**模板侧实现，不增加 LLM 调用**：

- 需要 `short_term` 结构化数据里补充每个指标的当前值与对比基线值（Coder 自查 `_calc_short_term` 现有输出，缺什么补什么，如 `hr_current`/`hr_baseline`、`pace_current_sec`/`pace_baseline_sec`、`eff_current`/`eff_baseline`）
- 模板每行渲染为：`[badge] 当前 X vs 近N次中位 Y（差 Z）`，配速用 `format_pace` 格式化，心率取整，效率保留两位
- 数据不足（无 baseline）时保持现状只显示 badge

## C. 教练点评 prompt 层（`src/deep_analyzer.py`）

### C1 技术效率分析：只在有变化时展开

新增结构化计算（建议挂在 `_compare_with_history` 或独立方法，输出进 `comparison['tech_changes']`）：对比本次 vs 历史中位数，阈值：

| 指标 | 字段 | 进步/退步阈值 |
|------|------|--------------|
| 垂直振幅比 | vertical_ratio | ±0.2 |
| 触地时间 | ground_contact_time | ±5 ms |
| 步频 | cadence | ±2 spm |
| 步幅 | stride_length | ±1 cm |

方向：VR/GCT 越低越好，cadence 适度高好（阈值内算持平，不做方向性判定，只做变化量），stride 只做变化量不做方向判定（避免与身高无关的误判）。

`_build_prompt` 技术段逻辑改为：
- 有变化的指标：正常输出指标名 + 当前值 + 与历史中位 diff + 评价，并在指令中要求 LLM 只对变化指标展开点评
- 全部稳定（无一项超阈值）：指令改为「本次各项技术指标与历史水平相比均无超阈值变化，本节用一句话确认稳定即可，不要逐项罗列指标数值」

### C2 长期趋势：增加去年同期对比

- `comparison['long_term']['yoy']` 新增结构化输出：
  - 窗口定义：本次跑步日期的去年同期等价窗口（对齐月日，向前相同天数；窗口长度与长期窗口一致，当前 180 天）
  - 对比维度：心率中位、配速中位（有数据时也算趋势斜率，实现从简）
  - 无数据时 `yoy = {'message': '数据不足'}`（当前数据 2025-10-24 起，今年 9 月的跑步其去年同期窗口暂无数据，属预期）
- 模板「长期趋势」行追加：有数据时「去年同期：心率 X vs Y bpm，配速 A vs B」；无数据时不显示（不显示「暂无数据」占位，直接省略）
- `_build_prompt` 历史对比段：yoy 有数据时追加一行去年同期对比；无数据时**不出现**（prompt 里不提示"没数据"）

### C3 改进建议：只针对本次暴露的问题

`_build_prompt` 第 6 项（改进建议）指令改为：
- 只针对**本次跑步暴露的问题**提建议（分圈漂移、心率失控、配速执行偏差、天气应对失误等）
- 长期固化存在的技术短板（如触地时间长期偏长）**除非本次明显恶化，否则不提**
- 删除原指令中「长期训练管理建议作为补充放在最后」的要求
- 保留【最高优先】→【次优先】→【中长期】分层格式与编号列表格式契约
- 若本次执行无大问题，允许只给 2-3 条，不强行凑数

## D. 历史数据回溯（`main.py` + `src/data_fetcher.py`）

- 新增 `--backfill-since YYYY-MM-DD` 参数：强制从该日期起拉取，与现有缓存**合并**（按 activity_id 去重更新，不得清空重建现有 parquet/缓存）
- 完成后老板会跑一次 `--backfill-since 2025-01-01`（Coder 自己也跑一次作为验收，见下）
- SKILL.md 运行模式表加一行：「补拉历史数据 | `python3 main.py --backfill-since 2025-01-01`」

## 验收标准

1. **A1**：综合报告 HTML 中无「距离趋势」、无 `chart-distance`；源码无 `create_distance_trend_chart` 残留
2. **A2**：综合报告新图正常渲染（打开 HTML 目视或检查 charts_json 含 `vr_gct_trend` 且两个 yaxis 存在）；截图或描述折线断点行为
3. **B1**：构造 diff=-0.3 → verdict「更经济」；diff=-0.1 → 「持平」（用 python 直接调 `_compare_with_history` 或提取逻辑单测，贴输出）
4. **B2**：深析报告「状态与趋势」三行各带数据解释（贴 HTML 片段）；LLM 调用次数/消耗不变（prompt 字符数不因此项增长，反而可能略降）
5. **C1**：构造「全稳定」数据的 `_build_prompt` 输出验证稳定指令出现；构造「VR 恶化 0.3」验证只展开变化指标（贴 prompt 片段）
6. **C2**：当前数据下 yoy 输出 `数据不足` 且模板不渲染去年同期行、prompt 不含去年同期段；用伪造的 df 构造有数据场景验证模板+prompt 正常输出（贴片段）
7. **C3**：`_build_prompt` 第 6 项为新指令文本（贴片段）；跑一次完整深析（`--deep-analyze 2026-09-24 --force --user-note "测试验证"`，**注意这会产生一次真实 LLM 调用**），确认 6 个小节结构完好
8. **G1 缓存失效**：部署后跑一次不加 `--force` 的 deep-analyze latest，确认因版本不匹配重新调用 LLM（日志无「复用 LLM 缓存」）；随后再跑一次确认缓存生效
9. **D**：`--backfill-since 2025-01-01` 执行成功，parquet 记录数 ≥ 之前（136），报告正常生成
10. **回归**：`python3 main.py --load-parquet` 全量报告正常；深析 6 小节齐全、格式契约完好

## 约束

- 只碰：`main.py`、`src/chart_generator.py`、`src/report_generator.py`、`src/deep_analyzer.py`、`src/analysis_report.py`、`src/data_fetcher.py`、`SKILL.md`
- 不碰：心率区间算法、Karvonen 参数、PDF 生成、Garmin 登录逻辑
- 分圈图表相关代码不碰
