# PowerFun PRD：Pa:Hr 有氧解耦 + 功率法气温分析

**版本**: v4.1
**日期**: 2026-05-17
**目标**: 在现有跑步分析系统中新增两个指标，量化气温对跑步能力的影响

---

## 一、背景与目标

用户（老板）希望在跑步分析中引入气温维度的量化分析，回答一个核心问题：
> "高温对我的跑步能力有多大影响？"

新增三个指标：
1. **Pa:Hr 有氧解耦**（单次跑步内）：反映跑步后半程是否出现热疲劳/心率漂移
2. **功率法气温分析**（跨跑对比）：固定功率输出下，不同气温对心率的影响
3. **热效率指数**（LLM 自然语言）：作为辅助解读融入教练点评

---

## 二、现有基础设施

### 2.1 已有数据源
| 数据 | 字段 | 来源 |
|------|------|------|
| 气温 | `min_temperature`, `max_temperature` | Garmin API |
| 功率 | `avg_power`, `max_power`, `normalized_power` | Garmin API |
| 分圈 | `fetch_lap_data()` → 每圈距离、配速、心率、功率 | Garmin API `/activity-service/activity/{id}/laps` |
| 分类 | `category`（轻松跑/有氧耐力跑/马拉松配速跑等9类） | 本地 RunClassifier |

### 2.2 相关现有模块
- `src/chart_generator.py`：`create_temp_hr_scatter_chart()`, `create_temp_efficiency_chart()` — 已有气温相关图表
- `src/deep_analyzer.py`：`_analyze_laps()` — 已有分圈分析逻辑
- `src/analysis_report.py`：深析报告 HTML 模板
- `src/report_generator.py`：综合报告 HTML 模板（含气温 section）

---

## 三、指标 1：Pa:Hr 有氧解耦

### 3.1 定义
将单次跑步按**距离中点**拆为前后两半程，分别计算"速度/心率"效率比，衡量后半程是否出现心率漂移。

### 3.2 计算公式
```
对一次跑步的 lap 数据：
  total_distance = Σ(lap.distance)
  half_dist = total_distance / 2

  前半程 laps = 累计距离 < half_dist 的 lap
  后半程 laps = 累计距离 ≥ half_dist 的 lap

  speed1 = Σ(lap1.distance) / Σ(lap1.duration)    # m/s
  hr1    = weighted_avg(lap1.avg_hr, lap1.duration) # bpm（按时长加权）
  speed2 = Σ(lap2.distance) / Σ(lap2.duration)
  hr2    = weighted_avg(lap2.avg_hr, lap2.duration)

  ratio1 = speed1 / hr1
  ratio2 = speed2 / hr2

  Pa:Hr = (ratio2 - ratio1) / ratio1 × 100%
```

### 3.3 解读标准
| Pa:Hr 绝对值 | 解读 | 颜色 |
|-------------|------|------|
| <3% | 很稳定 | 🟢 |
| 3~5% | 正常 | 🟡 |
| 5~8% | 有明显漂移 | 🟠 |
| >8% | 热疲劳/耐力不足 | 🔴 |

### 3.4 门槛
- **最低距离 ≥3km**：太短的分半不准，跳过计算
- lap 数据缺失时跳过

### 3.5 输出
- **计算函数**：新增 `_calc_pa_hr(laps: list[dict]) -> dict`，返回：
  ```python
  {
      'pa_hr_pct': float,        # Pa:Hr 百分比（带符号，负值=漂移）
      'pa_hr_abs': float,        # 绝对值
      'verdict': str,            # '很稳定'/'正常'/'有明显漂移'/'热疲劳/耐力不足'
      'verdict_class': str,      # 'excellent'/'good'/'warning'/'poor'（CSS class）
      'verdict_emoji': str,      # '🟢'/'🟡'/'🟠'/'🔴'
      'first_half_speed': float, # m/s
      'first_half_hr': float,    # bpm
      'second_half_speed': float,
      'second_half_hr': float,
      'total_distance': float,   # km
  }
  ```
  若无 lap 数据或距离 <3km，返回 `None`。

### 3.6 放置位置
**深度分析报告**（`src/analysis_report.py`），在「📈 对比分析」section 之后、「🔍 关键发现」之前，新增 section：

```
🔄 有氧解耦分析（Pa:Hr）
┌───────────────────────────────────────────────┐
│              前半程    后半程     Pa:Hr        │
│ 配速        6:00/km   6:00/km                  │
│ 心率        140 bpm   152 bpm                  │
│ 效率比      0.0714    0.0658    -7.8% 🟠       │
│                                               │
│ 解读：有明显漂移（5-8%），可能原因：气温偏高、   │
│       后程疲劳、补水不足                         │
└───────────────────────────────────────────────┘
```

使用 HTML 表格 + 颜色编码展示，不依赖 Plotly 图表。

### 3.7 Pa:Hr 历史趋势图
在深析报告同 section 内，表格下方新增迷你折线图（Plotly）：
- **数据源**：从 `lap_data.parquet` 缓存中提取所有 ≥3km 跑步的 Pa:Hr
- **X 轴**：日期（最近 10 次）
- **Y 轴**：Pa:Hr 百分比（负值）
- **背景色带**：
  - 绿色区域：-3% ~ +3%（稳定区）
  - 黄色区域：-5% ~ -3%（正常区）
  - 橙色区域：-8% ~ -5%（漂移区）
  - 红色区域：< -8%（热疲劳区）
- **点着色**：按跑步分类着色（category_color）
- **hover**：显示日期、类型、距离、气温、Pa:Hr 值
- **门槛**：历史样本 ≥3 次才显示图表

---

## 四、指标 2：功率法气温分析

### 4.1 定义
按**功率分箱**（5W 一档）× **气温分箱**（5°C 一档）统计，对比同一功率输出下不同气温的平均心率变化。

### 4.2 分箱规则
- **功率分箱**：5W 一档，例如 150-155W, 155-160W, ..., 250-255W
  - 动态范围：根据用户实际功率数据，取 `[floor(min/5)*5, ceil(max/5)*5]`
  - 每个功率箱需 ≥2 个样本才显示（太稀的不展示）
- **气温分箱**：5°C 一档
  - 固定区间：`<15`, `15-20`, `20-25`, `25-30`, `>30`
  - 标签：`<15°C`, `15-20°C`, `20-25°C`, `25-30°C`, `30°C+`
  - 气温取 `(min_temperature + max_temperature) / 2`

### 4.3 按分类切换
- 每个训练分类单独计算一张图表 + 一个表格
- 在综合报告 section 顶部加分类标签按钮组，点击切换
- **默认展示**：轻松跑（`easy_run`），因为数据最充分
- **可用分类**：有 ≥5 个有效样本的分类才出现标签
- **分类标签样式**：
  - 使用 `category_name` + `category_color` + `category_icon`
  - 例如：😌 轻松跑 | 💨 有氧耐力跑 | ⚡ 马拉松配速跑 | 🔥 强度训练
  - 当前激活的标签高亮，其余灰色

### 4.4 图表设计（Plotly 分组柱状图）
- **X 轴**：功率区间标签（如 "175-180W", "180-185W"）
- **Y 轴**：平均心率（bpm）
- **分组**：每个气温一档作为一组柱状图
- **颜色**：气温由低到高，蓝色渐变到红色
  - `<15°C`：`#4A90D9`（冷蓝）
  - `15-20°C`：`#5BC0A5`（绿蓝）
  - `20-25°C`：`#F5D76E`（暖黄）
  - `25-30°C`：`#F7882F`（橙色）
  - `30°C+`：`#E74C3C`（热红）
- **hover**：显示功率区间、平均心率、样本数

### 4.5 表格设计（图表下方）
| 功率区间 | <15°C | 15-20°C | 20-25°C | 25-30°C | 30°C+ |
|---------|-------|---------|---------|---------|-------|
| 175-180W | 132(8) | 141(6) | 149(4) | 158(2) | — |
| 180-185W | 138(10) | 147(9) | 156(7) | 165(3) | — |
| 185-190W | 144(7) | 153(8) | 162(5) | — | — |

- 单元格格式：`平均心率(样本数)`
- 当某单元格的气温档位比同功率行的最低气温档位高，且心率升高 ≥5 bpm，加红色背景
- 无数据的单元格显示 `—`

### 4.6 放置位置
**综合分析报告**（`src/report_generator.py`），在气温相关现有 section（`has_temp` / `has_temp_eff`）之后，新增 section：

```
🌡️ 气温-功率-心率分析
[分类标签按钮组]
[Plotly 分组柱状图]
[HTML 数据表格]
```

### 4.7 新增图表生成函数
在 `src/chart_generator.py` 新增：
```python
def create_power_hr_temp_chart(self, df: pd.DataFrame, category: str = 'easy_run') -> Dict:
    """
    功率-气温-心率分组柱状图
    
    Args:
        df: 完整 DataFrame
        category: 跑步分类（如 'easy_run'）
    
    Returns:
        Plotly chart dict（JS 可序列化）
    """
```

### 4.8 综合报告前端交互
在综合报告模板中，分类切换用纯 JS 实现：
- 预渲染所有可用分类的图表数据（JSON 变量）
- JS 函数根据点击的标签切换显示对应图表
- 表格同样用 JS 切换

---

## 五、指标 3：热效率指数（LLM 自然语言）

### 5.1 不需要独立可视化
在深析报告 LLM prompt 中注入气温参考上下文，让 LLM 用自然语言融入教练点评。

### 5.2 注入到 LLM prompt
在 `LLMReportGenerator._build_prompt()` 中，新增一个 section：

```
## 气温影响参考
【热效率数据】
- 本次跑步气温：{min_temp}-{max_temp}°C（中值 {mid_temp}°C）
- 基准温度（15-20°C）下，你在 {ref_power}W 功率输出时平均心率为 {ref_hr} bpm
- 近期高温天（{hot_temp_range}°C）同功率下心率升至 {hot_hr} bpm，上升约 {rise_pct}%
- 本次 Pa:Hr 有氧解耦值：{pa_hr_pct:+.1f}%（{pa_hr_verdict}）

请在教练点评中适当提及气温对训练的影响（如果相关的话）。
```

### 5.3 基准值计算方法
- 基准温度：15-20°C 区间
- 基准功率：取本次跑步的 avg_power 所在 5W 区间
- 从历史数据中找同一分类、同一功率区间、基准温度下的平均心率
- 高温区间：25-30°C，同样分类 + 功率区间的平均心率

如果样本不足（任一 <3），省略该段落或简化表述。

---

## 六、改动清单

### 6.1 文件与改动概览
| # | 文件 | 改动类型 | 预估行数 |
|---|------|---------|---------|
| 1 | `src/deep_analyzer.py` | 新增 `_calc_pa_hr()` 方法；修改 `analyze()` 注入 Pa:Hr 到 result；修改 `LLMReportGenerator._build_prompt()` 注入气温参考 | +120 |
| 2 | `src/analysis_report.py` | 模板新增「🔄 有氧解耦分析」section（含表格 + 历史趋势图）；`generate()` 方法接收 pa_hr 参数 | +100 |
| 3 | `src/chart_generator.py` | 新增 `create_power_hr_temp_chart()` 方法；新增 `create_pa_hr_trend_chart()` 方法；`generate_all_charts()` 注册新图表 | +200 |
| 4 | `src/report_generator.py` | 模板新增「🌡️ 气温-功率-心率分析」section（含分类切换 + 图表 + 表格）；数据准备逻辑 | +150 |
| 5 | `main.py` | 深析函数传递 pa_hr 数据；综合报告传递 power_hr_temp 图表 | +30 |

### 6.2 详细改动

#### 6.2.1 `src/deep_analyzer.py`

**新增方法** `DeepRunAnalyzer._calc_pa_hr(laps: list[dict]) -> Optional[dict]`：
```python
def _calc_pa_hr(self, laps: list[dict]) -> Optional[dict]:
    """
    计算 Pa:Hr 有氧解耦指标
    
    Args:
        laps: 分圈数据列表，每个 dict 包含:
            - distance: 圈距离（米）
            - duration: 圈时长（秒）
            - avg_hr: 平均心率（bpm，可能为 None/NaN）
    
    Returns:
        dict 或 None（lap 数据不足或总距离 <3km）
    """
```
核心逻辑：
1. 过滤无效 lap（distance <= 0 或 duration <= 0）
2. 累计距离 ≥ 3000m 才计算
3. 按距离中点拆分前后半程
4. 加权平均心率（权重 = 每圈时长）
5. 计算 ratio1, ratio2, pa_hr_pct
6. 按解读标准映射 verdict + class + emoji

**修改 `analyze()` 方法**：
```python
result['pa_hr'] = self._calc_pa_hr(laps_list) if laps_list else None
```
其中 `laps_list` 从 `self.lap_data.get('current', [])` 获取。

**修改 `LLMReportGenerator._build_prompt()`**：
在 prompt 末尾「关键发现」之前，新增 section：
```
## 气温与热影响
[动态生成，见 5.2]
```
需要 `self.df_all` 来查询历史基准数据，在 `__init__` 中传入或在 `generate()` 时传入。

#### 6.2.2 `src/analysis_report.py`

**修改 `generate()` 方法签名**：
```python
def generate(self, analysis_data: dict, llm_report: str,
             lap_pace_chart_html: str = '', lap_hr_chart_html: str = '',
             lap_count: int = 0, pa_hr: dict = None, pa_hr_history: list = None) -> str:
```

**模板新增 section**（在对比分析 section 之后）：
```html
<div class="section">
    <h2>🔄 有氧解耦分析（Pa:Hr）</h2>
    {% if pa_hr %}
    <!-- 本次 Pa:Hr 卡片 -->
    <div class="pa-hr-card">
        <table>...</table>
    </div>
    {% else %}
    <p style="color:#999;">距离不足或无分圈数据，无法计算 Pa:Hr</p>
    {% endif %}
    
    <!-- 历史趋势图 -->
    <div id="pa-hr-trend-chart" style="border-radius:8px;overflow:hidden;margin-top:16px;"></div>
</div>
```

Pa:Hr 卡片 HTML 结构：
```html
<table class="pa-hr-table">
    <thead>
        <tr><th></th><th>前半程</th><th>后半程</th></tr>
    </thead>
    <tbody>
        <tr><td>配速</td><td>{first_pace}</td><td>{second_pace}</td></tr>
        <tr><td>心率</td><td>{first_hr} bpm</td><td>{second_hr} bpm</td></tr>
        <tr><td>效率比</td><td>{ratio1}</td><td>{ratio2}</td></tr>
    </tbody>
</table>
<div class="pa-hr-verdict">Pa:Hr: <span class="badge-{class}">{pa_hr_pct:+.1f}% {emoji} {verdict}</span></div>
```

#### 6.2.3 `src/chart_generator.py`

**新增方法 1** `create_power_hr_temp_chart(df, category)`:
- 按 category 过滤 df
- 过滤 `avg_power > 0` 且有气温数据的行
- 按 5W 分箱 power_bin，按 5°C 分箱 temp_bin
- 每个 (power_bin, temp_bin) 计算 avg_hr 和 count
- 生成 Plotly 分组柱状图
- 同时返回表格数据 dict

**新增方法 2** `create_pa_hr_trend_chart(pa_hr_history)`:
- 输入：`list[dict]`，每个 dict 含 date, category, category_color, category_icon, distance, mid_temp, pa_hr_pct, pa_hr_abs
- 生成 Plotly 折线图，带背景色带
- 按 5.7 的规范

**修改 `generate_all_charts()`**：
注册新图表生成调用。

#### 6.2.4 `src/report_generator.py`

**修改 `_render_jinja2()` 和 `_render_fallback()`**：
- 新增参数 `power_hr_temp_data: dict`（包含分类列表、各分类图表 JSON、各分类表格数据）

**模板新增 section**（在气温 section 之后）：
```html
{% if power_hr_temp_data %}
<div class="section">
    <h2 class="section-title"><span class="icon">🌡️</span>气温-功率-心率分析</h2>
    <!-- 分类标签按钮组 -->
    <div class="category-tabs" id="power-temp-tabs">
        {% for cat in power_hr_temp_data.categories %}
        <button class="tab-btn {% if loop.first %}active{% endif %}" 
                data-category="{{ cat }}" 
                style="--cat-color: {{ power_hr_temp_data.cat_info[cat].color }}">
            {{ power_hr_temp_data.cat_info[cat].icon }} {{ power_hr_temp_data.cat_info[cat].name }}
        </button>
        {% endfor %}
    </div>
    <!-- 图表容器 -->
    <div id="chart-power-temp" class="chart-container"></div>
    <!-- 表格容器 -->
    <div id="power-temp-table-container"></div>
</div>
{% endif %}
```

**JS 切换逻辑**：预渲染 `window.POWER_TEMP_CHARTS` 和 `window.POWER_TEMP_TABLES` 变量，按钮点击时切换。

#### 6.2.5 `main.py`

**修改深析函数**（`_generate_deep_report` 或等效函数）：
- 计算 pa_hr 并传递给 `AnalysisReportGenerator.generate()`
- 生成 pa_hr_history 数据（从 parquet 缓存提取所有 ≥3km 跑步的 Pa:Hr）

**修改综合报告函数**：
- 为有功率 + 气温数据的分类生成 power_hr_temp 图表数据
- 传递给 `ReportGenerator.generate_html()`

---

## 七、技术约束

1. **XSS 防护**：所有用户输入在模板中必须 html.escape 或使用 Jinja2 autoescape
2. **Plotly 版本**：保持 CDN 版本 2.27.0 兼容
3. **NaN 处理**：心率、功率字段可能为 None/NaN，计算时需过滤
4. **样本门槛**：
   - Pa:Hr：≥3km，lap 数据有效
   - Pa:Hr 历史趋势：≥3 次历史样本
   - 功率法图表：每个功率箱 ≥2 样本，每个分类 ≥5 样本
   - 热效率基准值：每个区间 ≥3 样本
5. **性能**：综合报告生成时，功率法图表需遍历所有分类，注意不要 N² 复杂度
6. **向后兼容**：所有新参数有默认值，不传不报错，老报告不受影响

---

## 八、验收标准

1. 生成一次深析报告（≥3km，有 lap 数据），报告中出现 Pa:Hr 卡片和历史趋势图
2. 生成一次综合报告（有功率数据），报告中出现气温-功率-心率分析 section
3. 分类切换功能正常，每个分类显示独立图表和表格
4. Pa:Hr 计算结果与手工验算一致（用已知 lap 数据验算）
5. 所有边界条件处理正确（无 lap 数据、无功率数据、样本不足等）
6. 代码通过 `python -m py_compile` 语法检查
