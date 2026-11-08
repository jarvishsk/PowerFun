# PowerFun 参照物取数逻辑修复 PRD

- **日期**：2026-10-05
- **项目**：`~/Projects/skills/PowerFun`
- **背景**：复核确认长期趋势判定存在取数缺陷——温区三档分桶（mid=(min+max)/2，≤25°C 为 mild）+ 同类型过滤，把凉爽天跑步的基线隔离到只剩过期数据。2026-10-04 实例：mild+轻松跑 180 天窗口仅 6 次且全部在 4-6 月（6 月唯一样本是 6:41 慢速跑），月度回归用月份序号当 x 轴 → 荒谬「退步」判定（配速月降 21.7 秒），与实际持续进步严重冲突
- **注意**：本 PRD 影响 prompt 内容（long_term 字段、分圈基线标注进入 prompt），**必须 bump 缓存版本号到 3**

## 通用要求

- G1：`main.py` 的 `LLM_PROMPT_VERSION` 从 2 改为 3（旧缓存自动失效，重跑一次 deep-analyze 会重新调用 LLM，属预期）
- G2：最小改动，不改图表样式、不动 Karvonen/区间算法/分圈图表结构
- G3：禁止 `or` 数值 fallback
- G4：venv 验证；完成后 git commit + **git push**（远端 origin 已配置）

## F1 趋势判定：保时效优先 + 基线新鲜度门槛（`src/deep_analyzer.py`）

`_calc_long_term` 与 `_calc_short_term` 的基线选择逻辑改为**统一的三级顺序**：

1. **窗口内同温区**：≥3 次 **且** 最新样本距目标日 ≤45 天 → 采用
2. **窗口内不限温区**：≥3 次 **且** 最新样本 ≤45 天 → 采用，`reason`/输出里标注「跨温区基线」
3. 否则 → 数据不足，`message` 区分原因：`样本不足`（n<3）/ `基线过旧`（最新样本 >45 天）

（现状：同温区 <3 才放宽不限温区，无新鲜度检查 → 6 次过期样本也能产出趋势结论）

**月度回归修正**（`_calc_long_term` 内）：
- x 轴从月份序号 `np.arange(len)` 改为**真实月份间隔**：`x = [(p - p0).n for p in monthly_stats['year_month']]`（pandas Period 月差）
- **每月最少 2 个样本**才纳入回归：groupby 时带 `count`，count<2 的月份从回归中剔除（样本总数报告不变）；剔除后有效月份 <3 → 数据不足

## F2 对比分析中位数：放宽顺序保时效（`_compare_with_history`）

放宽链从「90天同温区 → 180天同温区」改为：

1. 90 天同温区（≥3 次）
2. **90 天不限温区**（≥3 次）
3. **180 天不限温区**（≥3 次）
4. 数据不足

（把「时效」排在「同温」前面，避免死卡温区用过期数据；每级采用时在结果里记 `baseline_scope: 'same_temp'|'all_temp'` 供 F4/F5 使用）

## F3 每公里参照物：分圈历史加温区偏好 + 基线构成标注

`_load_similar_lap_history`（main.py）选择顺序改为：

1. 近 90 天 + 同类型 + **同温区** 的跑步分圈（≥5 次跑步）
2. 近 90 天 + 同类型 + 不限温区（≥5 次跑步）
3. 现状逻辑：最近 N=100 次同类型（兜底，跨全年）

`lap_data` 输出增加 `baseline_note` 字段（如「同温区 8 次」/「跨温区 9 次」）：
- 深析报告分圈区块标题处显示：`对比前 N 次同类型跑步（同温区 X 次）`
- `_format_lap_data` 同步该标注进 prompt 分圈段首行

## F4 短期 verdict 温度背景（`src/analysis_report.py` 模板）

`short_term` 走了 F2/F1 的不限温区降级时（`baseline_scope == 'all_temp'`），心率/配速/效率三行 verdict 后追加「·跨温区基线」标注（B2 行内追加，badge 不动）

## F5 一致性连带（`_get_long_term_baseline`）

percentile / expected_pace 使用的 `_get_long_term_baseline` 同步 F1 的三级顺序 + 新鲜度门槛（输出同样带 `baseline_scope`）；基线过旧时 percentile/expected_pace 返回数据不足（模板已有降级显示）

## 验收标准

1. **今天场景复现**（2026-10-04，mild）：长期判定不再出现「退步」——应走「跨温区基线」给出基于近期数据的结论，或合理的数据不足；`_compare_with_history` 中位数基线应为 90 天不限温区（近期 9 次），不再是春天 6 次
2. **热天场景回归**（2026-09-24，hot）：同温区样本充足，判定与修复前一致（进步/持平类结论不变）
3. **构造用例**：伪造「6 次春天 mild + 近期全 hot」df → 长期判定走跨温区或数据不足，**绝不出现基于春天数据的退步**；回归 x 轴验证真实月差（4月→6月 x=[0,1,2]，4月→10月 x=[0,...,6]）
4. **单月单样本**：某月只有 1 次跑步时该月不进回归（用真实数据验证：今天场景 6 月被剔除后结论变化）
5. **分圈标注**：今天深析报告分圈区块显示基线构成（如「对比前 9 次同类型跑步（跨温区 9 次）」）
6. **F4 标注**：今天报告短期三行带「·跨温区基线」（若走了降级）
7. **prompt 版本**：缓存 frontmatter 写入 `prompt_version: 3`；首次 deep-analyze 重调 LLM，二次缓存命中
8. **全量回归**：`python3 main.py --load-parquet` 正常，13 图表、报告无报错
9. 三场景 HTML 目视检查（0924 / 0928 / 1004）无渲染破损
10. commit（中文 conventional）+ push 成功

## 约束

- 只碰：`src/deep_analyzer.py`、`src/analysis_report.py`、`main.py`、`src/chart_generator.py`（仅 F3 标注如需）
- 不碰：心率区间算法、Karvonen 参数、PDF、Garmin 登录、图表样式、VR 阈值（0.2）
- `_calc_yoy` 逻辑不动（F1 只改基线选择与回归，yoy 照常挂返回）
