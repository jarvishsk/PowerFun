# PowerFun Round 4 修复 PRD（低风险批处理）

## 背景
低风险增量审阅报告：`/Users/jarvis/.openclaw/workspace/tmp/powerfun_lowrisk_audit.md`（约 50 条发现，先读它作为清单依据）。
本轮只做低风险批处理，不改任何业务行为。

## 工作目录
`~/Projects/skills/PowerFun`

## 修复范围

### P0-1：`fetch_all_laps.py` 的 `fail_count` 崩溃 bug
- 现状：`fail_count = 0` 在模块级（约 100 行），`fail_count += 1` 在 `fetch_lap_data()` 函数内（约 77 行），无 `global` 声明，拉取失败时会 `UnboundLocalError`。
- 修复：在函数内加 `global fail_count`，或更优——把计数逻辑重构为返回值/参数传递，消除模块级可变状态。选最小改动方案。

### P0-2：核对 `src/deep_analyzer.py` 第 104 行附近的 `_call_llm` 调用
- 审阅报告称"timeout 误传为 port"。读取该调用点，若确实存在 positional 参数错位则修复；若审计误报，在报告中说明即可，不改。

### P1：抽公共 helper（消除重复）
1. **iCloud 复制逻辑**（main.py 中 3 处重复：`mkdir → unlink(missing_ok=True) → shutil.copy2`）→ 抽成单个 helper 函数。
2. **配速/时间格式化**（多个模块重复的秒→mm:ss 等格式化）→ 集中到一处（如 `src/utils.py` 或现有合适的模块），各调用点引用。
3. **深析历史过滤逻辑**（main.py 与 deep_analyzer.py 中重复的"同类+排除本次+日期过滤"片段）→ 抽 helper。
4. **分圈统计逻辑**（若 `_analyze_laps` 与 chart_generator 有明显重复的聚合片段）→ 能抽则抽，抽不了就在报告中说明。
- 注意：抽取后行为必须与现状完全一致，优先纯移动代码。

### P2：魔法数字收编进 `src/config.py`
- `N = 100`（深析历史分圈样本上限）
- `fetch_all_laps.py` 的批次/频率参数（batch_size、2 秒间隔等）
- 数据校验阈值（data_processor 中的校验阈值）
- 跑分类阈值（classifier 中的分类阈值）
- 心率区间 int 截断重叠问题：**先确认是否为真 bug**（如下一区间 min 与上一区间 max 因 int() 截断产生重叠/空洞），是真 bug 才修，并保证区间语义不变；存疑则在报告中记录、不改。

### P3：死代码/过期注释清理
- `pa_hr_history = []` 死变量（main.py 两处）
- `GARMIN_API` 死配置（确认无引用后删除）
- 审阅报告中列出的其他死代码/过期注释项
- 删除前必须 grep 确认无引用。

## 明确不做
- 不改 1km 分圈假设、残圈逻辑、不做距离/温度分层
- 不改报告样式/文案
- 不重构架构、不换依赖
- 不改 Round 1-3 已修内容的行为

## 测试要求
1. `python3 main.py` 正常模式跑通（主报告 + 最新深析报告生成）。
2. `python3 main.py --load-parquet --deep-analyze "2026-08-10"` 跑通。
3. `python3 fetch_all_laps.py --help` 或干跑其入口确认 fail_count 修复无语法/运行错误（不必真的全量拉取）。
4. 重构前后主报告关键区块一致（13 张图、表格在底部、链接数 59）。

## 输出要求（必须）
完成后把成果写入 `/Users/jarvis/.openclaw/workspace/tmp/powerfun_round4_fix_report.md`：修改清单、关键代码说明、测试结果、遗留问题（包括审计误报项）。不要只在会话里回复。不要执行 git commit。
