# PowerFun 分圈图历史基线修复 PRD

## 背景
深度分析报告中的「每公里配速」「每公里心率」两张图，历史基线存在两个问题：
1. 回溯历史日期做深析时，目标日期之后的跑步会进入历史分圈样本，造成未来数据污染。
2. P20–P80 阴影带在当前阈值（历史 run ≥8）下对小样本类型不够稳定。

## 目标
- 修复未来数据污染。
- 收紧 IQR / P20–P80 展示规则，使历史带只在数据充足时显示。
- 保持 1km 自动分圈假设、残圈丢弃逻辑不变。
- 不引入距离/温度分层。

## 改动范围

### 1. `src/main.py`：`_generate_deep_report`

#### 1.1 分圈历史样本过滤
在选取 `recent_laps` 时，只取 **目标日期之前** 的同类型历史跑步。

当前代码（约 198–207 行）：
```python
category = target_run.get('category', '')
N = 10
if category and 'category' in df.columns:
    df_same = df[df['category'] == category]
else:
    df_same = df
# 排除本次
df_same = df_same[df_same['activity_id'] != activity_id]
# 按日期排序，取最近 N 次
df_same = df_same.sort_values('date', ascending=False).head(N)
```

改为：
```python
category = target_run.get('category', '')
N = 10
if category and 'category' in df.columns:
    df_same = df[df['category'] == category]
else:
    df_same = df
# 排除本次
df_same = df_same[df_same['activity_id'] != activity_id]
# 排除目标日期之后的所有数据，避免未来数据污染
target_ts = pd.Timestamp(target_run.get('date'))
df_same = df_same[df_same['date'] < target_ts]
# 按日期排序，取最近 N 次
df_same = df_same.sort_values('date', ascending=False).head(N)
```

#### 1.2 Pa:Hr 历史趋势过滤
同一函数中，计算 `pa_hr_history_data` 时也要加 `date < target_ts` 过滤。

当前：
```python
pa_hr_history_data = df[
    (df['distance'] >= 3.0) &
    (df['activity_id'] != activity_id)
].copy()
```

改为：
```python
pa_hr_history_data = df[
    (df['distance'] >= 3.0) &
    (df['activity_id'] != activity_id) &
    (df['date'] < target_ts)
].copy()
```

> 正常模式（深析最近一次跑步）中 `target_ts` 就是最新日期，过滤无实际影响；回溯日期时则保证基线因果正确。

---

### 2. `src/chart_generator.py`：`generate_lap_pace_chart_v2` 与 `generate_lap_hr_chart`

#### 2.1 新阈值规则
- **P20–P80 阴影带**：仅当该分类历史 run 总数 ≥30 且当前公里样本数 ≥20 时绘制。
- **历史中位线**：仅当当前公里样本数 ≥5 时绘制。
- **IQR 异常过滤**：仅当当前公里样本数 ≥10 时启用；否则不过滤直接算 median。

#### 2.2 实现要点
两张图当前逻辑类似，分别修改其中的 `show_band` 与样本判断。

以 `generate_lap_pace_chart_v2` 为例：

1. 新增分类级开关：
   ```python
   category_enough = len(recent_laps) >= 30
   ```

2. 在按公里序号收集历史样本后，判断：
   ```python
   if paces:
       use_iqr = len(paces) >= 10
       if use_iqr:
           paces = self._iqr_filter(paces)
       hist_median_pace.append(float(np.percentile(paces, 50)))
       if category_enough and len(paces) >= 20:
           hist_p20_pace.append(float(np.percentile(paces, 20)))
           hist_p80_pace.append(float(np.percentile(paces, 80)))
       else:
           hist_p20_pace.append(None)
           hist_p80_pace.append(None)
   else:
       hist_median_pace.append(None)
       hist_p20_pace.append(None)
       hist_p80_pace.append(None)
   ```

3. 删除/替换原来的全局 `show_band = bool(recent_laps) and len(recent_laps) >= 8`，改为按每个公里独立判断。

`generate_lap_hr_chart` 做同样修改（对 `hrs` 列表判断）。

#### 2.3 图例处理
当某个公里因为样本不足没有 P20–P80 时，该公里不画阴影；图例仍保留「历史P20-P80区间」名称，但只在有数据处填充。

---

### 3. `src/deep_analyzer.py`：`_analyze_laps`（可选一致性修复）

`_analyze_laps` 生成的 `history_p20_pace` / `history_p80_pace` 会被文字报告引用。为避免文字和图表不一致，建议同步阈值：

- 仅当 `len(recent_laps) >= 30` 且当前公里样本数 ≥20 时才计算 P20/P80；否则置 0/None。
- median 保持样本 ≥1 即可计算。

如果改动会显著影响 `analysis_report.py` 的渲染，请同步检查并处理 None。

## 验收标准

1. 用 `--deep-analyze 2026-08-10 --load-parquet` 生成报告，确认：
   - 分圈图的历史中位线/P20–P80 不再使用 8/11、8/13、8/16、8/19、8/21 的数据。
   - Pa:Hr 历史趋势图也不使用这些未来日期。
2. easy_run（77 次）的 km 1–16 仍正常显示 P20–P80 带。
3. lsd（21 次）、aerobic_run（15 次）的 per-km 图：
   - 早期公里（样本 ≥20 处）可显示带；
   - 后期公里降级为只显示中位线；
   - 中位线样本 <5 的公里不画历史参照。
4. 主报告 `PowerFun.html` 正常生成，无报错。

## 备注
- 不修改 1km 自动分圈假设。
- 不修改残圈（<1km）丢弃逻辑。
- 不引入距离/温度分层。
