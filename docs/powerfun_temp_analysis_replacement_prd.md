# PRD: 综合报告"气温-功率-心率分析"替换方案

## 1. 背景

当前综合分析报告中的"气温-功率-心率分析"使用 `power_hr_temp_data`（功率区间 × 气温区间 → 平均心率分组柱状图），信息虽全但不够直观。现替换为 3 张更直观的多变量可视化图表。

## 2. 改动范围

- **新增**：3 张图表（beats/km 心率成本、速度-HR 散点图、速度-HR 温度分层曲线）
- **删除**：旧的 `power_hr_temp_data` 相关代码（`chart_generator.py` 中的相关方法、`report_generator.py` 中的渲染逻辑、`analysis_report.py` 中的调用）
- **不涉及**：深析报告（Pa:Hr 已在那里）、数据获取层（`data_fetcher.py`）、数据清洗层（`data_processor.py`）

## 3. 可用数据字段

从 `data_processor.py` 处理后得到的 `df` 中可用字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `date` | datetime | 跑步日期 |
| `avg_hr` | float | 平均心率 (bpm) |
| `avg_pace_sec` | float | 平均配速 (秒/km) |
| `avg_power` | float | 平均功率 (W) |
| `avg_speed` | float | 平均速度 (km/h) — 如不存在需计算: `3600 / avg_pace_sec` |
| `min_temperature` | float | 最低温度 (°C) |
| `max_temperature` | float | 最高温度 (°C) |
| `category` | str | 跑类（easy_run, aerobic_run, lsd, full_marathon, half_marathon, race_event） |
| `category_name` | str | 跑类中文名 |
| `category_color` | str | 跑类颜色 |
| `distance` | float | 距离 (km) |

温度字段建议：如果 `min_temperature` 和 `max_temperature` 都存在，用 `(min + max) / 2` 作为 `avg_temperature`。如果只有一个，直接用。

## 4. 新增图表详细规格

### 4.1 图1：beats/km 心率成本趋势图

**方法名**：`create_beats_per_km_chart(self, df: pd.DataFrame) -> Dict`

**指标计算**：
```python
beats_per_km = avg_hr * (avg_pace_sec / 60.0)
# 即: bpm × min/km = 心搏/km
# 示例: HR=140, pace=6:00 → 140 × 6 = 840 beats/km
```

**图表规格**：
- **类型**：Plotly Scatter + Lines
- **横轴**：日期（按时间排序）
- **纵轴**：beats/km（数值轴）
- **颜色**：按 `category` 着色（使用现有 `CATEGORY_COLORS` + `CAT_NAME_MAP`）
- **趋势线**：添加一条所有数据的线性回归趋势线（灰色虚线），标注斜率（如 "-3.2 beats/km/月"）
- **hover 信息**：日期、标题、心率、配速、beats/km 值、气温
- **高度**：450px
- **图例**：底部水平

**关键细节**：
- 过滤掉 `avg_hr <= 0` 或 `avg_pace_sec <= 0` 的行
- 如果数据点 < 3 个，返回空字典
- 纵轴 title: "心率成本 (beats/km)"
- 在图表右上角标注当前平均值："Avg: 840 beats/km"

---

### 4.2 图2：速度-心率散点图（颜色 = 气温）

**方法名**：`create_speed_hr_scatter_chart(self, df: pd.DataFrame) -> Dict`

**指标计算**：
```python
avg_speed_kmh = 3600.0 / avg_pace_sec  # km/h
avg_temperature = (min_temperature + max_temperature) / 2
```

**图表规格**：
- **类型**：Plotly Scatter
- **横轴**：速度 (km/h)
- **纵轴**：心率 (bpm)
- **颜色编码**：使用连续色带（`colorscale='RdBu_r'` 或自定义蓝→红），映射 `avg_temperature`
- **标记**：圆形点，size=10，透明度 0.75
- **趋势线**：添加线性回归趋势线（黑色虚线）
- **hover 信息**：日期、标题、速度(km/h)、心率(bpm)、气温(°C)、功率(W)
- **高度**：450px
- **colorbar**：右侧显示气温色标，title="气温(°C)"

**关键细节**：
- 过滤掉心率或速度异常值（HR < 60 或 speed < 5 或 speed > 25）
- 如果数据点 < 5 个，返回空字典
- 横轴 title: "速度 (km/h)"，纵轴 title: "心率 (bpm)"
- 色带范围：使用数据中的 min/max 温度，范围扩展 ±2°C

---

### 4.3 图3：速度-心率温度分层曲线

**方法名**：`create_speed_hr_temp_curves(self, df: pd.DataFrame) -> Dict`

**温度分组**：
```python
bins = [
    (-float('inf'), 15, '<15°C 冷'),
    (15, 20, '15-20°C 凉爽'),
    (20, 25, '20-25°C 适中'),
    (25, 30, '25-30°C 热'),
    (30, float('inf'), '30°C+ 酷热'),
]
```

**颜色方案**：
```python
temp_group_colors = {
    '<15°C 冷': '#1E90FF',      # 冷蓝
    '15-20°C 凉爽': '#4169E1',   # 宝蓝
    '20-25°C 适中': '#32CD32',   # 绿色
    '25-30°C 热': '#FF8C00',     # 橙色
    '30°C+ 酷热': '#FF4500',     # 红橙
}
```

**图表规格**：
- **类型**：Plotly Scatter（每个温度组一条线）
- **横轴**：速度 (km/h)
- **纵轴**：心率 (bpm)
- **每组一条趋势线**：对每个温度组内的所有散点做线性回归，画出拟合线
- **线宽**：2.5px
- **hover 信息**：组名、样本数、速度、心率
- **高度**：450px
- **图例**：底部水平，格式："20-25°C 适中 (n=42)"

**关键细节**：
- 只有样本数 ≥ 3 的组才绘制
- 横轴 title: "速度 (km/h)"，纵轴 title: "心率 (bpm)"
- 添加注释：如果最高温组和最低温组在同一速度下的 HR 差值 > 5bpm，在图上标注差异值
- 如果所有组总数据点 < 10，返回空字典

---

## 5. HTML 模板改动

### 5.1 删除的区块

**report_generator.py 模板中**：
- 删除 `{% if power_hr_temp_data %} ... {% endif %}` 整个区块（"气温-功率-心率分析"）
- 删除 `power_hr_temp_data` 参数传递
- 删除 `power_temp_charts_json` / `power_temp_tables_json` 相关处理
- 删除 JS 中的 `POWER_TEMP_CHARTS` 相关代码

**report_generator.py Python 方法中**：
- `generate_html()` 移除 `power_hr_temp_data` 参数及相关逻辑
- `_render_jinja2()` 移除 `power_hr_temp_data` 参数
- 删除 `has_power_hr_temp` flag

**analysis_report.py 中**：
- 删除调用 `chart_generator` 生成 `power_hr_temp_data` 的代码
- 删除 `generate_html()` 调用中的 `power_hr_temp_data` 参数

### 5.2 新增的区块

**HTML 模板中新增**：
```html
{% if has_beats_km %}
<div class="section">
    <h2 class="section-title"><span class="icon">💓</span>心率成本趋势 (beats/km)</h2>
    <div id="chart-beats-km" class="chart-container"></div>
</div>
{% endif %}

<div class="charts-row">
    {% if has_speed_hr_scatter %}
    <div class="section">
        <h2 class="section-title"><span class="icon">🌡️</span>速度-心率散点 (颜色=气温)</h2>
        <div id="chart-speed-hr-scatter" class="chart-container"></div>
    </div>
    {% endif %}
    {% if has_speed_hr_temp %}
    <div class="section">
        <h2 class="section-title"><span class="icon">🌡️</span>速度-心率温度分层</h2>
        <div id="chart-speed-hr-temp" class="chart-container"></div>
    </div>
    {% endif %}
</div>
```

**JS 中新增渲染代码**：
```javascript
const beats_km = {{ charts_json.get('beats_per_km', 'null') | safe }};
const speed_hr_scatter = {{ charts_json.get('speed_hr_scatter', 'null') | safe }};
const speed_hr_temp = {{ charts_json.get('speed_hr_temp_curves', 'null') | safe }};

// 在对应 {% if %} 块内 Plotly.newPlot
```

---

## 6. 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `src/chart_generator.py` | 新增 | +3 个方法: `create_beats_per_km_chart`, `create_speed_hr_scatter_chart`, `create_speed_hr_temp_curves` |
| `src/chart_generator.py` | 修改 | `generate_all_charts()` 注册新方法 |
| `src/report_generator.py` | 修改 | HTML 模板：删除旧区块，添加新区块 + JS |
| `src/report_generator.py` | 修改 | `generate_html()`: 移除 `power_hr_temp_data` 参数，添加 3 个 has_* flag |
| `src/report_generator.py` | 修改 | `_render_jinja2()`: 同上 |
| `src/analysis_report.py` | 修改 | 调用处：移除旧逻辑，调用新方法 |

## 7. 验收标准

1. `python main.py --webui-only` 正常启动
2. 综合报告能正常生成，3 张新图都能渲染
3. 旧的"气温-功率-心率分析"区块不再出现
4. 所有图表 hover 信息完整
5. 数据异常处理：无数据时不报错、不渲染空图
6. beats/km 趋势线斜率标注正确
7. 温度分层曲线各组图例含样本数
8. 图表高度一致（450px），排版美观
9. 代码风格：中文注释
10. 无 lint 错误

## 8. 注意事项

- 使用现有 `CATEGORY_COLORS` 和 `CAT_NAME_MAP` 保持一致性
- Plotly 图表返回格式必须与现有方法一致（`fig.to_dict()` + `_to_js_dict()` 序列化）
- 温度计算优先使用 `(min + max) / 2`，缺失时降级处理
- 回归线使用 `np.polyfit(x, y, 1)` 计算
- 所有方法需要过滤无效数据（NaN、0、负值）
- 遇到问题上报主 Agent，不要自行猜测
