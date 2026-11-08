# PowerFun 图表优化 PRD（直方图删除 + 气温效率图 + P20-P80 阴影修复）

- **日期**：2026-10-11
- **项目**：`~/Projects/skills/PowerFun`
- **状态**：需求已与老板逐项确认（Q1 删两张直方图 / Q2 合并为气温-效率代价图 / Q3 阴影带四项修复）
- **不涉 LLM prompt 改动**：`LLM_PROMPT_VERSION` 保持 4 不动；深析报告重生成走缓存，不产生额外 LLM 调用

## 已核实的背景事实（直接采信）

**Q3 阴影带（深析报告每公里配速图，`generate_lap_pace_chart_v2`）**：
- 数值验证通过（逐公里 P20 < 中位 < P80，无倒挂）——**不是计算 bug，是呈现问题**
- 实测问题证据（2026-10-11 报告）：
  - P20 边缘逐公里跳动：…338.0→346.7→346.7→333.9…（锯齿带 vs spline 平滑主线，视觉冲突）
  - km14-16 阴影宽 53 秒/km（P20 322.9 vs P80 375.7），末段漏斗爆炸——末段样本只剩「跑得远+收尾快」的跑步（选择偏差）
  - band trace 在最后 add → 半透明阴影压在主线上面（z-order 反了）
  - 历史分圈基线只过滤 `pace>0`，**未过滤残圈**（如 15.5km 跑步的 0.5km 残圈配速混入 km-16 基线）

**综合报告当前 14 个区块**（rendered）：配速-心率趋势、月跑量、心率区间分布饼图、类型分布饼图、月度心率区间时长堆积、功率分布直方图、心率分布直方图、VR&GCT 双轴、训练效果趋势、气温-心率效率趋势（temp_hr_scatter）、心率成本趋势、速度-心率散点、速度-心率温度分层曲线、训练结论。
- `create_temp_efficiency_chart`、`create_power_hr_temp_chart`、`create_pa_hr_trend_chart` 已定义但**未渲染**——新图优先评估能否复用

## 需求

### F1 删除两张直方图（综合报告）

全链路删除（不留死代码，参照 v2 A1 的做法）：
- `chart_generator.py`：删 `create_power_distribution_chart`、`create_hr_distribution_histogram` 函数及 `generate_all_charts` 中的接线
- `report_generator.py`：删「功率分布」「心率分布直方图」两个 section 及对应 JS 渲染块（`power_distribution`、`hr_distribution` 变量）

### F2 合并速度-心率两张图为「气温-效率代价图」（综合报告）

- 删除：「速度-心率散点（颜色=气温）」「速度-心率温度分层曲线」两个区块（函数+接线+模板+JS 全链路）
- 新增 `create_temp_efficiency_cost_chart(df)`（**先评估已有未渲染的 `create_temp_efficiency_chart` 能否改造复用**）：
  - X 轴：气温中值（(min+max)/2）
  - Y 轴：效率指数 `3600000/(avg_pace_sec × avg_hr)`（项目已有口径）
  - 散点按跑步类型着色（easy_run/aerobic_run/lsd 区分），近期点更深
  - 一条线性趋势线 + 标注结论：「每升高 1°C，效率指数约降 X（约等于同心率配速慢 Y 秒/km）」——Y 由斜率按中位心率/配速折算
  - 数据不足（<10 个有效点）时 graceful 跳过（参照 temp_hr_scatter 条件渲染模式）
  - 位置：放在原「速度-心率散点」的位置
- 「气温-心率效率趋势」（temp_hr_scatter）保留不动

### F3 P20-P80 阴影带修复（深析报告 `generate_lap_pace_chart_v2`）

1. **z-order**：band trace 最先 add（压在主线和中位线下面）
2. **残圈过滤**：历史分圈基线只纳入完整公里圈——按分圈距离字段过滤（如 `distance_m >= 950`；字段名以实际数据结构为准，若缺距离字段则按「该圈所属跑步的总公里数取整后 lap_index ≤ total_km」规则过滤，并在报告里说明所选口径）
3. **边缘平滑**：`hist_p20_pace` / `hist_p80_pace` 数组做窗口=3 的居中滚动均值后再绘制（中位线已由 `shape='spline'` 渲染平滑，不动；本次配速线不动）
4. **末段门槛**：阴影带绘制条件从「每公里样本 ≥20」收紧为 ≥25，缓解末段漏斗爆炸；平滑+过滤后仍漏斗属真实数据特征，保留

### 同步核对

- `generate_lap_hr_chart`（每公里心率图）若有同样的 band/残圈逻辑，**同步修复**（残圈过滤至少要做；平滑与 z-order 看代码结构顺手做）

## 验收标准

1. **F3 目视**：重生成 2026-10-11 深析报告（`python3 main.py --load-parquet --deep-analyze 2026-10-11`，应缓存命中零 LLM 调用），headless Chrome 截图：阴影带边缘平滑、压在线条下方、末段漏斗明显收窄、数值仍满足 P20<中位<P80
2. **F3 数值**：解析图表 JSON，断言平滑后 p20/p80 数组相邻公里波动幅度下降；残圈过滤后 km16 基线样本构成变化有日志或数据说明
3. **F1**：综合报告 HTML 无「功率分布」「心率分布直方图」字样及对应 div；源码 grep 无函数残留
4. **F2**：综合报告出现「气温-效率」新图，趋势线 + 每 °C 代价标注可见；原两张速度-心率图区块消失
5. **回归**：`python3 main.py --load-parquet` 全量正常；0924/1005 深析报告重生成正常（缓存命中）
6. commit（中文 conventional）+ push

## 约束

- 只碰：`src/chart_generator.py`、`src/report_generator.py`（及 `main.py` 仅若接线需要）
- 不碰：LLM prompt/缓存版本、深析分析逻辑、分圈数据获取（`_load_similar_lap_history` 的基线选择逻辑不动，只动图表内的样本过滤）、其他图表
- 禁止 `or` 数值 fallback；滚动均值注意边界（端点窗口截断，不填 0）
- headless 截图验证用 `--headless=new` 或现有可用方式，截图放 `tmp/` 不提交
