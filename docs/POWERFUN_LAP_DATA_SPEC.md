# PowerFun 分圈数据需求文档

> 创建时间: 2026-05-05
> 负责人: Coder Agent（开发）+ 主 Agent（验收）
> 项目位置: `/Users/jarvis/Projects/skills/PowerFun`

---

## 一、背景

当前 PowerFun 只获取活动级别的汇总数据（总距离、总配速、总心率等），不支持分圈/分段（Lap/Split）数据。需要从 Garmin API 获取每公里的详细数据，本地持久化，并用于深度分析报告。

## 二、Garmin API 分圈数据源

Garmin API 提供 `get_activity_splits(activity_id)` 接口，返回 `lapDTOs` 数组，每个 Lap 对象包含以下字段：

| 字段（API原始名） | 含义 | 类型 |
|---|---|---|
| `lapIndex` | 圈序号（从 1 开始） | int |
| `distance` | 该圈距离（米） | float |
| `duration` | 该圈时长（秒） | float |
| `averageHR` | 该圈平均心率 | int |
| `maxHR` | 该圈最大心率 | int |
| `averagePower` | 该圈平均功率（W） | float |
| `averageRunCadence` | 该圈平均步频 | float |
| `elevationGain` | 该圈累计爬升（米） | float |

**注意**：当前项目使用 `garth` 库（`garth.connectapi`），不是 `garminconnect` Python SDK。需要找到 garth 对应的 API 端点来获取分圈数据。参考 `garminconnect` SDK 中 `get_activity_splits` 的实现，端点应为：
```
/activity-service/activity/{activityId}/laps
```
通过 `garth.connectapi(f"/activity-service/activity/{activity_id}/laps")` 调用。

## 三、需求清单

### 需求 1：分圈数据获取（data_fetcher.py）

**文件**: `src/data_fetcher.py`

**要求**:
- 新增方法 `fetch_lap_data(activity_id: int) -> list[dict]`
  - 调用 garth API 获取该活动的分圈数据
  - 返回标准化的分圈列表（映射为内部字段名）
  - 异常时返回空列表并记录 warning 日志
- 该方法独立于 `fetch_activity_detail`，按需调用

### 需求 2：分圈数据存储（增量 + 首次全量）

**原则**: 分圈数据与基础数据一样，本地持久化，分析时从本地读取。

**文件**: `src/data_fetcher.py` + `main.py`

**要求**:
- 首次全量拉取时，对每条跑步活动调用 `fetch_lap_data` 获取分圈数据
- 后续增量拉取时，仅对新增活动获取分圈数据
- 存储格式：单独的文件（如 `.data/lap_data.parquet`），按 `activity_id` 关联
- 新增方法 `_save_lap_cache(laps: list[dict])` / `_load_lap_cache(activity_id: int)` 或类似机制
- 在 `main.py` 的数据拉取流程中，清洗保存 parquet 后、报告生成前，增加分圈数据拉取与合并步骤

### 需求 3：分圈数据注入深度分析（deep_analyzer.py）

**文件**: `src/deep_analyzer.py`

**要求**:
- `DeepRunAnalyzer.__init__` 新增参数 `lap_data: dict`（传入当前活动的分圈列表）
- `analyze()` 方法新增返回值字段 `laps`（分圈数据列表）
- `_extract_raw_data()` 新增字段：`lap_count`（圈数）
- `_generate_brief_summary()` 中 max_tokens 改为 **2000**
- 新增 `_analyze_laps(lap_data: list[dict], recent_laps: list[list[dict]]) -> dict` 方法：
  - 输入：本次分圈数据 + 前 N 次（同类型，N=min(5, 可用次数)）的分圈数据
  - 输出：包含每圈的配速对比、心率对比、历史均值/最高/最低配速
  - 配速计算：`pace_sec_per_km = duration / (distance / 1000)`
- `_build_llm_prompt()` 增加分圈数据段落（详见需求 5）

### 需求 4：分圈数据图表（chart_generator.py）

**文件**: `src/chart_generator.py`

**要求**:
- 新增方法 `generate_lap_pace_chart(lap_data: list[dict], recent_laps: list[list[dict]], cat_name: str) -> str`
- 返回 Plotly 图表的 JSON（与现有 `generate_all_charts` 风格一致）

**图表规格**:

| 要素 | 要求 |
|---|---|
| **X 轴** | 公里数（1KM, 2KM, 3KM...），整数刻度 |
| **Y 轴** | 配速（秒/KM），注意：数值越小越快 |
| **折线 1** | 本次分段配速（平滑曲线，使用 `line.shape='spline'`） |
| **折线 2** | 本次分段心率（次/分钟，用右侧 Y 轴或次图） |
| **折线 3** | 前 N 次同类型平均配速（平滑曲线，虚线） |
| **区域填充** | 前 N 次同类型的 P20-P80 配速区间用颜色填充（注意：配速数值小=快，P20=较快侧，P80=较慢侧；样本 <8 时降级只显示中位线，不画区间） |
| **配色** | 本次配速用主色（如蓝色），心率用红色，历史平均用灰色虚线，填充区域用浅蓝半透明 |

**关键细节**:
- **平滑曲线**：使用 Plotly 的 `line.shape='spline'`，不要用均值聚合
- **前 N 次**：同类型跑步（`easy_run`/`aerobic_run`/`lsd`/`race_event`），N = 10（P20-P80 百分位统计需要足够样本）；样本 <8 时降级只画中位线
- **P20/P80 分位数**：对每个公里序号 K，先对样本做 IQR 异常值过滤（剔除 [Q1-1.5×IQR, Q3+1.5×IQR] 之外的值），再用 numpy 线性插值计算 P20/P50/P80
- **Y 轴反转**：配速越小表示越快，Y 轴需要 `autorange='reversed'`
- **心率双轴**：可以用 `make_subplots(specs=[[{"secondary_y": True}]])` 实现左右双 Y 轴

### 需求 5：LLM Prompt 增加分圈数据

**文件**: `src/deep_analyzer.py` 的 `_build_llm_prompt()` 方法

**要求**:
- 在 Prompt 中新增一个 `## 分圈数据分析` 段落
- 列出本次每圈的配速、心率、功率（简洁格式）
- 列出历史同类型该圈的平均配速范围
- 新增要求 LLM 解读分圈表现的指令（如配速是否均匀、心率漂移等）
- 总字数限制从 800 字改为 **1200 字**
- `max_tokens` 统一改为 **2000**

### 需求 6：报告模板嵌入分圈图表

**文件**: `src/analysis_report.py`

**要求**:
- 在深析报告 HTML 模板中，分圈图表排在"强度和负荷"之后、"历史对比"之前
- 如果分圈数据为空，跳过该图表，不报错

### 需求 7：main.py 流程整合

**文件**: `main.py`

**要求**:
- 数据拉取阶段（`_main_inner`）：清洗保存 parquet 后，对每条新增跑步活动拉取分圈数据并持久化
- 报告生成阶段（`_generate_deep_report` / Step 8）：
  - 从本地加载本次跑步的分圈数据
  - 从本地加载前 N 次同类型的分圈数据
  - 传入 `DeepRunAnalyzer` 和 `ChartGenerator`
- `--load-parquet` 模式也能正常加载分圈数据

---

## 四、分圈数据结构定义

### 本地存储格式（`.data/lap_data.parquet`）

| 列名 | 类型 | 说明 |
|---|---|---|
| `activity_id` | int | Garmin 活动 ID |
| `lap_index` | int | 圈序号（从 1 开始） |
| `distance_m` | float | 该圈距离（米） |
| `duration_sec` | float | 该圈时长（秒） |
| `pace_sec_per_km` | float | 该圈配速（秒/KM） |
| `avg_hr` | int/NaN | 该圈平均心率 |
| `max_hr` | int/NaN | 该圈最大心率 |
| `avg_power` | float/NaN | 该圈平均功率（W） |
| `cadence` | float/NaN | 该圈平均步频 |
| `elevation_gain_m` | float | 该圈累计爬升（米） |

### 深析分析输出（`analysis_data['laps']`）

```python
{
    'current': [  # 本次分圈
        {'lap': 1, 'pace_sec': 330.5, 'avg_hr': 145, 'avg_power': 210, 'elevation_gain': 5},
        {'lap': 2, 'pace_sec': 325.0, 'avg_hr': 148, 'avg_power': 215, 'elevation_gain': 3},
        ...
    ],
    'history_avg': [  # 前 N 次同类型平均
        {'lap': 1, 'pace_sec': 335.0, 'avg_hr': 143},
        {'lap': 2, 'pace_sec': 330.0, 'avg_hr': 146},
        ...
    ],
    'history_max_pace': [...],  # 前 N 次每圈最慢配速（秒数最大）
    'history_min_pace': [...],  # 前 N 次每圈最快配速（秒数最小）
    'sample_size': 3,  # 实际用于对比的同类型次数
}
```

---

## 五、验收标准

1. `python main.py --days 7` 能正常拉取数据，包含分圈数据
2. `python main.py --load-parquet --deep-analyze 2026-05-05` 深析报告包含分圈图表
3. 分圈图表：平滑折线、心率双轴、历史平均虚线、填充区域均正常渲染
4. LLM 分析报告包含分圈解读段落
5. `--load-parquet` 模式下不触发任何 API 调用
6. 没有分圈数据的活动（如旧设备记录）不报错，跳过该图表
7. 所有新增代码有中文注释
8. 代码风格与现有项目一致（PEP 8，命名规范）

---

## 六、约束

- **不要修改跑步分析报告**（主报告），只改深度分析报告
- **不要修改已有图表**，只新增
- 遇到 Garmin API 相关问题，上报主 Agent，不要自行猜测
- 保持向后兼容，已有功能不受影响
