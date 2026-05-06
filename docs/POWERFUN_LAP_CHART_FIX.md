# PowerFun 每KM数据图表修正需求

> 创建时间: 2026-05-05
> 项目位置: `/Users/jarvis/Projects/skills/PowerFun`

---

## 背景

上一轮新增了"分圈配速分析"图表（每KM数据），但存在以下问题需要修正：
1. 图表 JSON 原样输出未渲染 → 已在 analysis_report.py 中修复（加了 Plotly CDN + `Plotly.newPlot`）
2. 配速显示、距离对齐、图表拆分等需求待实现

---

## 需求清单

### 需求 1：配速显示格式 → "分:秒/KM"

**文件**: `src/chart_generator.py` — `generate_lap_pace_chart` 方法

**要求**:
- hovertemplate 中的配速格式统一为 `X:XX/KM`（如 `6:28/KM`）
- Y 轴 tickformat 也要显示为分:秒格式
- 当前代码使用 `tickformat='%M:%S'` 可能有问题（这是分钟:秒的时间格式），需要确认是否能正确将秒数（如 388）显示为 `6:28`
- 如果不能，使用自定义 ticktext

### 需求 2：距离取整，图表 KM 数以总距离向下取整为准

**文件**: `src/chart_generator.py` — `generate_lap_pace_chart` 方法

**要求**:
- 计算本次跑步总距离（所有 lap 的 distance_m 之和），向下取整得到 `total_km`
- 图表只显示 1KM 到 total_km 的分圈
- 如果最后一个 lap 不足 1KM，不计入图表 X 轴
- 历史数据同理，只取到 total_km

**举例**: 本次跑了 25.3 公里，图表 X 轴只显示 1KM ~ 25KM

### 需求 3：历史数据距离不足时，用其他历史均值填充

**文件**: `src/chart_generator.py` — `generate_lap_pace_chart` 方法

**要求**:
- 对于每个 KM 序号 K（1 到 total_km），计算历史均值/最高/最低时：
  - 如果某次历史跑步没有第 K 圈的数据，则跳过该次
  - 如果所有历史跑步都有第 K 圈，正常计算
  - 如果部分历史跑步缺少第 K 圈，用**有数据的跑步**计算均值/最高/最低
- 关键变化：不是用其他 KM 的均值填充，而是用**同一 KM 但有数据的历史记录**来计算
- 举例：本次 26KM，5 次历史中 2 次只有 24KM。计算第 25、26KM 的历史均值时，用剩下的 3 次有数据的历史跑步来计算

### 需求 4：拆分为两张图

**文件**: `src/chart_generator.py` 和 `src/analysis_report.py`

**要求**:
- 原 `generate_lap_pace_chart` 拆为两个方法：
  1. `generate_lap_pace_chart_v2()` → 每KM配速图
  2. `generate_lap_hr_chart()` → 每KM心率图

**每KM配速图**:
- X 轴：公里数（1, 2, 3...N）
- Y 轴：配速（秒/KM，反转，越小越快），tick 格式：`X:XX/KM`
- 蓝色平滑曲线：本次配速（markers + lines，shape='spline'）
- 灰色虚线：历史平均配速（shape='spline'）
- 浅蓝填充：历史最高配速 vs 历史最低配速区间（toself）
- 图例：本次配速、历史均配速、历史配速区间

**每KM心率图**:
- X 轴：公里数（1, 2, 3...N）
- Y 轴：心率（bpm），正常方向
- 蓝色平滑曲线：本次心率（markers + lines，shape='spline'）
- 灰色虚线：历史平均心率（shape='spline'）
- 浅蓝填充：历史最高心率 vs 历史最低心率区间（toself）
- 图例：本次心率、历史均心率、历史心率区间

**analysis_report.py 模板修改**:
- 将原来的一个 `lap_chart_html` 拆为 `lap_pace_chart_html` 和 `lap_hr_chart_html`
- 标题改为"每KM数据"作为大类，下面两张子图
- 或者两个独立的 section，标题分别为"📊 每KM配速"和"📊 每KM心率"

**main.py 调用点修改**:
- `_generate_deep_report()` 和 Step 8 中，改为调用两个图表方法
- 传入两个 HTML 字符串给 `AnalysisReportGenerator.generate()`

### 需求 5：AI 教练点评标题与内容之间不隔行

**文件**: `src/analysis_report.py` — `markdown_to_html` 函数

**要求**:
- 当前 LLM 报告的 `<h3>` 标签和内容之间有多余的空行/`<br>`
- 修改 `markdown_to_html`，使 `<h3>` 后面不要额外添加 `<br>`
- 当前逻辑是 `'<br>'.join(result)`，每一行都用 `<br>` 连接
- 需要改为：`<h3>` 后面的内容直接跟在后面，不用 `<br>` 分隔
- 或者调整模板中 `.llm-report` 的样式

---

## 数据结构

### 方法签名变更

```python
def generate_lap_pace_chart_v2(self, lap_data: list[dict], recent_laps: list[list[dict]],
                                cat_name: str = '') -> str:
    """生成分圈配速对比图表（独立图）"""

def generate_lap_hr_chart(self, lap_data: list[dict], recent_laps: list[list[dict]],
                           cat_name: str = '') -> str:
    """生成分圈心率对比图表（独立图）"""
```

### analysis_report.py generate 方法签名

```python
def generate(self, analysis_data: dict, llm_report: str,
             lap_pace_chart_html: str = '', lap_hr_chart_html: str = '',
             lap_count: int = 0) -> str:
```

---

## 验收标准

1. 配速显示为 `X:XX/KM` 格式（如 `6:28/KM`）
2. 距离取整：25.3KM 只显示 1~25KM
3. 历史数据不足时，用可用的历史值计算均值
4. 两张独立图表：配速图和心率图，都有平滑曲线 + 历史均值 + 区间填充
5. AI 教练点评的 h3 标题与内容之间无多余空行
6. 重新生成 5月3日的深析报告，打开 HTML 确认图表正常渲染
7. 语法检查通过
8. 向后兼容：无分圈数据时不报错
