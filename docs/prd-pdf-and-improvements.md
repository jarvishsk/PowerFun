# PowerFun 跑分技能改进 PRD

**日期**: 2026-06-08
**需求来源**: 老板
**Coder**: agentId=coder

---

## 需求概览

| # | 需求 | 优先级 |
|---|------|--------|
| 1 | LLM 调用超时 + 重试优化 | P0 |
| 2 | 报告末尾信息更新 | P1 |
| 3 | 独立 PDF 生成模块（触发词：跑分PDF） | P0 |
| 4 | PDF 手机端适配（iPhone 390px） | P0 |

---

## 需求 1：LLM 调用超时 + 重试优化

### 问题
oMLX 冷启动加载模型耗时长，当前 120s 超时不够，导致首次调用失败。

### 位置
`src/deep_analyzer.py` → `LLMReportGenerator._call_llm()` 静态方法

### 当前逻辑（已有重试，需调整参数）
```python
for attempt in range(3):
    # 超时 120s → 改为 240s
    # 固定等待 3s → 改为指数退避
```

### 修改要求
1. **超时**: `timeout=120` → `timeout=240`
2. **重试间隔**: 固定 `time.sleep(3)` → 指数退避
   - 第 1 次重试: `time.sleep(5)`
   - 第 2 次重试: `time.sleep(15)`
3. **日志**: 每次重试打印 `logger.warning(f"LLM 调用失败，第 {attempt+1}/3 次重试: {e}")`

---

## 需求 2：报告末尾信息更新

### 2a. 深度分析报告

**位置**: `src/analysis_report.py` → Jinja2 模板中的 `<div class="footer">`

**当前**:
```
PowerFun v{{ version }} | 数据来自 Garmin Connect | 生成时间：{{ generated_at }}
```

**改为**:
```
PowerFun v{{ version }} | AI分析由 {{ model_name }} 完成 | 生成时间：{{ generated_at }}
```

**实现**:
- 在 `config.py` 的 `LLM_CONFIG` 中新增 `'display_name': 'MiMo v2.5 Pro'` 字段
- `AnalysisReportGenerator.generate()` 接收 `model_name` 参数，传入模板
- 调用方从 `LLM_CONFIG['display_name']` 读取并传入

### 2b. 综合分析报告

**位置**: `src/report_generator.py` → Jinja2 模板 footer

**当前**:
```
🏃 综合分析报告 v{{ version }} | 数据来自 Garmin Connect
```

**改为**:
```
🏃 综合分析报告 v{{ version }} | AI分析由 {{ model_name }} 完成
```

**实现**: 同上，`generate_report()` 方法接收 `model_name` 参数传入模板。

---

## 需求 3：独立 PDF 生成模块

### 概述
新建独立模块 `src/pdf_generator.py`，当用户说"跑分PDF"时触发。

### 触发词
- `跑分PDF`
- `生成跑分PDF`

### 功能
1. 读取综合分析报告 HTML: `~/Documents/Run/PowerFun.html`
2. 读取最新深度分析报告 HTML: `~/Documents/Run/PowerFun_Reports/run_analysis_*.html`（取最新一份）
3. 使用 Playwright 将两个 HTML 转为 PDF
4. 输出到 iCloud:
   - `~/Library/Mobile Documents/com~apple~CloudDocs/RUN/综合分析报告.PDF`
   - `~/Library/Mobile Documents/com~apple~CloudDocs/RUN/深度分析报告.PDF`
5. **覆盖策略**: 先删除旧文件，再写入新文件

### SKILL.md 更新
在 PowerFun 技能的 SKILL.md 中增加触发词 `跑分PDF`，并说明该功能独立于数据分析流程。

---

## 需求 4：PDF 手机端适配

### 参数
- **宽度**: 390px（iPhone 视口宽度）
- **高度**: 自动撑开（不分页截断）
- **Playwright 参数**:
  ```python
  page.set_viewport_size({"width": 390, "height": 844})
  page.pdf(
      width="390px",
      height=f"{actual_height}px",  # 从 scrollHeight 获取
      print_background=True,
      margin={"top": "0", "right": "0", "bottom": "0", "left": "0"}
  )
  ```

### 注意事项
- HTML 中的 Plotly 图表需要 `include_script_tag=True` 或等效处理
- 确保 CSS 在 390px 宽度下正确响应（可能需要微调 report CSS）
- PDF 生成完成后检查文件大小（目标 < 5MB）

---

## 技术约束

- 不改变现有数据流（parquet 是唯一数据源）
- PDF 模块完全独立，不影响现有分析流程
- Playwright 已安装，可直接使用
- 所有路径使用 `pathlib.Path`

## 验收标准

1. ✅ 模型调用失败时自动重试 3 次，超时 240s，指数退避
2. ✅ 深析报告末尾显示 "AI分析由 MiMo v2.5 Pro 完成"
3. ✅ 综合报告末尾同上
4. ✅ 说"跑分PDF"后，iCloud 目录下生成两个 PDF 文件
5. ✅ PDF 在 iPhone 上宽度合适，内容完整不截断
